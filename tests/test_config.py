import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from koc import config


class ConfigTest(unittest.TestCase):
    def test_env_value_wins_over_local_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text('AI_API_KEY="from-file"\n', encoding="utf-8")

            with patch.object(config, "CONFIG_FILES", (env_path,)):
                with patch.dict(os.environ, {"AI_API_KEY": "from-env"}):
                    self.assertEqual(config.get_config_value("AI_API_KEY"), "from-env")

    def test_reads_local_env_file_when_process_env_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "# local config\nAI_API_KEY='from-file'\nAI_MODEL=gpt-test\n",
                encoding="utf-8",
            )

            with patch.object(config, "CONFIG_FILES", (env_path,)):
                with patch.dict(os.environ, {}, clear=True):
                    self.assertEqual(config.get_config_value("AI_API_KEY"), "from-file")
                    self.assertEqual(config.get_config_value("AI_MODEL"), "gpt-test")

    def test_reads_export_prefix_in_local_env_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text('export AI_API_KEY="from-export"\n', encoding="utf-8")

            with patch.object(config, "CONFIG_FILES", (env_path,)):
                with patch.dict(os.environ, {}, clear=True):
                    self.assertEqual(config.get_config_value("AI_API_KEY"), "from-export")

    def test_can_disable_local_config_for_isolated_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("AI_API_KEY=from-file\n", encoding="utf-8")

            with patch.object(config, "CONFIG_FILES", (env_path,)):
                with patch.dict(os.environ, {"KOC_DISABLE_LOCAL_CONFIG": "1"}, clear=True):
                    self.assertIsNone(config.get_config_value("AI_API_KEY"))


if __name__ == "__main__":
    unittest.main()
