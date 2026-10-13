"""test_dispatcher.py — the bash entry point resolves commands and interpreters safely.

``bin/tcut`` is intentionally a shell script so it can explain a broken TUI environment
before Python starts. These tests drive it with temporary script stubs and assert the routing
rules without opening a real database.
"""

import importlib.util
import os
import re
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
TUI = ROOT / "scripts" / "tcut-tui.py"
SCRIPTS = ROOT / "scripts"

# The help text is checked against the command table the dispatcher actually routes to,
# so the table has to be loaded — not copied into this file, which is how it drifted once.
sys.path.insert(0, str(SCRIPTS))          # tcut-stats imports tcut_db by module name
_spec = importlib.util.spec_from_file_location(
    "tcut_stats_for_dispatcher", SCRIPTS / "tcut-stats.py")
stats = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stats)

# The help text counts tabs in words, so the check needs the words.
NUMERAL_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                 "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
                 "eleven": 11, "twelve": 12}


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
        self.assertIn("tcut sync --full", proc.stdout)
        # The advertised tab count is checked against the app that composes the tabs.
        # Asserting a literal word here once passed on a help text that had fallen
        # behind the product, which is the whole reason the line existed.
        claimed = re.search(r"interactive TUI \((\w+) tabs\)", proc.stdout)
        self.assertTrue(claimed,
                        f"bin/tcut no longer states a tab count where this checks: "
                        f"{proc.stdout.splitlines()[:6]}")
        word = claimed.group(1)
        self.assertIn(word, NUMERAL_WORDS, f"unknown numeral word {word!r} in the help")
        panes = len(re.findall(r"with TabPane\(", TUI.read_text(encoding="utf-8")))
        self.assertTrue(panes, "the TUI source composes no TabPane at all — wrong file?")
        self.assertEqual(NUMERAL_WORDS[word], panes,
                         f"bin/tcut advertises {word} tabs, {TUI.name} composes {panes}")

    def test_an_invalid_interpreter_is_reported_before_exec(self):
        env = dict(self.env, TCUT_VENV=str(self.root / "missing-python"))
        proc = self.run_bin("stats", env=env)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("neither a venv dir nor an executable", proc.stderr)


    def test_the_help_names_every_headless_command(self):
        """`tcut help` is what a person reads when the TUI will not start.

        The header is a hand-copied list, and it had fallen behind the CLI it dispatches to:
        `models`, `credits` and `format` were reachable commands no help line mentioned. The
        check reads the real command table in both directions, so adding a command only
        passes once the help text names it — and renaming one cannot leave a ghost behind.
        """
        proc = self.run_bin("help")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        words = set()
        for line in proc.stdout.splitlines():
            # The header's command lines carry the indentation the comment block used,
            # so the prefix test strips it: the old substring assertions passed on
            # lines that never started where this looks.
            line = line.lstrip()
            if line.startswith("tcut "):
                words.update(t for t in line.split() if t.isalpha() and t.islower())
        piped = set()
        for token in proc.stdout.split():
            if "|" in token:
                piped.update(p for p in token.split("|") if p.isalpha() and p.islower())
        self.assertTrue(piped, "no `|` command list in the help — the pattern is wrong")
        named = words | piped
        self.assertFalse(set(stats.COMMANDS) - named,
                         f"bin/tcut help never names {sorted(set(stats.COMMANDS) - named)}")
        ghost = piped - set(stats.COMMANDS)
        self.assertFalse(ghost,
                         f"bin/tcut help advertises {sorted(ghost)} that no CLI command is")


if __name__ == "__main__":
    unittest.main()
