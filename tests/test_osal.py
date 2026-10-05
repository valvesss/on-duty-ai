import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@unittest.skipUnless(sys.platform == "darwin", "the macOS implementation of osal")
class MacOsal(unittest.TestCase):
    def test_contract(self):
        import osal
        self.assertGreaterEqual(osal.idle_seconds(), 0.0)
        self.assertIsInstance(osal.system_asleep(), bool)
        self.assertGreaterEqual(osal.display_count(), 1)
        self.assertIsInstance(osal.mic_in_use(), bool)
        self.assertIsInstance(osal.login_item_enabled(), bool)
        voices = osal.list_voices()
        self.assertTrue(all({"name", "locale"} <= v.keys() for v in voices))


class Contract(unittest.TestCase):
    """What every platform module must export (see CONTRIBUTING.md)."""

    NAMES = ("idle_seconds", "system_asleep", "display_count", "mic_in_use", "list_voices", "speak", "notify", "play_alert",
             "login_item_enabled", "set_login_item")

    @unittest.skipUnless(sys.platform == "darwin", "needs a platform module")
    def test_all_functions_exported(self):
        import osal
        for n in self.NAMES:
            self.assertTrue(callable(getattr(osal, n, None)), n)


if __name__ == "__main__":
    unittest.main()
