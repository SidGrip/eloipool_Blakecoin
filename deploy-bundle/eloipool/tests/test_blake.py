"""Hash regression test for eloipool-devnet.

Pins known Blakecoin devnet block headers and asserts that ``blake8.BLAKE(256)``
produces the same hash the daemon stores. This is the single most important
correctness test in the pool: if it fails, accepted shares would correspond to
blocks the daemon will reject.

Run from the eloipool-devnet root:

    PYTHONPATH=. python3 tests/test_blake.py
"""

import struct
import sys
import unittest
from pathlib import Path

# Allow ``python3 tests/test_blake.py`` from inside the tests dir.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from blake8 import BLAKE


def hash_header(version, prev_be_hex, merkle_be_hex, ts, bits, nonce):
    """Build the canonical 80-byte header and return its Blake-256 hash, big-endian hex."""
    hdr = (
        struct.pack('<L', version)
        + bytes.fromhex(prev_be_hex)[::-1]
        + bytes.fromhex(merkle_be_hex)[::-1]
        + struct.pack('<L', ts)
        + struct.pack('<L', bits)
        + struct.pack('<L', nonce)
    )
    assert len(hdr) == 80, len(hdr)
    return BLAKE(256).digest(hdr)[::-1].hex()


class BlakecoinDevnetHashFixtures(unittest.TestCase):
    """Each fixture is a known devnet block: serialize the header, hash it,
    compare to the daemon-reported block hash."""

    def test_devnet_genesis(self):
        # CDevNetParams in src/chainparams.cpp keeps a distinct devnet genesis
        # while moving the chain onto a production-like retarget baseline.
        got = hash_header(
            version=1,
            prev_be_hex='00' * 32,
            merkle_be_hex='9e4654d5bb91c723c3dbbaee57761d06ed10ac17f4d8841746aeec7ff8206ddc',
            ts=1775683200,
            bits=0x1f00ffff,
            nonce=50151,
        )
        self.assertEqual(got, '0000c95fc36d84f2cf35a5a5c5666216c782724137c48cf6e3141bba2e089d76')


if __name__ == '__main__':
    unittest.main(verbosity=2)
