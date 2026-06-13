import unittest

from koc.scanner_config import scanner_config_from_env


class ScannerConfigTest(unittest.TestCase):
    def test_uses_local_defaults_outside_github_actions(self):
        config = scanner_config_from_env({})

        self.assertEqual(config.timeout, 15)
        self.assertEqual(config.max_retries, 3)
        self.assertEqual(config.request_delay, 0.3)
        self.assertEqual(config.max_workers, 4)

    def test_uses_faster_settings_inside_github_actions(self):
        config = scanner_config_from_env({"GITHUB_ACTIONS": "true"})

        self.assertEqual(config.timeout, 8)
        self.assertEqual(config.max_retries, 1)
        self.assertEqual(config.request_delay, 0.1)
        self.assertEqual(config.max_workers, 8)


if __name__ == "__main__":
    unittest.main()
