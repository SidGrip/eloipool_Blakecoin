"""Regression test for the canonical mining-key module — a pure-Python port
of Blakestream-nomp's addressFromEx() (src/stratum/util.ts:74) and the
upstream pubkey → mining key pipeline (src/bsp/crypto.ts:171).

If this test ever drifts from byte-for-byte equality with NOMP, the eloipool
pool will start producing payout addresses that nomp-pubkey-generator users
do not recognize and cannot spend from. That breaks the cross-pool symmetry
the mining-key system was designed for. Run on every change to mining_key.py.

    cd eloipool-devnet
    PYTHONPATH=. python3 -m unittest tests.test_address_from_ex
"""

import sys
import unittest
from pathlib import Path

# The canonical mining_key module lives at the top of eloipool-devnet/.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from mining_key import (
    address_from_ex,
    address_from_v2_mining_key,
    mining_key_from_uncompressed_pubkey,
    mining_key_v2_from_compressed_pubkey,
    is_mining_key,
    resolve_payout_address,
    _detect_checksum_codec,
    _decode_address_parts,
    _get_version_byte,
    _ripemd160,
    _sha256,
)


class TestChecksumCodecDetect(unittest.TestCase):
    def test_blakecoin_devnet_legacy_is_blake(self):
        # devnet P2PKH version 65 (0x41), checksum is single Blake-256
        self.assertEqual(
            _detect_checksum_codec('TWXKRsGwztxnpdSPRwHp3F7NQkMEzd3Esg'),
            'blake',
        )


class TestVersionByteExtraction(unittest.TestCase):
    def test_devnet_p2pkh_prefix_is_one_byte_0x41(self):
        prefix = _get_version_byte('TWXKRsGwztxnpdSPRwHp3F7NQkMEzd3Esg')
        self.assertEqual(prefix, bytes([65]))   # 65 = 0x41 = devnet P2PKH version


class TestAddressFromEx(unittest.TestCase):
    EX_DEVNET = 'TWXKRsGwztxnpdSPRwHp3F7NQkMEzd3Esg'

    def test_zero_mining_key_round_trip(self):
        derived = address_from_ex(self.EX_DEVNET, '00' * 20)
        self.assertIsNotNone(derived)
        self.assertTrue(derived.startswith('T'))
        # Decode and verify the embedded hash160 = the input mining key
        payload, _ = _decode_address_parts(derived)
        self.assertEqual(payload[1:], b'\x00' * 20)

    def test_known_pubkey_pipeline(self):
        # Pinned pipeline: priv → uncompressed pub → SHA256 → RIPEMD160 →
        # mining key → address_from_ex against the devnet Ex address.
        # If any step drifts, this asserts loudly.
        priv_hex = '51ee9d8741ba317b42e886fa07ddea012894c5cc3cc428f464818eed54eb2d35'
        uncompressed_pub_hex = (
            '04'
            '14e2baa21ed4161a208b2b02365770d815a1273881ba4f7036640d9cc2da1714'
            '4b5edf24485c8d526c62dba6e0b9cb53425948b8b6df7e1be1d1e2ce847bcf36'
        )
        expected_mining_key = '94d1da94895aa8f26ea1bdda0627927535cef463'
        expected_derived    = 'TPY6QMEAzdrRLv462Ke5VXLnLBx7ba5eei'

        mk = mining_key_from_uncompressed_pubkey(uncompressed_pub_hex)
        self.assertEqual(mk, expected_mining_key)

        derived = address_from_ex(self.EX_DEVNET, mk)
        self.assertEqual(derived, expected_derived)

    def test_different_mining_key_yields_different_address(self):
        a = address_from_ex(self.EX_DEVNET, '00' * 20)
        b = address_from_ex(self.EX_DEVNET, '94d1da94895aa8f26ea1bdda0627927535cef463')
        self.assertNotEqual(a, b)
        self.assertTrue(a.startswith('T'))
        self.assertTrue(b.startswith('T'))


class TestInvalidInput(unittest.TestCase):
    EX_DEVNET = 'TWXKRsGwztxnpdSPRwHp3F7NQkMEzd3Esg'

    def test_short_mining_key_returns_none(self):
        self.assertIsNone(address_from_ex(self.EX_DEVNET, 'abc'))

    def test_non_hex_mining_key_returns_none(self):
        self.assertIsNone(address_from_ex(self.EX_DEVNET, 'zz' * 20))

    def test_bech32_ex_address_returns_none(self):
        # bech32 has no version-byte prefix in the base58 sense — addressFromEx
        # cannot use it. Confirm we return None instead of crashing.
        self.assertIsNone(address_from_ex(
            'dblk1qc4wmdhwmurc9rw4nxml6ufn53ndgk09puxmlc6',
            '00' * 20,
        ))


class TestMiningKeyFromPubkey(unittest.TestCase):
    def test_rejects_compressed_pubkey(self):
        # 33-byte compressed pub starting with 0x02 — must be rejected because
        # NOMP hashes the UNCOMPRESSED form, not the compressed form. If a
        # caller accidentally passes a compressed pubkey, the resulting mining
        # key would be inconsistent with what nomp-pubkey-generator produces
        # for the same private key. The function must reject it loudly.
        compressed_hex = '02' + '14e2baa21ed4161a208b2b02365770d815a1273881ba4f7036640d9cc2da1714'
        with self.assertRaises(ValueError):
            mining_key_from_uncompressed_pubkey(compressed_hex)

    def test_rejects_wrong_length(self):
        with self.assertRaises(ValueError):
            mining_key_from_uncompressed_pubkey('04' + '00' * 10)

    def test_pipeline_byte_exact(self):
        # Same pinned values as TestAddressFromEx.test_known_pubkey_pipeline,
        # but isolated so a single failure here pinpoints which step drifted.
        uncompressed = (
            '04'
            '14e2baa21ed4161a208b2b02365770d815a1273881ba4f7036640d9cc2da1714'
            '4b5edf24485c8d526c62dba6e0b9cb53425948b8b6df7e1be1d1e2ce847bcf36'
        )
        sha = _sha256(bytes.fromhex(uncompressed))
        ripemd = _ripemd160(sha)
        self.assertEqual(ripemd.hex(), '94d1da94895aa8f26ea1bdda0627927535cef463')

    def test_v2_compressed_pipeline_byte_exact(self):
        compressed = '0214e2baa21ed4161a208b2b02365770d815a1273881ba4f7036640d9cc2da1714'
        self.assertEqual(
            mining_key_v2_from_compressed_pubkey(compressed),
            '8a1251277ceccaef3268d1a75ec7018bcf2fcf1c',
        )

    def test_v2_rejects_uncompressed_pubkey(self):
        uncompressed = (
            '04'
            '14e2baa21ed4161a208b2b02365770d815a1273881ba4f7036640d9cc2da1714'
            '4b5edf24485c8d526c62dba6e0b9cb53425948b8b6df7e1be1d1e2ce847bcf36'
        )
        with self.assertRaises(ValueError):
            mining_key_v2_from_compressed_pubkey(uncompressed)


class TestAddressFromV2(unittest.TestCase):
    KEY_V2 = '8a1251277ceccaef3268d1a75ec7018bcf2fcf1c'

    def test_known_bech32_vector(self):
        self.assertEqual(
            address_from_v2_mining_key(self.KEY_V2, 'dblk'),
            'dblk1q3gf9zfmuan9w7vng6xn4a3cp308jlncuagdnls',
        )

    def test_missing_hrp_returns_none(self):
        self.assertIsNone(address_from_v2_mining_key(self.KEY_V2, ''))


class TestIsMiningKey(unittest.TestCase):
    """is_mining_key is shape-only and must be permissive about hex case."""

    def test_lowercase_hex_40chars(self):
        self.assertTrue(is_mining_key('00' * 20))
        self.assertTrue(is_mining_key('94d1da94895aa8f26ea1bdda0627927535cef463'))

    def test_uppercase_hex_40chars(self):
        self.assertTrue(is_mining_key('94D1DA94895AA8F26EA1BDDA0627927535CEF463'))

    def test_too_short(self):
        self.assertFalse(is_mining_key('abc'))
        self.assertFalse(is_mining_key('00' * 19))   # 38 chars

    def test_too_long(self):
        self.assertFalse(is_mining_key('00' * 21))   # 42 chars

    def test_non_hex(self):
        self.assertFalse(is_mining_key('z' * 40))
        self.assertFalse(is_mining_key('g' * 40))

    def test_blakecoin_address_is_not_mining_key_shape(self):
        # A Blakecoin devnet legacy address is 34 chars, so it can't pass
        # the 40-char shape check even though it's also hex-ish.
        self.assertFalse(is_mining_key('TWXKRsGwztxnpdSPRwHp3F7NQkMEzd3Esg'))

    def test_prefixed_forms_are_rejected(self):
        self.assertFalse(is_mining_key('mk1:94d1da94895aa8f26ea1bdda0627927535cef463'))
        self.assertFalse(is_mining_key('MK1:94d1da94895aa8f26ea1bdda0627927535cef463'))
        self.assertFalse(is_mining_key('mk2:8a1251277ceccaef3268d1a75ec7018bcf2fcf1c'))
        self.assertFalse(is_mining_key('MK2:8A1251277CECCAEF3268D1A75EC7018BCF2FCF1C'))


class TestResolvePayoutAddress(unittest.TestCase):
    """The doc-prescribed 4-step username handling order from MINING-KEY.md
    'Required Next Step':

       1. strip optional .workername
       2. if the head is a direct Blakecoin address, use it
       3. else if the head is exactly 40 hex chars, derive through
          address_from_v2_mining_key(mining_key, hrp)
       4. else skip it
    """
    EX = 'TWXKRsGwztxnpdSPRwHp3F7NQkMEzd3Esg'
    KEY_V2 = '8a1251277ceccaef3268d1a75ec7018bcf2fcf1c'

    def test_direct_bech32_with_worker(self):
        r = resolve_payout_address('dblk1q9ksvg8tzm4xd6cyjulqnrzkrny0k974gs8xpv4.alice', self.EX)
        self.assertIsNotNone(r)
        self.assertEqual(r['kind'], 'direct')
        self.assertEqual(r['address'], 'dblk1q9ksvg8tzm4xd6cyjulqnrzkrny0k974gs8xpv4')
        self.assertEqual(r['addr_type'], 'bech32')
        self.assertEqual(r['worker'], 'alice')
        self.assertIsNone(r['mining_key'])

    def test_direct_uppercase_bech32_with_worker(self):
        r = resolve_payout_address('DBLK1Q9KSVG8TZM4XD6CYJULQNRZKRNY0K974GS8XPV4.alice', self.EX)
        self.assertIsNotNone(r)
        self.assertEqual(r['kind'], 'direct')
        self.assertEqual(r['address'], 'DBLK1Q9KSVG8TZM4XD6CYJULQNRZKRNY0K974GS8XPV4')
        self.assertEqual(r['addr_type'], 'bech32')
        self.assertEqual(r['worker'], 'alice')

    def test_direct_legacy_no_worker(self):
        r = resolve_payout_address('TWXKRsGwztxnpdSPRwHp3F7NQkMEzd3Esg', self.EX)
        self.assertEqual(r['kind'], 'direct')
        self.assertEqual(r['addr_type'], 'legacy')
        self.assertIsNone(r['worker'])

    def test_direct_p2sh(self):
        r = resolve_payout_address('qda1h4bGcuyV5ZcXZms84FDXGnFMDLb45U.gpu1', self.EX)
        self.assertEqual(r['kind'], 'direct')
        self.assertEqual(r['addr_type'], 'p2sh')
        self.assertEqual(r['worker'], 'gpu1')

    def test_mining_key_with_worker_derives_v2(self):
        r = resolve_payout_address(f'{self.KEY_V2}.rig1', self.EX, 'dblk')
        self.assertEqual(r['kind'], 'derived_v2')
        self.assertEqual(r['address'], 'dblk1q3gf9zfmuan9w7vng6xn4a3cp308jlncuagdnls')
        self.assertEqual(r['addr_type'], 'bech32')
        self.assertEqual(r['mining_key'], self.KEY_V2)
        self.assertEqual(r['worker'], 'rig1')

    def test_mining_key_no_worker_derives_v2(self):
        r = resolve_payout_address(self.KEY_V2, self.EX, 'dblk')
        self.assertEqual(r['kind'], 'derived_v2')
        self.assertEqual(r['address'], 'dblk1q3gf9zfmuan9w7vng6xn4a3cp308jlncuagdnls')
        self.assertEqual(r['addr_type'], 'bech32')
        self.assertIsNone(r['worker'])

    def test_mining_key_uppercase_normalized(self):
        # Mining key sent in uppercase should still work and derive the same
        # address as the lowercase form.
        upper = self.KEY_V2.upper()
        r = resolve_payout_address(upper, self.EX, 'dblk')
        self.assertEqual(r['kind'], 'derived_v2')
        self.assertEqual(r['mining_key'], self.KEY_V2)   # normalized to lowercase
        self.assertEqual(r['address'], 'dblk1q3gf9zfmuan9w7vng6xn4a3cp308jlncuagdnls')

    def test_plain_label_returns_none(self):
        # 'alice.rig1' has no recognised address head and isn't a mining key
        # → step 4: skip
        self.assertIsNone(resolve_payout_address('alice.rig1', self.EX))

    def test_mining_key_without_hrp_returns_kind_only(self):
        r = resolve_payout_address(f'{self.KEY_V2}.rig1', None, None)
        self.assertEqual(r['kind'], 'mining_key_v2')
        self.assertIsNone(r['address'])
        self.assertEqual(r['mining_key'], self.KEY_V2)
        self.assertEqual(r['worker'], 'rig1')

    def test_legacy_ex_address_is_ignored_for_v2(self):
        bad_ex = 'dblk1qc4wmdhwmurc9rw4nxml6ufn53ndgk09puxmlc6'
        r = resolve_payout_address(f'{self.KEY_V2}.rig1', bad_ex, 'dblk')
        self.assertEqual(r['kind'], 'derived_v2')
        self.assertEqual(r['address'], 'dblk1q3gf9zfmuan9w7vng6xn4a3cp308jlncuagdnls')

    def test_empty_username_returns_none(self):
        self.assertIsNone(resolve_payout_address('', self.EX))
        self.assertIsNone(resolve_payout_address(None, self.EX))

    def test_mk1_prefix_is_rejected(self):
        self.assertIsNone(resolve_payout_address(f'mk1:{self.KEY_V2}.alice', self.EX, 'dblk'))

    def test_mk2_prefix_is_rejected(self):
        self.assertIsNone(resolve_payout_address(f'mk2:{self.KEY_V2}.alice', self.EX, 'dblk'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
