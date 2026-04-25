#!/usr/bin/env python3
"""PROP-style coinbaser for BlakeStream Eloipool post-SegWit release.

eloipool calls this script every time it builds a new block template. Our job
is to write a coinbase output split to stdout in eloipool's
CoinbaserCmd protocol:

    <num_outputs>
    <satoshi_amount_1>
    <address_1>
    <satoshi_amount_2>
    <address_2>
    ...

eloipool reads those outputs from stdout, adds them to the coinbase
transaction, and any leftover satoshis (the unaccounted-for portion of
coinbaseValue) flow to config.TrackerAddr — the pool wallet — automatically.

How the split is computed
=========================
1. Read the last N shares from the share log (N controlled by COINBASER_WINDOW)
2. For each share, parse the stratum username through resolve_payout_address()
   from the canonical mining_key module. The 4-step rule from MINING-KEY.md:
       a. strip optional .workername
       b. if the head is a direct Blakecoin address (bech32/legacy/p2sh), use it
       c. else if the head is exactly 40 hex chars, treat it as a mining key
          and derive the payout via address_from_v2_mining_key(key, hrp)
       d. else skip the share (no payout, no dilution of other miners)
3. Group by resolved address, count shares per address.
4. Reserve POOL_KEEP_BPS basis points (default 100 = 1%) for the pool wallet.
5. Split the remainder proportionally to share count.

This is PROP (proportional) when COINBASER_WINDOW spans the current round, and
PPLNS (pay-per-last-N-shares) when it spans more than one round.

Mining key support unlocks merged mining: a single bare 40-char stratum
username produces a different derived bech32 payout address per chain (one
HRP per chain), which is the only way to express "pay me on six chains"
through the single-string stratum auth field. Without it the username can
only carry one chain's address. See MINING-KEY.md for the design.

Edge cases
==========
- No share log yet, or no shares with resolvable addresses → emit zero
  outputs. Whole reward goes to TrackerAddr by default.
- Single miner → that miner gets the full payable amount.
- Rounding remainder → assigned to the smallest miner so the total emitted
  exactly equals the payable amount (no satoshi loss).
- Total emitted MUST be strictly less than coinbaseValue or eloipool fails the
  template build. We reserve POOL_KEEP_BPS + at least 1 satoshi.
- Mining-key share but COINBASER_MINING_KEY_SEGWIT_HRP unset → resolve
  returns kind=mining_key_v2 with address=None; the share is treated as
  unresolvable and dropped, same as a misconfig label.

Environment variables
=====================
    COINBASER_SHARE_LOG               path to eloipool's share log (default
                                      /var/log/blakecoin-pool/share-logfile)
    COINBASER_WINDOW                  how many recent shares to consider (default 20)
    COINBASER_POOL_KEEP_BPS           basis points reserved for pool wallet
                                      (default 100 = 1%)
    COINBASER_MINING_KEY_SEGWIT_HRP   HRP used for bare mining-key usernames.
                                      Required for V2/bech32 mining-key
                                      payouts. If unset, mining-key usernames
                                      are recognized but treated as unpayable.
    COINBASER_DEBUG_LOG               if set, append a JSONL trace of every
                                      invocation here for debugging
    COINBASER_ELOIPOOL_DIR            override path to the eloipool tree (used
                                      to find the mining_key module). Default:
                                      auto-discovered.

Usage in eloipool config.py:
    CoinbaserCmd = '/opt/blakecoin-pool/bin/coinbaser.py %d %p'
"""

import json
import os
import sys
import time
from collections import Counter
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from pathlib import Path


# ---------------------------------------------------------------------------
# Path discovery: find the eloipool tree so we can import the canonical
# mining_key module. Same pattern as dashboard.py + mining_key.py itself.
# ---------------------------------------------------------------------------

def _find_mining_key_module():
    here = Path(__file__).resolve().parent
    candidates = [
        here / 'eloipool',                                  # bundle layout: coinbaser.py at bundle root
        here.parent / 'eloipool',                           # if coinbaser is one level deeper
        Path('/opt/blakecoin-pool/eloipool'),               # VPS deploy layout
        Path(os.environ.get('COINBASER_ELOIPOOL_DIR', '')),
    ]
    for c in candidates:
        if c and (c / 'mining_key.py').is_file():
            if str(c) not in sys.path:
                sys.path.insert(0, str(c))
            return c
    return None
_ELOIPOOL_DIR = _find_mining_key_module()

try:
    from mining_key import resolve_payout_address
except ImportError as _e:
    sys.stderr.write(
        f'coinbaser: failed to import mining_key module: {_e}\n'
        f'  search candidates: {_ELOIPOOL_DIR}\n'
        f'  set COINBASER_ELOIPOOL_DIR env var to override\n'
    )
    resolve_payout_address = None


SHARE_LOG       = os.environ.get('COINBASER_SHARE_LOG', '/var/log/blakecoin-pool/share-logfile')
WINDOW          = int(os.environ.get('COINBASER_WINDOW', '20'))
POOL_KEEP_BPS   = int(os.environ.get('COINBASER_POOL_KEEP_BPS', '100'))
MINING_KEY_SEGWIT_HRP = os.environ.get('COINBASER_MINING_KEY_SEGWIT_HRP', '').strip() or None
DEBUG_LOG       = os.environ.get('COINBASER_DEBUG_LOG', '')


def resolve_username_detail(user):
    """Resolve a stratum username to its payout target plus metadata."""
    if not user or resolve_payout_address is None:
        return {
            'address': None,
            'kind': 'skip',
            'mining_key': None,
            'addr_type': 'none',
        }
    resolved = resolve_payout_address(user, None, MINING_KEY_SEGWIT_HRP)
    if not isinstance(resolved, dict):
        return {
            'address': None,
            'kind': 'skip',
            'mining_key': None,
            'addr_type': 'none',
        }
    return {
        'address': resolved.get('address'),
        'kind': resolved.get('kind', 'skip'),
        'mining_key': resolved.get('mining_key'),
        'addr_type': resolved.get('addr_type') or ('none' if not resolved.get('address') else 'unknown'),
    }


def resolve_username(user):
    """Compatibility wrapper returning only (address, kind)."""
    resolved = resolve_username_detail(user)
    return (resolved.get('address'), resolved.get('kind'))


def tail_lines(path, n):
    """Read up to N final lines from a text file."""
    try:
        with open(path, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            buf = b''
            chunk = 8192
            while size > 0 and buf.count(b'\n') <= n + 1:
                back = min(chunk, size)
                f.seek(size - back)
                buf = f.read(back) + buf
                size -= back
        return buf.decode('utf-8', errors='replace').splitlines()[-n:]
    except FileNotFoundError:
        return []
    except Exception:
        return []


def parse_share_line(line):
    """Parse an eloipool share-log line.

    Historical format:
        time host user our_result upstream_result reason solution

    Current extended format:
        time host user our_result upstream_result reason share_diff target_hex solution

    Returns None for malformed input. The returned `weight` is the value that
    should count toward payouts: any line with either local acceptance or
    upstream block acceptance contributes its recorded worker difficulty. Old
    lines without difficulty metadata fall back to weight=1 for compatibility.
    """
    parts = line.split()
    if len(parts) < 7:
        return None
    try:
        ts = float(parts[0])
    except ValueError:
        return None

    accepted_local = parts[3] == 'Y'
    accepted_upstream = parts[4] == 'Y'
    contribution = accepted_local or accepted_upstream

    share_diff = None
    target_hex = None
    solution = parts[6]
    if len(parts) >= 9:
        diff_token = parts[6]
        target_hex = parts[7] if parts[7] != '-' else None
        solution = parts[8]
        if diff_token != '-':
            try:
                share_diff = Decimal(diff_token)
            except InvalidOperation:
                share_diff = None

    if contribution:
        if share_diff is None or share_diff <= 0:
            weight = Decimal(1)
        else:
            weight = share_diff
    else:
        weight = Decimal(0)

    return {
        'time': ts,
        'host': parts[1].strip("'\""),
        'user': parts[2],
        'our_result': accepted_local,
        'upstream_result': accepted_upstream,
        'reason': parts[5] if len(parts) > 5 else '-',
        'share_diff': share_diff,
        'target_hex': target_hex,
        'solution': solution,
        'contribution': contribution,
        'weight': weight,
    }


def compute_splits(total_satoshis, share_lines):
    """Return (list_of_(amount, address), debug_dict) for the given inputs."""
    counts = {}
    recipient_meta = {}
    kind_counts = Counter()      # bookkeeping per resolution kind
    skipped = 0
    total_lines = 0
    counted_lines = 0
    for line in share_lines:
        parsed = parse_share_line(line)
        if parsed is None:
            continue
        total_lines += 1
        resolved = resolve_username_detail(parsed['user'])
        addr = resolved.get('address')
        kind = resolved.get('kind', 'skip')
        kind_counts[kind] += 1
        if not parsed['contribution']:
            continue
        counted_lines += 1
        if not addr:
            skipped += 1
            continue
        counts[addr] = counts.get(addr, Decimal(0)) + parsed['weight']
        if addr not in recipient_meta:
            recipient_meta[addr] = {
                'kind': kind,
                'mining_key': resolved.get('mining_key'),
                'addr_type': resolved.get('addr_type'),
            }

    if not counts:
        return ([], {
            'reason': 'no resolvable shares',
            'skipped': skipped,
            'window': len(share_lines),
            'parsed_lines': total_lines,
            'counted_lines': counted_lines,
            'kind_counts': dict(kind_counts),
            'mining_key_segwit_hrp': MINING_KEY_SEGWIT_HRP,
        })

    payable = total_satoshis * (10000 - POOL_KEEP_BPS) // 10000
    if payable <= 0:
        return ([], {'reason': 'payable<=0 after pool keep', 'total': total_satoshis})

    total_work = sum(counts.values(), Decimal(0))

    # Sort biggest first; allocate floor amounts to all but smallest, give
    # the rounding remainder to the smallest miner so the sum is exact.
    rows = sorted(counts.items(), key=lambda kv: -kv[1])
    splits = []
    distributed = 0
    payable_dec = Decimal(payable)
    for addr, work in rows[:-1]:
        amt = int((payable_dec * work / total_work).to_integral_value(rounding=ROUND_DOWN))
        if amt > 0:
            splits.append((amt, addr))
            distributed += amt
    last_addr, _ = rows[-1]
    last_amt = payable - distributed
    if last_amt > 0:
        splits.append((last_amt, last_addr))

    # Sanity: total emitted must be strictly less than coinbaseValue or
    # eloipool's CoinbaserCmd handler treats it as failure and zeros all
    # outputs (eloipool.py:131-133).
    emitted = sum(a for a, _ in splits)
    if emitted >= total_satoshis:
        # Should never happen with POOL_KEEP_BPS > 0, but be defensive.
        overshoot = emitted - total_satoshis + 1
        splits[-1] = (splits[-1][0] - overshoot, splits[-1][1])
        if splits[-1][0] <= 0:
            splits.pop()
        emitted = sum(a for a, _ in splits)

    debug = {
        'total_satoshis':           total_satoshis,
        'window':                   len(share_lines),
        'unique_miners':            len(counts),
        'parsed_lines':             total_lines,
        'counted_lines':            counted_lines,
        'total_work':               str(total_work),
        'skipped_shares':           skipped,
        'kind_counts':              dict(kind_counts),
        'pool_keep_bps':            POOL_KEEP_BPS,
        'payable':                  payable,
        'emitted':                  emitted,
        'pool_remainder':           total_satoshis - emitted,
        'splits':                   [{
            'addr': a,
            'sat': v,
            'pct': round(100*v/total_satoshis, 2),
            'work': str(counts[a]),
            'kind': recipient_meta.get(a, {}).get('kind'),
            'mining_key': recipient_meta.get(a, {}).get('mining_key'),
            'addr_type': recipient_meta.get(a, {}).get('addr_type'),
        } for v, a in splits],
    }
    return (splits, debug)


def write_debug(debug, prev_block_hash):
    if not DEBUG_LOG:
        return
    try:
        with open(DEBUG_LOG, 'a') as f:
            entry = {'ts': time.time(), 'prev': prev_block_hash}
            entry.update(debug)
            f.write(json.dumps(entry) + '\n')
    except Exception:
        pass


def main():
    if len(sys.argv) < 2:
        sys.stderr.write('usage: coinbaser.py <coinbaseValue_satoshis> [prev_block_hash]\n')
        print(0)
        return
    try:
        total = int(sys.argv[1])
    except ValueError:
        sys.stderr.write('coinbaser: invalid coinbase value: %r\n' % (sys.argv[1],))
        print(0)
        return
    prev = sys.argv[2] if len(sys.argv) > 2 else ''

    lines = tail_lines(SHARE_LOG, WINDOW)
    splits, debug = compute_splits(total, lines)
    write_debug(debug, prev)

    if not splits:
        # Fall through to TrackerAddr
        print(0)
        return

    print(len(splits))
    for amt, addr in splits:
        print(amt)
        print(addr)


if __name__ == '__main__':
    main()
