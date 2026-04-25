import importlib.util
from importlib.machinery import SourceFileLoader
import types
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROXY_PATH = ROOT / "merged-mine-proxy.py3"
MINING_KEY_PATH = ROOT / "mining_key.py"


def load_module(name, path):
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def install_twisted_stubs():
    if "twisted" in sys.modules:
        return

    twisted = types.ModuleType("twisted")
    internet = types.ModuleType("twisted.internet")
    defer = types.ModuleType("twisted.internet.defer")
    reactor = types.SimpleNamespace(callLater=lambda *a, **k: None)
    task = types.ModuleType("twisted.internet.task")
    threads = types.ModuleType("twisted.internet.threads")
    error_mod = types.ModuleType("twisted.internet.error")
    web = types.ModuleType("twisted.web")
    server = types.ModuleType("twisted.web.server")
    resource = types.ModuleType("twisted.web.resource")

    def inline_callbacks(func):
        return func

    def return_value(value):
        return value

    class DummyResource:
        def __init__(self, *args, **kwargs):
            pass

        def putChild(self, *args, **kwargs):
            return None

    defer.inlineCallbacks = inline_callbacks
    defer.returnValue = return_value
    task.deferLater = lambda *a, **k: None
    error_mod.ConnectionRefusedError = ConnectionRefusedError
    server.NOT_DONE_YET = object()
    resource.Resource = DummyResource

    twisted.internet = internet
    twisted.web = web
    internet.defer = defer
    internet.reactor = reactor
    internet.task = task
    internet.threads = threads
    internet.error = error_mod
    web.server = server
    web.resource = resource

    sys.modules["twisted"] = twisted
    sys.modules["twisted.internet"] = internet
    sys.modules["twisted.internet.defer"] = defer
    sys.modules["twisted.internet.reactor"] = reactor
    sys.modules["twisted.internet.task"] = task
    sys.modules["twisted.internet.threads"] = threads
    sys.modules["twisted.internet.error"] = error_mod
    sys.modules["twisted.web"] = web
    sys.modules["twisted.web.server"] = server
    sys.modules["twisted.web.resource"] = resource


mk = load_module("blakestream_test_mining_key", MINING_KEY_PATH)


class TestAuxPowPerSolver(unittest.TestCase):
    KEY = "a5d3e00343efe51e81d39884a74124ca060fefdd"
    proxy = None

    @classmethod
    def setUpClass(cls):
        install_twisted_stubs()
        try:
            cls.proxy = load_module("blakestream_test_proxy", PROXY_PATH)
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest(f"proxy runtime dependency missing locally: {exc}") from exc

    def make_listener(self, payout_addresses, per_solver_aux_payouts=False):
        listener = self.proxy.Listener.__new__(self.proxy.Listener)
        listener.auxs = [object(), object(), object()]
        listener.aux_payout_addresses = list(payout_addresses)
        listener.per_solver_aux_payouts = per_solver_aux_payouts
        return listener

    def test_default_pool_mode_keeps_session_level_addresses(self):
        payout_addresses = [
            "tbbtc1q5hf7qq6ralj3aqwnnzz2wsfyegrqlm7afa890n",
            "telt1q5hf7qq6ralj3aqwnnzz2wsfyegrqlm7aza9heu",
            "tlit1q5hf7qq6ralj3aqwnnzz2wsfyegrqlm7augmrw0",
        ]
        listener = self.make_listener(payout_addresses)
        payouts = listener._resolve_selector_payout_addresses({"username": f"{self.KEY}.rig1"})
        self.assertEqual(payouts, tuple(listener.aux_payout_addresses))

    def test_per_solver_mode_derives_child_addresses_for_bare_mining_key(self):
        payout_addresses = [
            "tbbtc1q5hf7qq6ralj3aqwnnzz2wsfyegrqlm7afa890n",
            "telt1q5hf7qq6ralj3aqwnnzz2wsfyegrqlm7aza9heu",
            "tlit1q5hf7qq6ralj3aqwnnzz2wsfyegrqlm7augmrw0",
        ]
        listener = self.make_listener(payout_addresses, per_solver_aux_payouts=True)
        payouts = listener._resolve_selector_payout_addresses({"username": f"{self.KEY}.rig1"})
        expected = (
            mk.address_from_v2_mining_key(self.KEY, "tbbtc"),
            mk.address_from_v2_mining_key(self.KEY, "telt"),
            mk.address_from_v2_mining_key(self.KEY, "tlit"),
        )
        self.assertEqual(payouts, expected)

    def test_mk2_prefixed_username_is_rejected(self):
        payout_addresses = [
            "tbbtc1q5hf7qq6ralj3aqwnnzz2wsfyegrqlm7afa890n",
            "telt1q5hf7qq6ralj3aqwnnzz2wsfyegrqlm7aza9heu",
            "tlit1q5hf7qq6ralj3aqwnnzz2wsfyegrqlm7augmrw0",
        ]
        listener = self.make_listener(payout_addresses)
        payouts = listener._resolve_selector_payout_addresses({"username": f"mk2:{self.KEY}.rig1"})
        self.assertEqual(payouts, tuple(listener.aux_payout_addresses))

    def test_direct_address_username_keeps_session_level_addresses(self):
        listener = self.make_listener([
            "tbbtc1q5hf7qq6ralj3aqwnnzz2wsfyegrqlm7afa890n",
            "telt1q5hf7qq6ralj3aqwnnzz2wsfyegrqlm7aza9heu",
            "tlit1q5hf7qq6ralj3aqwnnzz2wsfyegrqlm7augmrw0",
        ])
        payouts = listener._resolve_selector_payout_addresses(
            {"username": "tblc1q5hf7qq6ralj3aqwnnzz2wsfyegrqlm7azmutfn.rig1"}
        )
        self.assertEqual(payouts, tuple(listener.aux_payout_addresses))

    def test_uppercase_direct_address_username_keeps_session_level_addresses(self):
        listener = self.make_listener([
            "tbbtc1q5hf7qq6ralj3aqwnnzz2wsfyegrqlm7afa890n",
            "telt1q5hf7qq6ralj3aqwnnzz2wsfyegrqlm7aza9heu",
            "tlit1q5hf7qq6ralj3aqwnnzz2wsfyegrqlm7augmrw0",
        ], per_solver_aux_payouts=True)
        payouts = listener._resolve_selector_payout_addresses(
            {"username": "TBLC1Q5HF7QQ6RALJ3AQWNNZZ2WSFYEGRQLM7AZMUTFN.rig1"}
        )
        self.assertEqual(payouts, tuple(listener.aux_payout_addresses))

    def test_block_hash_unknown_is_treated_as_stale_aux_submission(self):
        err = self.proxy.Error(-8, "block hash unknown", "")
        self.assertTrue(self.proxy.Listener._is_stale_aux_submission_error(err))

    def test_unrelated_rpc_error_is_not_treated_as_stale_aux_submission(self):
        err = self.proxy.Error(-1, "misc error", "")
        self.assertFalse(self.proxy.Listener._is_stale_aux_submission_error(err))


if __name__ == "__main__":
    unittest.main()
