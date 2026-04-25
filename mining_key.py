"""Mining-key crypto helpers — pure Python port of Blakestream-nomp.

This is the canonical implementation referenced from MINING-KEY.md. Both
``deploy-bundle/dashboard/dashboard.py`` and ``deploy-bundle/coinbaser.py``
import from this module so there is one source of truth for the mining-key
math. Drift between consumers is the failure mode the doc explicitly guards
against ("If these tests drift, cross-pool mining-key compatibility is
broken." — MINING-KEY.md, section "Tested Guarantees").

A "mining key" is the 40-character hex of
``RIPEMD160(SHA256(uncompressed_secp256k1_pubkey))`` for legacy/v1 and
``RIPEMD160(SHA256(compressed_secp256k1_pubkey))`` for native-segwit/v2.

The active release line is post-SegWit and V2-only:

- bare ``<40hex>[.workername]`` is the only accepted mining-key username form
- bare mining keys derive native-segwit/bech32 payouts through the configured
  chain HRP
- prefixed forms such as ``mk1:`` and ``mk2:`` are rejected
- direct legacy/bech32/p2sh payout-address usernames still pass through as-is

Reference (must remain byte-for-byte compatible):
  - Blakestream-nomp/src/stratum/util.ts:74    addressFromEx()
  - Blakestream-nomp/src/stratum/util.ts:60    detectAddressChecksumCodec()
  - Blakestream-nomp/src/stratum/util.ts:86    getVersionByte()
  - Blakestream-nomp/src/bsp/crypto.ts:171     mining key derivation

Stable decisions, per MINING-KEY.md "Stable Decisions":
  - v1 mining keys are derived from UNCOMPRESSED pubkeys.
  - v2 mining keys are derived from COMPRESSED pubkeys.
  - Checksum codec comes from the Ex address chain rules.
  - TrackerAddr and the mining-key Ex address are SEPARATE roles. Do not
    reuse the pool keep wallet as the Ex address.
"""

import hashlib
import os
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Module-level path discovery: find the eloipool tree so blake8 + the vendored
# base58 are importable from any consumer regardless of where the script lives.
#
# Three candidate locations are tried in order:
#   1. The directory this module sits in (top-level eloipool tree)
#      — used when imported from inside the source tree directly.
#   2. The bundle's eloipool/ subdirectory — used when imported from the
#      bundle's dashboard or coinbaser scripts at runtime.
#   3. /opt/blakecoin-pool/eloipool — the on-VPS deploy layout from deploy.sh.
#   4. The MINING_KEY_ELOIPOOL_DIR env var — operator override.
# ---------------------------------------------------------------------------

def _find_eloipool_dir():
    here = Path(__file__).resolve().parent
    candidates = [
        here,                                              # module is at top of the source tree
        here.parent / 'eloipool',                          # module is at bundle root, eloipool/ alongside
        here.parent.parent / 'eloipool',                   # module is one level deeper
        Path('/opt/blakecoin-pool/eloipool'),
        Path(os.environ.get('MINING_KEY_ELOIPOOL_DIR', '')),
    ]
    for c in candidates:
        if c and (c / 'blake8.py').is_file():
            return c
    return None


_ELOIPOOL_DIR = _find_eloipool_dir()
if _ELOIPOOL_DIR is not None:
    if str(_ELOIPOOL_DIR) not in sys.path:
        sys.path.insert(0, str(_ELOIPOOL_DIR))
    _vendor = _ELOIPOOL_DIR / 'vendor'
    if _vendor.is_dir() and str(_vendor) not in sys.path:
        sys.path.insert(0, str(_vendor))

try:
    from blake8 import BLAKE as _BLAKE
    def _blake256(data):
        return _BLAKE(256).digest(data)
except ImportError:
    _blake256 = None    # mining-key features will fail loudly when called

try:
    from base58 import b58encode as _b58encode, b58decode as _b58decode
except ImportError:
    _b58encode = _b58decode = None

try:
    from bitcoin import segwit_addr as _segwit_addr
except ImportError:
    _segwit_addr = None


# ---------------------------------------------------------------------------
# Hash primitives
# ---------------------------------------------------------------------------

def _sha256(data):
    return hashlib.sha256(data).digest()


def _sha256d(data):
    return _sha256(_sha256(data))


def _ripemd160(data):
    """RIPEMD160(data). Falls back gracefully if hashlib doesn't expose it
    (some Ubuntu builds disable it; Python 3.12 still has it on this box)."""
    h = hashlib.new('ripemd160')
    h.update(data)
    return h.digest()


def _checksum(codec, payload):
    """Per Blakestream-nomp util.ts getAddressChecksum:
       blake → first 4 bytes of single Blake-256(payload)
       sha256d → first 4 bytes of double SHA-256(payload)
    """
    if codec == 'blake':
        if _blake256 is None:
            raise RuntimeError('blake256 unavailable — eloipool tree not on path')
        return _blake256(payload)[:4]
    return _sha256d(payload)[:4]


# ---------------------------------------------------------------------------
# Address decoding
# ---------------------------------------------------------------------------

def _decode_address_parts(address):
    """Returns (payload, checksum) where checksum is the last 4 bytes."""
    if _b58decode is None:
        raise RuntimeError('base58 unavailable — vendored base58 not on path')
    # The vendored base58 module takes an optional fixed-length argument.
    # Passing None keeps compatibility with both the old NOMP-style helper and
    # the bundled implementation used in this tree.
    decoded = _b58decode(address, None)
    if decoded is None:
        raise ValueError(f'invalid base58 address: {address!r}')
    if len(decoded) < 25:
        raise ValueError(f'address payload too short: {len(decoded)} bytes')
    return decoded[:-4], decoded[-4:]


def _detect_checksum_codec(address):
    """Try sha256d first (more common), then blake (Blakecoin)."""
    payload, checksum = _decode_address_parts(address)
    if _checksum('sha256d', payload) == checksum:
        return 'sha256d'
    if _blake256 is not None and _checksum('blake', payload) == checksum:
        return 'blake'
    raise ValueError(f'unsupported or invalid address checksum for {address}')


def _get_version_byte(address):
    """The 'version byte' is everything in the payload that comes BEFORE the
    final 20-byte hash160. For most chains it's a single byte, but some
    coins use multi-byte prefixes — addressFromEx supports both shapes."""
    payload, _ = _decode_address_parts(address)
    if len(payload) <= 20:
        raise ValueError(f'invalid address payload length for {address}')
    return payload[:len(payload) - 20]


# ---------------------------------------------------------------------------
# Public API: address_from_ex + mining key derivation
# ---------------------------------------------------------------------------

def address_from_ex(ex_address, mining_key_hex):
    """Pure-Python port of Blakestream-nomp/src/stratum/util.ts:74.

    Args:
      ex_address: a legacy P2PKH address that serves as the operator's
        "namespace prefix". Must be base58check (T..., B..., 1...). bech32
        addresses are NOT supported because they have no version-byte prefix
        in the base58 sense.
      mining_key_hex: 40-char hex string = the miner's RIPEMD160(SHA256(pub)).

    Returns:
      A base58check address on the same chain as ex_address, with the same
      version-byte prefix and checksum codec, but with mining_key_hex spliced
      in where ex_address's hash160 would be. Spendable only by whoever holds
      the secp256k1 private key whose pubkey hashes to mining_key_hex.

      Returns None if anything goes wrong, matching the TS reference's
      ``try { ... } catch { return null }`` shape.
    """
    try:
        if not mining_key_hex or len(mining_key_hex) != 40:
            return None
        mining_key_bytes = bytes.fromhex(mining_key_hex)
        prefix = _get_version_byte(ex_address)
        codec  = _detect_checksum_codec(ex_address)
        addr_base = prefix + mining_key_bytes
        cksum  = _checksum(codec, addr_base)
        full   = addr_base + cksum
        return _b58encode(full)
    except Exception:
        return None


def mining_key_from_uncompressed_pubkey(pubkey_hex):
    """Compute the mining key from a 65-byte (130-char hex) uncompressed
    secp256k1 public key. Matches Blakestream-nomp's bsp/crypto.ts:171:
       miningKey = ripemd160(sha256(uncompressed_pubkey)).toString('hex')

    Note: NOMP intentionally hashes the UNCOMPRESSED 65-byte form, not the
    standard Bitcoin compressed 33-byte form. Anyone porting this MUST use
    the uncompressed form or the mining keys won't match what the miner-side
    nomp-pubkey-generator tool produces.
    """
    pub = bytes.fromhex(pubkey_hex)
    if len(pub) != 65 or pub[0] != 0x04:
        raise ValueError(
            f'expected 65-byte uncompressed pubkey starting with 0x04, '
            f'got {len(pub)} bytes starting with 0x{pub[0]:02x}'
        )
    return _ripemd160(_sha256(pub)).hex()


def mining_key_v2_from_compressed_pubkey(pubkey_hex):
    """Compute the v2 mining key from a 33-byte compressed secp256k1 pubkey.

    v2 intentionally diverges from v1: it hashes the COMPRESSED pubkey form
    so the resulting mining key can map directly to a witness-v0 P2WPKH
    program. The same private key will therefore produce a different v1 and
    v2 mining key, by design.
    """
    pub = bytes.fromhex(pubkey_hex)
    if len(pub) != 33 or pub[0] not in (0x02, 0x03):
        raise ValueError(
            f'expected 33-byte compressed pubkey starting with 0x02/0x03, '
            f'got {len(pub)} bytes starting with 0x{pub[0]:02x}'
        )
    return _ripemd160(_sha256(pub)).hex()


def address_from_v2_mining_key(mining_key_hex, hrp, witver=0):
    """Encode a v2 mining key as a native bech32 witness address.

    Unlike v1, v2 does not preserve any Ex-address namespace. The witness
    program is simply the 20-byte HASH160 encoded under the configured chain
    HRP (for example ``blc`` on mainnet, ``dblk`` on devnet).
    """
    try:
        if _segwit_addr is None:
            raise RuntimeError('segwit_addr unavailable — eloipool tree not on path')
        if not mining_key_hex or len(mining_key_hex) != 40:
            return None
        if not hrp:
            return None
        program = bytes.fromhex(mining_key_hex)
        if len(program) != 20:
            return None
        return _segwit_addr.encode(hrp, witver, program)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Stratum username classification
# ---------------------------------------------------------------------------

HEX40 = set('0123456789abcdefABCDEF')


def is_mining_key(s):
    """Return True if s is a mining key in the only accepted shape:
    - bare 40-hex (default and only v2/bech32 contract)

    Note: this is shape-only — it does NOT verify that the bytes correspond
    to a real on-chain pubkey hash. address_from_ex will accept any 40-char
    hex string and emit a derived address; whether the miner can actually
    spend it depends on whether they hold the matching secp256k1 private key.
    """
    if not s:
        return False
    if len(s) != 40:
        return False
    return all(c in HEX40 for c in s)


def resolve_payout_address(stratum_username, legacy_ex_address, segwit_hrp=None):
    """Implement the doc-prescribed username handling order from
    MINING-KEY.md "Required Next Step":

       1. strip optional .workername
       2. if the head is a direct Blakecoin address, use it
       3. else if the head is a supported mining key form, derive through
          the configured v2 path
       4. else skip it

    Args:
      stratum_username: the raw `mining.authorize` username string.
      legacy_ex_address: ignored in the post-SegWit release line.
        The parameter remains only for call-site compatibility with older
        bundle scripts and tests.
      segwit_hrp: chain HRP for native witness payouts (e.g. ``blc`` or
        ``dblk``). If unset, bare mining-key usernames are recognized but
        treated as unpayable.

    Returns:
      ``{'address': str, 'kind': 'direct' | 'derived_v2' | 'mining_key_v2',
         'worker': str|None, 'mining_key': str|None}``
      OR None if the username can't be resolved to a payout target.

      'kind':
        - 'direct'  - the username's head was already a Blakecoin address;
                      that address is used as-is
        - 'derived_v2' - the username's head was a bare mining key;
                      address_from_v2_mining_key was called to produce the payout
        - 'mining_key_v2' - the username's head was a bare mining key but
                      no segwit HRP was configured.
    """
    if not stratum_username:
        return None
    head, sep, tail = stratum_username.partition('.')
    worker = tail if sep else None

    # 1. direct Blakecoin address
    addr_type = _classify_addr_string_shape(head)
    if addr_type != 'none':
        return {
            'address':    head,
            'kind':       'direct',
            'addr_type':  addr_type,
            'worker':     worker,
            'mining_key': None,
        }

    # 2. mining key
    if is_mining_key(head):
        bare_key = head.lower()
        if not segwit_hrp:
            return {
                'address':    None,
                'kind':       'mining_key_v2',
                'addr_type':  'none',
                'worker':     worker,
                'mining_key': bare_key,
            }
        derived = address_from_v2_mining_key(bare_key, segwit_hrp)
        if derived is None:
            return None
        return {
            'address':    derived,
            'kind':       'derived_v2',
            'addr_type':  'bech32',
            'worker':     worker,
            'mining_key': bare_key,
        }

    # 3. anything else: skip
    return None


def _classify_addr_string_shape(addr):
    """Internal: classify a bare address string by shape only.
    Returns 'bech32' / 'legacy' / 'p2sh' / 'none'. Mirrors the dashboard's
    classify_address but lives here so coinbaser doesn't have to import
    from the dashboard."""
    if not addr:
        return 'none'
    lower = addr.lower()
    upper = addr.upper()
    if (addr == lower or addr == upper) and '1' in addr:
        hrp, _sep, rest = lower.partition('1')
        bech32_charset = set('qpzry9x8gf2tvdw0s3jn54khce6mua7l')
        if hrp and rest and all(ch in bech32_charset for ch in rest):
            return 'bech32'
    if _detect_checksum_codec_safe(addr) is None:
        return 'none'
    if addr.startswith(('3', 'q')):
        return 'p2sh'
    return 'legacy'


def _detect_checksum_codec_safe(address):
    """Like _detect_checksum_codec but returns None on failure instead of
    raising. Used by resolve_payout_address to label the resolved address."""
    try:
        return _detect_checksum_codec(address)
    except Exception:
        return None
