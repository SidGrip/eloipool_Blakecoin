import importlib.util
import os
import unittest
from pathlib import Path


def find_coinbaser_path() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / 'deploy-bundle' / 'coinbaser.py'
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f'could not locate coinbaser.py from {here}')


COINBASER_PATH = find_coinbaser_path()


def load_coinbaser_module(segwit_hrp='dblk'):
    old_hrp = os.environ.get('COINBASER_MINING_KEY_SEGWIT_HRP')
    try:
        if segwit_hrp:
            os.environ['COINBASER_MINING_KEY_SEGWIT_HRP'] = segwit_hrp
        else:
            os.environ.pop('COINBASER_MINING_KEY_SEGWIT_HRP', None)
        spec = importlib.util.spec_from_file_location('coinbaser_test_module', COINBASER_PATH)
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        return mod
    finally:
        if old_hrp is None:
            os.environ.pop('COINBASER_MINING_KEY_SEGWIT_HRP', None)
        else:
            os.environ['COINBASER_MINING_KEY_SEGWIT_HRP'] = old_hrp


class TestCoinbaserWeightedAccounting(unittest.TestCase):
    LEGACY = 'TRNcQYeREye1iyksJKtdnqaCFcPQCdddK8'
    BECH32 = 'dblk1qvaaugfwjdnl5lzwkzwrmxwkw6zsy9ey8r6mywz'
    P2SH = 'qaRUdTuAAWaxi1m3byLfHZ8LG2xwVYp29z'
    MINING_KEY = '8a1251277ceccaef3268d1a75ec7018bcf2fcf1c'

    def test_parse_share_line_supports_extended_weighted_format(self):
        cb = load_coinbaser_module()
        line = (
            f"1775675377.3503573 76.150.194.102 {self.LEGACY}.rig1 "
            "N Y high-hash 1535.976562 000000000006aaa0000000000000000000000000000000000000000000000000 deadbeef"
        )
        parsed = cb.parse_share_line(line)
        self.assertIsNotNone(parsed)
        self.assertFalse(parsed['our_result'])
        self.assertTrue(parsed['upstream_result'])
        self.assertTrue(parsed['contribution'])
        self.assertEqual(str(parsed['share_diff']), '1535.976562')
        self.assertEqual(str(parsed['weight']), '1535.976562')

    def test_compute_splits_ignores_non_contributing_rejects(self):
        cb = load_coinbaser_module()
        total = 1_000_000_000
        lines = [
            f"1 host {self.LEGACY}.rig1 Y - - 1 0001 aa",
            f"2 host {self.BECH32}.rig1 N - high-hash 1024 0002 bb",
            f"3 host {self.P2SH}.rig1 Y - - 1 0003 cc",
        ]
        splits, debug = cb.compute_splits(total, lines)
        amounts = {addr: sat for sat, addr in splits}
        self.assertIn(self.LEGACY, amounts)
        self.assertIn(self.P2SH, amounts)
        self.assertNotIn(self.BECH32, amounts)
        self.assertEqual(debug['counted_lines'], 2)

    def test_compute_splits_weights_by_share_difficulty(self):
        cb = load_coinbaser_module()
        total = 1_000_000_000
        lines = [
            f"1 host {self.LEGACY}.rig1 Y - - 1 0001 aa",
            f"2 host {self.BECH32}.rig1 Y - - 3 0002 bb",
        ]
        splits, debug = cb.compute_splits(total, lines)
        amounts = {addr: sat for sat, addr in splits}
        legacy = amounts[self.LEGACY]
        bech32 = amounts[self.BECH32]
        self.assertGreater(bech32, legacy)
        self.assertAlmostEqual(bech32 / legacy, 3.0, delta=0.02)
        self.assertEqual(debug['total_work'], '4')

    def test_upstream_accepted_block_solve_counts_even_if_local_result_is_n(self):
        cb = load_coinbaser_module()
        total = 1_000_000_000
        lines = [
            f"1 host {self.LEGACY}.rig1 N Y high-hash 8 0001 aa",
            f"2 host {self.BECH32}.rig1 Y - - 1 0002 bb",
        ]
        splits, _ = cb.compute_splits(total, lines)
        amounts = {addr: sat for sat, addr in splits}
        self.assertGreater(amounts[self.LEGACY], amounts[self.BECH32])

    def test_old_share_log_format_remains_supported(self):
        cb = load_coinbaser_module()
        total = 1_000_000_000
        lines = [
            f"1 host {self.LEGACY}.rig1 Y - - deadbeef",
            f"2 host {self.BECH32}.rig1 Y - - cafebabe",
        ]
        splits, debug = cb.compute_splits(total, lines)
        amounts = sorted(sat for sat, _ in splits)
        self.assertEqual(len(amounts), 2)
        self.assertLessEqual(abs(amounts[0] - amounts[1]), 1)
        self.assertEqual(debug['counted_lines'], 2)

    def test_debug_splits_keep_mining_key_metadata_for_bare_mining_keys(self):
        cb = load_coinbaser_module()
        total = 1_000_000_000
        lines = [
            f"1 host {self.MINING_KEY}.rig1 Y - - 1 0001 aa",
        ]
        _, debug = cb.compute_splits(total, lines)
        self.assertEqual(len(debug['splits']), 1)
        split = debug['splits'][0]
        self.assertEqual(split['kind'], 'derived_v2')
        self.assertEqual(split['mining_key'], self.MINING_KEY)
        self.assertEqual(split['addr_type'], 'bech32')
