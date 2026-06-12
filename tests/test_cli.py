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

    def test_user_facing_commands_only_expose_v2_entrypoints(self):
        parser = cli.build_parser()
        subparsers_action = next(action for action in parser._actions if action.dest == "command")

        self.assertEqual(
            set(subparsers_action.choices),
            {"run-v2", "eval-v2"},
        )


if __name__ == "__main__":
    unittest.main()
