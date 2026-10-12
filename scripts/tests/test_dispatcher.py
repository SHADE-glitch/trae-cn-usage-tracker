"""test_dispatcher.py — the bash entry point resolves commands and interpreters safely.

``bin/tcut`` is intentionally a shell script so it can explain a broken TUI environment
before Python starts. These tests drive it with temporary script stubs and assert the routing
rules without opening a real database.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parents[1]
sys.path.insert(0, str(TESTS))
import _hermetic  # noqa: E402,F401

BIN = ROOT / "bin" / "tcut"


class DispatcherTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.scripts = self.root / "scripts"
        self.scripts.mkdir()
        for name in ("tcut-tui.py", "tcut-sync.py", "tcut-stats.py"):
            (self.scripts / name).write_text(
                "import sys; print(sys.argv[0].split('/')[-1] + ' ' + ' '.join(sys.argv[1:]))\n",
                encoding="utf-8")
        self.env = dict(os.environ, TCUT_SCRIPTS=str(self.scripts),
                        TCUT_DB=str(self.root / "test.db"),
                        TCUT_VENV=sys.executable)

    def run_bin(self, *args, env=None):
        return subprocess.run([str(BIN), *args], capture_output=True, text=True,
                              env=env or self.env)

    def test_sync_routes_to_sync_script_and_preserves_arguments(self):
        proc = self.run_bin("sync", "--full", "--quiet")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("tcut-sync.py --full --quiet", proc.stdout)

    def test_tui_is_the_default_route(self):
        proc = self.run_bin()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("tcut-tui.py", proc.stdout)

    def test_headless_command_routes_to_stats_script(self):
        proc = self.run_bin("stats", "--limit", "3")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("tcut-stats.py stats --limit 3", proc.stdout)

    def test_help_reads_the_script_header(self):
        proc = self.run_bin("help")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("ten tabs", proc.stdout)
        self.assertIn("tcut sync --full", proc.stdout)

    def test_an_invalid_interpreter_is_reported_before_exec(self):
        env = dict(self.env, TCUT_VENV=str(self.root / "missing-python"))
        proc = self.run_bin("stats", env=env)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("neither a venv dir nor an executable", proc.stderr)


if __name__ == "__main__":
    unittest.main()
