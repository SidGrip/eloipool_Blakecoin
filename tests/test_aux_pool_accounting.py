import importlib.util
import os
import unittest
from decimal import Decimal
from pathlib import Path


def find_dashboard_path() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / 'deploy-bundle' / 'dashboard' / 'dashboard.py'
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f'could not locate dashboard.py from {here}')


DASH_PATH = find_dashboard_path()


def load_dashboard_module(segwit_hrp='dblk', v2_coin_hrps='{"BlakeBitcoin":"bbtc","Electron":"elt"}', extra_env=None):
    old_env = {}
    updates = {
        'DASH_MINING_KEY_SEGWIT_HRP': segwit_hrp,
        'DASH_MINING_KEY_V2_COIN_HRPS': v2_coin_hrps,
        'DASH_AUX_PAYOUT_MODE': 'pool',
    }
    if extra_env:
        updates.update(extra_env)
    try:
        for key, value in updates.items():
            old_env[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        spec = importlib.util.spec_from_file_location('dashboard_aux_pool_test_module', DASH_PATH)
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        return mod
    finally:
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class TestAuxPoolAccounting(unittest.TestCase):
    KEY_A = '8a1251277ceccaef3268d1a75ec7018bcf2fcf1c'
    KEY_B = '1a8ef9c714af41ba978af9c53965e7eb743cce5b'

    def test_child_rewards_are_shared_by_recorded_work_and_keep_pool_remainder(self):
        dash = load_dashboard_module()
        child_bbtc_a = dash.address_from_v2_mining_key(self.KEY_A, 'bbtc')
        child_bbtc_b = dash.address_from_v2_mining_key(self.KEY_B, 'bbtc')
        child_elt_a = dash.address_from_v2_mining_key(self.KEY_A, 'elt')
        child_elt_b = dash.address_from_v2_mining_key(self.KEY_B, 'elt')

        dash.incremental_coinbaser_debug_entries = lambda: [{
            'ts': 99.0,
            'prev': 'prevhash',
            'pool_keep_bps': 100,
            'total_work': Decimal('4'),
            'splits': [
                {'addr': dash.address_from_v2_mining_key(self.KEY_A, 'dblk'), 'work': Decimal('1'), 'kind': 'derived_v2', 'mining_key': self.KEY_A, 'addr_type': 'bech32'},
                {'addr': dash.address_from_v2_mining_key(self.KEY_B, 'dblk'), 'work': Decimal('3'), 'kind': 'derived_v2', 'mining_key': self.KEY_B, 'addr_type': 'bech32'},
            ],
        }]

        def fake_block_meta(label, block_hash):
            if label == 'Blakecoin':
                return {'prev_hash': 'prevhash', 'time': 100.0}
            if label == 'BlakeBitcoin':
                return {'reward': 50.0}
            if label == 'Electron':
                return {'reward': 25.0}
            return {}

        dash.get_chain_block_meta = fake_block_meta

        payouts, pool_keeps = dash.get_recent_child_accounted_payouts([
            {
                'hash': 'parenthash',
                'ts': 100.0,
                'parent_accepted': True,
                'accepted_details': [
                    {'label': 'BlakeBitcoin', 'hash': 'bbtc-block'},
                    {'label': 'Electron', 'hash': 'elt-block'},
                ],
            }
        ], max_blocks=None)

        self.assertEqual(payouts['BlakeBitcoin'][child_bbtc_a], 1_237_500_000)
        self.assertEqual(payouts['BlakeBitcoin'][child_bbtc_b], 3_712_500_000)
        self.assertEqual(pool_keeps['BlakeBitcoin'], 50_000_000)

        self.assertEqual(payouts['Electron'][child_elt_a], 618_750_000)
        self.assertEqual(payouts['Electron'][child_elt_b], 1_856_250_000)
        self.assertEqual(pool_keeps['Electron'], 25_000_000)

    def test_unsupported_child_recipient_stays_in_pool_keep(self):
        dash = load_dashboard_module()
        child_bbtc = dash.address_from_v2_mining_key(self.KEY_A, 'bbtc')

        dash.incremental_coinbaser_debug_entries = lambda: [{
            'ts': 99.0,
            'prev': 'prevhash',
            'pool_keep_bps': 100,
            'total_work': Decimal('2'),
            'splits': [
                {'addr': 'TRNcQYeREye1iyksJKtdnqaCFcPQCdddK8', 'work': Decimal('1'), 'kind': 'direct', 'mining_key': None, 'addr_type': 'legacy'},
                {'addr': dash.address_from_v2_mining_key(self.KEY_A, 'dblk'), 'work': Decimal('1'), 'kind': 'derived_v2', 'mining_key': self.KEY_A, 'addr_type': 'bech32'},
            ],
        }]
        dash.get_chain_block_meta = lambda label, block_hash: {'prev_hash': 'prevhash', 'time': 100.0} if label == 'Blakecoin' else {'reward': 50.0}

        payouts, pool_keeps = dash.get_recent_child_accounted_payouts([
            {
                'hash': 'parenthash',
                'ts': 100.0,
                'parent_accepted': True,
                'accepted_details': [{'label': 'BlakeBitcoin', 'hash': 'bbtc-block'}],
            }
        ], max_blocks=None)

        self.assertEqual(payouts['BlakeBitcoin'][child_bbtc], 2_475_000_000)
        self.assertEqual(pool_keeps['BlakeBitcoin'], 2_525_000_000)


if __name__ == '__main__':
    unittest.main()
