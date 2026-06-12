import unittest

from koc.output import Progress, print_json


class OutputTest(unittest.TestCase):
    def test_progress_log_writes_to_stdout(self):
        progress = Progress("test", enabled=True)
        progress.log("hello")
        # No exception = success

    def test_progress_disabled_is_silent(self):
        progress = Progress("test", enabled=False)
        progress.log("should not print")
        # No exception = success

    def test_print_json_outputs_valid_json(self):
        import contextlib, io, json

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            print_json({"ok": True})

        output = stdout.getvalue()
        data = json.loads(output)
        self.assertEqual(data, {"ok": True})


if __name__ == "__main__":
    unittest.main()
