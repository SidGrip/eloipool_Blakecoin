import importlib.util
import os
import unittest
from pathlib import Path


def find_dashboard_path() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / 'deploy-bundle' / 'dashboard' / 'dashboard.py'
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f'could not locate dashboard.py from {here}')


DASH_PATH = find_dashboard_path()


def load_dashboard_module(segwit_hrp='', v2_coin_hrps=None):
    old_hrp = os.environ.get('DASH_MINING_KEY_SEGWIT_HRP')
    old_v2 = os.environ.get('DASH_MINING_KEY_V2_COIN_HRPS')
    try:
        if segwit_hrp is None:
            os.environ.pop('DASH_MINING_KEY_SEGWIT_HRP', None)
        else:
            os.environ['DASH_MINING_KEY_SEGWIT_HRP'] = segwit_hrp
        if v2_coin_hrps is None:
            os.environ.pop('DASH_MINING_KEY_V2_COIN_HRPS', None)
        else:
            os.environ['DASH_MINING_KEY_V2_COIN_HRPS'] = v2_coin_hrps
        spec = importlib.util.spec_from_file_location('dashboard_test_module', DASH_PATH)
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        return mod
    finally:
        if old_hrp is None:
            os.environ.pop('DASH_MINING_KEY_SEGWIT_HRP', None)
        else:
            os.environ['DASH_MINING_KEY_SEGWIT_HRP'] = old_hrp
        if old_v2 is None:
            os.environ.pop('DASH_MINING_KEY_V2_COIN_HRPS', None)
        else:
            os.environ['DASH_MINING_KEY_V2_COIN_HRPS'] = old_v2


class TestDashboardMiningKeys(unittest.TestCase):
    KEY_V2 = '8a1251277ceccaef3268d1a75ec7018bcf2fcf1c'
    DERIVED_V2 = 'dblk1q3gf9zfmuan9w7vng6xn4a3cp308jlncuagdnls'
    PUB_V2 = '0214e2baa21ed4161a208b2b02365770d815a1273881ba4f7036640d9cc2da1714'
    COIN_HRPS = '{"BlakeBitcoin":"bbtc","Electron":"elt"}'

    def test_parse_stratum_username_resolves_bare_v2_mining_key(self):
        dash = load_dashboard_module('dblk')
        parsed = dash.parse_stratum_username(self.KEY_V2)
        self.assertEqual(parsed['addr'], self.DERIVED_V2)
        self.assertEqual(parsed['addr_type'], 'bech32')
        self.assertEqual(parsed['kind'], 'derived_v2')
        self.assertEqual(parsed['mining_key'], self.KEY_V2)

    def test_parse_stratum_username_preserves_worker_suffix_for_v2(self):
        dash = load_dashboard_module('dblk')
        parsed = dash.parse_stratum_username(self.KEY_V2 + '.rig1')
        self.assertEqual(parsed['addr'], self.DERIVED_V2)
        self.assertEqual(parsed['worker'], 'rig1')
        self.assertEqual(parsed['kind'], 'derived_v2')

    def test_parse_stratum_username_without_hrp_returns_kind_only_for_v2(self):
        dash = load_dashboard_module('')
        parsed = dash.parse_stratum_username(self.KEY_V2)
        self.assertIsNone(parsed['addr'])
        self.assertEqual(parsed['addr_type'], 'none')
        self.assertEqual(parsed['kind'], 'mining_key_v2')

    def test_parse_stratum_username_rejects_prefixed_forms(self):
        dash = load_dashboard_module('dblk')
        self.assertEqual(dash.parse_stratum_username('mk1:' + self.KEY_V2)['kind'], 'skip')
        self.assertEqual(dash.parse_stratum_username('mk2:' + self.KEY_V2)['kind'], 'skip')

    def test_api_derive_address_v2(self):
        dash = load_dashboard_module('dblk')
        client = dash.app.test_client()
        rv = client.post('/api/derive-address-v2', json={'mining_key': self.KEY_V2, 'hrp': 'dblk'})
        self.assertEqual(rv.status_code, 200)
        body = rv.get_json()
        self.assertTrue(body['ok'])
        self.assertEqual(body['derived_address'], self.DERIVED_V2)

    def test_api_verify_mining_key_v2(self):
        dash = load_dashboard_module('dblk')
        client = dash.app.test_client()
        rv = client.post('/api/verify-mining-key', json={'version': 2, 'pubkey_hex': self.PUB_V2, 'hrp': 'dblk'})
        self.assertEqual(rv.status_code, 200)
        body = rv.get_json()
        self.assertTrue(body['ok'])
        self.assertEqual(body['mining_key'], self.KEY_V2)
        self.assertEqual(body['derived_address'], self.DERIVED_V2)

    def test_api_derive_addresses_v2_returns_full_bech32_set(self):
        dash = load_dashboard_module('dblk', self.COIN_HRPS)
        client = dash.app.test_client()
        rv = client.post('/api/derive-addresses-v2', json={'mining_key': self.KEY_V2, 'hrp': 'dblk'})
        self.assertEqual(rv.status_code, 200)
        body = rv.get_json()
        self.assertTrue(body['ok'])
        self.assertEqual(body['derived_address'], self.DERIVED_V2)
        self.assertIn('Blakecoin', body['derived_addresses'])
        self.assertIn('BlakeBitcoin', body['derived_addresses'])
        self.assertIn('Electron', body['derived_addresses'])
        self.assertEqual(body['derived_addresses']['BlakeBitcoin']['addr_type'], 'bech32')
        self.assertTrue(body['derived_addresses']['BlakeBitcoin']['address'].startswith('bbtc1'))
        self.assertTrue(body['derived_addresses']['Electron']['address'].startswith('elt1'))

    def test_identity_payout_targets_derives_v2_child_addresses(self):
        dash = load_dashboard_module('dblk', self.COIN_HRPS)
        identity = {
            'addr': self.DERIVED_V2,
            'kind': 'derived_v2',
            'mining_key': self.KEY_V2,
        }
        targets = dash.identity_payout_targets(identity)
        self.assertEqual(targets['Blakecoin'], self.DERIVED_V2)
        self.assertTrue(targets['BlakeBitcoin'].startswith('bbtc1'))
        self.assertTrue(targets['Electron'].startswith('elt1'))

    def test_index_shows_v2_only_generator_copy(self):
        dash = load_dashboard_module('')
        client = dash.app.test_client()
        rv = client.get('/')
        self.assertEqual(rv.status_code, 200)
        html = rv.get_data(as_text=True)
        self.assertIn('Generate Mining Key', html)
        self.assertNotIn('Generate V1 Mining Key', html)
        self.assertNotIn('Generate V2 Mining Key', html)
        self.assertNotIn('mk2:&lt;40hex&gt;', html)

    def test_old_v1_route_is_absent(self):
        dash = load_dashboard_module('dblk')
        client = dash.app.test_client()
        rv = client.post('/api/derive-addresses-v1', json={'mining_key': self.KEY_V2})
        self.assertEqual(rv.status_code, 404)

    def test_parse_share_log_promotes_upstream_high_hash_to_block(self):
        dash = load_dashboard_module('dblk')
        rows = dash.parse_share_log([
            f"1.0 1.2.3.4 {self.KEY_V2}.rig1 N Y high-hash 1535.976562 deadbeef cafebabe"
        ])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['status'], 'BLOCK ✓')
        self.assertTrue(rows[0]['accepted'])
        self.assertAlmostEqual(rows[0]['share_diff'], 1535.976562)
        self.assertAlmostEqual(rows[0]['weight'], 1535.976562)

    def test_parse_identity_stats_tracks_submissions_and_weighted_work(self):
        dash = load_dashboard_module('dblk')
        stats = dash.parse_identity_stats([
            f"1.0 1.2.3.4 {self.KEY_V2}.rig1 Y - - 4 deadbeef cafebabe",
            f"2.0 1.2.3.4 {self.KEY_V2}.rig1 N - high-hash 8 deadbeef cafebabe",
            f"3.0 1.2.3.4 {self.KEY_V2}.rig1 N Y high-hash 2 deadbeef cafebabe",
        ])
        row = stats[('1.2.3.4', self.KEY_V2 + '.rig1')]
        self.assertEqual(row['shares'], 3)
        self.assertEqual(row['accepted_shares'], 2)
        self.assertEqual(row['blocks'], 1)
        self.assertAlmostEqual(row['weighted_work'], 6.0)

    def test_aggregate_identity_payout_totals_sums_all_chains(self):
        dash = load_dashboard_module('dblk')
        totals = dash.aggregate_identity_payout_totals([
            {'all_paid_satoshis': {'Blakecoin': 150, 'BlakeBitcoin': 75}},
            {'all_paid_satoshis': {'Blakecoin': 25, 'Photon': 1000}},
        ], ['Blakecoin', 'BlakeBitcoin', 'Photon'])
        self.assertEqual(totals, {
            'Blakecoin': 175,
            'BlakeBitcoin': 75,
            'Photon': 1000,
        })

    def test_pool_wallet_paid_totals_combines_tracker_and_aux(self):
        dash = load_dashboard_module('dblk')
        totals = dash.pool_wallet_paid_totals(
            2500,
            {'BlakeBitcoin': 500, 'Photon': 125},
            ['Blakecoin', 'BlakeBitcoin', 'Photon'],
        )
        self.assertEqual(totals, {
            'Blakecoin': 2500,
            'BlakeBitcoin': 500,
            'Photon': 125,
        })

    def test_wallet_balances_from_info_normalizes_wallet_fields(self):
        dash = load_dashboard_module('dblk')
        balances = dash.wallet_balances_from_info({
            'balance': 12.5,
            'immature_balance': 1.25,
            'unconfirmed_balance': 0.5,
        })
        self.assertEqual(balances, {
            'confirmed_satoshis': 1250000000,
            'immature_satoshis': 125000000,
            'unconfirmed_satoshis': 50000000,
            'total_satoshis': 1425000000,
        })
