import contextlib
import io
import unittest
from unittest.mock import patch

from koc import cli


class CliTest(unittest.TestCase):
    def run_cli(self, argv):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = cli.main(argv)
        return code, stdout.getvalue()

    def test_user_facing_commands_only_expose_known_entrypoints(self):
        parser = cli.build_parser()
        subparsers_action = next(
            action for action in parser._actions if action.dest == "command"
        )
        self.assertEqual(set(subparsers_action.choices), {"run-v2", "eval-v2"})

    def test_run_v2_delegates_to_the_single_production_entrypoint(self):
        with patch("run_brief.main", return_value=0) as run:
            code, _stdout = self.run_cli([
                "run-v2",
                "--watchlist", "watch.txt",
                "--schedule", "schedule.json",
                "--output", "site",
            ])

        self.assertEqual(code, 0)
        run.assert_called_once_with(
            output_dir="site",
            watchlist_path="watch.txt",
            schedule_path="schedule.json",
        )


if __name__ == "__main__":
    unittest.main()
