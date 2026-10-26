"""test_sync.py — the indexer, driven against throwaway Trae-shaped fixtures.

The indexer is the half of this tool that reads someone else's on-disk data, so it is the
half that breaks when Trae changes something. Each handler is exercised directly (not through
``run()``) because the point is to pin *what each source contributes*, and a failure should
name the source rather than "sync returned 3 instead of 7".

Five properties, one class each:

1. **The bytes are read correctly** — a summary line becomes a session with its intent,
   outcome, actions and learned list; a topic line becomes a topic; a markdown doc becomes
   paragraphs; a git tag becomes a turn or a toolcall; a vscdb row becomes a prompt.
2. **Incremental reads are exact** — a streamed file is consumed by byte offset, and a
   partial trailing line is left for the next run rather than half-stored or double-counted.
   Idempotence is the whole premise of a 30-second sync timer, so it is tested, not assumed.
3. **A record the indexer cannot use is counted, never dropped** — the ``unparsed`` table is
   what turns a Trae format change into something a person can see.
4. **``store_content`` gates every piece of prose** — summaries, topics, actions, learned,
   prompts, memory docs. Metadata (ids, counts, inventory) is not gated, because that is the
   part the tracker exists to keep when content storage is off.
5. **``finalize`` derives the counts it claims to** — turns/toolcalls from the tag tables, and
   a real project path from ``workspace.json`` where one is known.

Standard library only. Every case builds its fixtures under ``tempfile`` and opens a database
there; ``_hermetic`` refuses the real ``usage.db`` if any of them slips.
"""

import json
import sqlite3
import sys
import tempfile
import unittest
import zlib
from datetime import datetime
from pathlib import Path

TESTS = Path(__file__).resolve().parent
SCRIPTS = TESTS.parent
sys.path.insert(0, str(TESTS))
import _hermetic  # noqa: E402,F401 -- tripwire: the suite must never open the real database
sys.path.insert(0, str(SCRIPTS))

import tcut_db as db  # noqa: E402

# ``tcut-sync.py`` has a hyphen in its name and cannot be imported normally; the
# data layer already carries the loader for it, so the tests use the same door.
sync = db.load_sync()

CFG = {"store_content": True}


def cfg(store_content=True):
    return {"store_content": store_content}


class Base(unittest.TestCase):
    """A throwaway database per case, closed on the way out."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.conn = db.open_db(self.tmp / "u.db")
        self.addCleanup(self.conn.close)
        db.ensure_schema(self.conn)

    def rows(self, sql, params=()):
        return self.conn.execute(sql, params).fetchall()

    def one(self, sql, params=()):
        return self.conn.execute(sql, params).fetchone()

    def stored_text(self):
        """Every value in every table, as one haystack for a privacy assertion."""
        parts = []
        for tab in self.rows("SELECT name FROM sqlite_master WHERE type='table'"):
            for row in self.rows('SELECT * FROM "%s"' % tab["name"]):
                parts.append("|".join(str(v) for v in tuple(row)))
        return "\n".join(parts)


# --- 1. helpers ------------------------------------------------------------


class DecodeTest(unittest.TestCase):
    """The lossy project-key codec, and the parse helpers built on it."""

    def test_p2_suffix_is_stripped_and_dashes_become_slashes(self):
        self.assertEqual(
            sync.decode_project("-home-user-Public--p2-ccbcb99c0123"),
            "/home/user/Public")

    def test_a_key_without_the_suffix_still_decodes(self):
        self.assertEqual(sync.decode_project("-home-user-tmp"), "/home/user/tmp")

    def test_a_dotted_segment_is_known_to_be_lossy(self):
        """A real ``.`` in a path is indistinguishable from the separator.

        This is not a bug to fix here — ``workspace.json`` is what resolves the true
        path, and ``FinalizeTest`` proves it does. Pinning the lossy result keeps the
        decoder honest about being a display convenience.
        """
        self.assertEqual(
            sync.decode_project("-home-user--local-share--p2-x"),
            "/home/user/local/share")

    def test_day_round_trips_and_rejects_nonsense(self):
        ms = sync.parse_day("20260101")
        self.assertEqual(sync.day_dir_name(ms), "20260101")
        self.assertIsNone(sync.parse_day("2026-01-01"))
        self.assertIsNone(sync.parse_day(None))

    def test_topic_time_accepts_the_three_shapes_trae_writes(self):
        expected = int(datetime(2026, 3, 4, 5, 6, 7).timestamp() * 1000)
        self.assertEqual(sync.parse_topic_time("2026-03-04 05:06:07"), expected)
        self.assertEqual(
            sync.parse_topic_time(" 2026-03-04 05:06:07 "), expected,
            "trailing space inside the bracket must not defeat the parse")
        self.assertEqual(sync.parse_topic_time("2026-03-04"),
                         int(datetime(2026, 3, 4).timestamp() * 1000))
        self.assertIsNone(sync.parse_topic_time("yesterday"))


# --- 2. session_memory_*.jsonl ---------------------------------------------


class SessionMemoryTest(Base):
    def _write(self, project_key, day, session_id, records, name=None):
        d = self.tmp / "projects" / project_key / day
        d.mkdir(parents=True, exist_ok=True)
        path = d / (name or f"session_memory_{session_id}.jsonl")
        body = "".join(json.dumps(r) + "\n" for r in records)
        path.write_text(body, encoding="utf-8")
        return path

    def test_a_summary_line_becomes_a_session_with_its_prose(self):
        self._write("-home-user-Public--p2-a", "20260304", "abc123", [{
            "intent": "add a sync timer",
            "outcome": "timer installed",
            "actions": ["edited tcut-sync.py", "ran tests"],
            "learned": ["offset must be bounded by size"],
        }])
        n = sync.scan_session_memory(self.conn, cfg(), self.tmp / "projects")
        self.conn.commit()
        self.assertEqual(n, 1)
        s = self.one("SELECT * FROM sessions WHERE session_id = 'abc123'")
        self.assertEqual(s["intent"], "add a sync timer")
        self.assertEqual(s["outcome"], "timer installed")
        self.assertEqual(s["project_key"], "-home-user-Public--p2-a")
        self.assertEqual(s["project"], "/home/user/Public")
        self.assertEqual(s["day"], "20260304")
        acts = self.rows("SELECT text FROM session_actions WHERE session_id='abc123' ORDER BY idx")
        self.assertEqual([r["text"] for r in acts], ["edited tcut-sync.py", "ran tests"])
        learned = self.rows("SELECT text FROM session_learned WHERE session_id='abc123'")
        self.assertEqual([r["text"] for r in learned], ["offset must be bounded by size"])

    def test_a_second_run_over_an_unchanged_file_consumes_nothing(self):
        """The premise of the sync timer: re-reading costs nothing and adds nothing."""
        self._write("-p--p2-a", "20260304", "abc123",
                    [{"intent": "one", "outcome": "done"}])
        root = self.tmp / "projects"
        sync.scan_session_memory(self.conn, cfg(), root)
        self.conn.commit()
        again = sync.scan_session_memory(self.conn, cfg(), root)
        self.conn.commit()
        self.assertEqual(again, 0, "a re-run re-read bytes it had already consumed")
        self.assertEqual(self.one("SELECT COUNT(*) c FROM sessions")["c"], 1)

    def test_appended_records_are_read_from_the_offset_not_from_the_top(self):
        path = self._write("-p--p2-a", "20260304", "abc123", [{"intent": "one"}])
        root = self.tmp / "projects"
        sync.scan_session_memory(self.conn, cfg(), root)
        self.conn.commit()
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"intent": "two", "outcome": "later"}) + "\n")
        n = sync.scan_session_memory(self.conn, cfg(), root)
        self.conn.commit()
        self.assertEqual(n, 1, "the appended line was not picked up")
        s = self.one("SELECT * FROM sessions WHERE session_id='abc123'")
        self.assertEqual(s["intent"], "two", "the newer record must win")
        self.assertEqual(s["outcome"], "later")

    def test_a_partial_trailing_line_is_left_for_the_next_run(self):
        """Never half-store a record, never double-count it either.

        A file being appended to can be caught mid-write; the tail that does not
        parse yet must stay unconsumed so the next run sees it whole.
        """
        d = self.tmp / "projects" / "-p--p2-a" / "20260304"
        d.mkdir(parents=True, exist_ok=True)
        path = d / "session_memory_abc123.jsonl"
        # One good line, then a truncated JSON object with no closing brace.
        path.write_text(json.dumps({"intent": "one"}) + "\n" + '{"intent": "par', encoding="utf-8")
        root = self.tmp / "projects"
        sync.scan_session_memory(self.conn, cfg(), root)
        self.conn.commit()
        self.assertEqual(self.one("SELECT COUNT(*) c FROM sessions")["c"], 1)
        # Now complete the line; the good one must not be counted twice.
        with open(path, "a", encoding="utf-8") as fh:
            fh.write('tial"}\n')
        n = sync.scan_session_memory(self.conn, cfg(), root)
        self.conn.commit()
        self.assertEqual(n, 1)
        self.assertEqual(self.one("SELECT intent FROM sessions WHERE session_id='abc123'")["intent"],
                         "partial")

    def test_a_misnamed_file_is_counted_not_silently_skipped(self):
        self._write("-p--p2-a", "20260304", "abc123", [{"intent": "x"}],
                    name="session_memory_NOTHEX.jsonl")
        sync.scan_session_memory(self.conn, cfg(), self.tmp / "projects")
        reasons = {r["reason"] for r in db.q_unparsed(self.conn)}
        self.assertIn("session_memory:bad_name", reasons)

    def test_a_non_json_line_is_counted(self):
        d = self.tmp / "projects" / "-p--p2-a" / "20260304"
        d.mkdir(parents=True, exist_ok=True)
        (d / "session_memory_abc123.jsonl").write_text("{not json}\n", encoding="utf-8")
        sync.scan_session_memory(self.conn, cfg(), self.tmp / "projects")
        reasons = {r["reason"] for r in db.q_unparsed(self.conn)}
        self.assertIn("session_memory:not_json", reasons)

    def test_store_content_off_keeps_the_ids_and_drops_the_prose(self):
        self._write("-home-user-Public--p2-a", "20260304", "abc123", [{
            "intent": "secret", "outcome": "secret", "actions": ["secret"],
            "learned": ["secret"]}])
        sync.scan_session_memory(self.conn, cfg(store_content=False),
                                 self.tmp / "projects")
        self.conn.commit()
        s = self.one("SELECT * FROM sessions WHERE session_id='abc123'")
        self.assertIsNotNone(s, "the session id was dropped along with its prose")
        self.assertIsNone(s["intent"])
        self.assertIsNone(s["outcome"])
        self.assertEqual(self.one("SELECT COUNT(*) c FROM session_actions")["c"], 0)
        self.assertEqual(self.one("SELECT COUNT(*) c FROM session_learned")["c"], 0)


# --- 3. topics.md ----------------------------------------------------------


class TopicsTest(Base):
    def _write(self, project_key, day, text):
        d = self.tmp / "projects" / project_key / day
        d.mkdir(parents=True, exist_ok=True)
        (d / "topics.md").write_text(text, encoding="utf-8")

    def test_a_topic_line_is_parsed_into_its_parts(self):
        self._write("-home-user-Public--p2-a", "20260304",
                    "[session_id: abc123 | topic_summary_time: 2026-03-04 05:06:07]"
                    " wired the sync timer\n")
        n = sync.scan_topics(self.conn, cfg(), self.tmp / "projects")
        self.conn.commit()
        self.assertEqual(n, 1)
        t = self.one("SELECT * FROM topics")
        self.assertEqual(t["session_id"], "abc123")
        self.assertEqual(t["summary"], "wired the sync timer")
        self.assertEqual(t["project_key"], "-home-user-Public--p2-a")
        self.assertEqual(t["ts"], int(datetime(2026, 3, 4, 5, 6, 7).timestamp() * 1000))

    def test_a_line_that_does_not_match_and_a_bad_time_are_counted_separately(self):
        self._write("-p--p2-a", "20260304",
                    "just some prose\n"
                    "[session_id: abc | topic_summary_time: whenever] late\n")
        sync.scan_topics(self.conn, cfg(), self.tmp / "projects")
        reasons = {r["reason"] for r in db.q_unparsed(self.conn)}
        self.assertIn("topic:no_match", reasons)
        self.assertIn("topic:bad_time", reasons)

    def test_an_unchanged_file_is_not_re_read(self):
        self._write("-p--p2-a", "20260304",
                    "[session_id: abc | topic_summary_time: 2026-03-04] one\n")
        root = self.tmp / "projects"
        sync.scan_topics(self.conn, cfg(), root)
        self.conn.commit()
        self.assertEqual(sync.scan_topics(self.conn, cfg(), root), 0)
        self.assertEqual(self.one("SELECT COUNT(*) c FROM topics")["c"], 1)

    def test_store_content_off_keeps_the_row_and_drops_the_summary(self):
        self._write("-p--p2-a", "20260304",
                    "[session_id: abc | topic_summary_time: 2026-03-04] secret\n")
        sync.scan_topics(self.conn, cfg(store_content=False), self.tmp / "projects")
        self.conn.commit()
        t = self.one("SELECT * FROM topics")
        self.assertIsNotNone(t, "the topic row is metadata (session + time) and must survive")
        self.assertIsNone(t["summary"])

    def test_a_removed_line_stops_being_indexed(self):
        """A topics file is a snapshot: a re-read replaces its rows, not merges.

        Upserting alone made the table a union of every version of the file ever
        seen, so a line the model withdrew stayed in the index for good.
        """
        self._write("-p--p2-a", "20260304",
                    "[session_id: abc | topic_summary_time: 2026-03-04 05:00:00] kept\n"
                    "[session_id: def | topic_summary_time: 2026-03-04 06:00:00] gone\n")
        root = self.tmp / "projects"
        sync.scan_topics(self.conn, cfg(), root)
        self.conn.commit()
        self.assertEqual(self.one("SELECT COUNT(*) c FROM topics")["c"], 2)

        self._write("-p--p2-a", "20260304",
                    "[session_id: abc | topic_summary_time: 2026-03-04 05:00:00] kept\n")
        sync.scan_topics(self.conn, cfg(), root)
        self.conn.commit()
        summaries = [r["summary"] for r in self.rows("SELECT summary FROM topics")]
        self.assertEqual(summaries, ["kept"],
                         "a line deleted from the file was still indexed")

    def test_a_bad_line_is_counted_once_however_often_the_file_is_reread(self):
        """The skip count describes the file, not the number of syncs.

        A topics file is re-read whole on every change, and the count was added
        to each time — three edits of a file with one bad line reported three
        unparsed records and made `tcut health` look like a format change.
        """
        self._write("-p--p2-a", "20260304", "not a topic line\n")
        root = self.tmp / "projects"
        for i in range(3):
            self._write("-p--p2-a", "20260304",
                        "not a topic line\n"
                        f"[session_id: s{i} | topic_summary_time: 2026-03-04] ok\n")
            sync.scan_topics(self.conn, cfg(), root)
            self.conn.commit()
        counted = {r["reason"]: r["count"] for r in db.q_unparsed(self.conn)}
        self.assertEqual(counted.get("topic:no_match"), 1,
                         f"one bad line was counted {counted.get('topic:no_match')} times")


# --- 4. memory documents ---------------------------------------------------


class MemoryDocsTest(Base):
    def test_user_profile_and_project_memory_become_scoped_paragraphs(self):
        root = self.tmp / "memory"
        root.mkdir()
        (root / "user_profile.md").write_text("Likes tabs.\n\nPrefers stdlib.\n",
                                              encoding="utf-8")
        proj = root / "projects" / "-home-user-Public--p2-a"
        proj.mkdir(parents=True)
        (proj / "project_memory.md").write_text("# Title\nbody line\n\n- bullet\n",
                                                encoding="utf-8")
        n = sync.scan_memory_docs(self.conn, cfg(), root)
        self.conn.commit()
        self.assertEqual(n, 4, "two user-profile paragraphs plus two project-memory blocks")
        scopes = {r["scope"] for r in self.rows("SELECT DISTINCT scope FROM memory")}
        self.assertEqual(scopes, {"user_profile", "project:-home-user-Public--p2-a"})
        # A headed block is one paragraph: the heading stays attached to its body.
        texts = [r["text"] for r in self.rows(
            "SELECT text FROM memory WHERE scope LIKE 'project:%' ORDER BY idx")]
        self.assertEqual(texts, ["# Title\nbody line", "- bullet"])

    def test_paragraphs_are_blank_line_separated_blocks(self):
        path = self.tmp / "doc.md"
        path.write_text("a\nb\n\n\nc\n", encoding="utf-8")
        self.assertEqual(sync._paragraphs(path), ["a\nb", "c"])

    def test_store_content_off_stores_no_paragraphs(self):
        root = self.tmp / "memory"
        root.mkdir()
        (root / "user_profile.md").write_text("secret\n", encoding="utf-8")
        n = sync.scan_memory_docs(self.conn, cfg(store_content=False), root)
        self.assertEqual(n, 0)
        self.assertEqual(self.one("SELECT COUNT(*) c FROM memory")["c"], 0)

    def test_a_removed_document_is_reflected(self):
        """The table is rebuilt each run, so a deleted doc must not linger."""
        root = self.tmp / "memory"
        root.mkdir()
        doc = root / "user_profile.md"
        doc.write_text("first\n", encoding="utf-8")
        sync.scan_memory_docs(self.conn, cfg(), root)
        self.conn.commit()
        # Bump mtime by rewriting, then confirm the content follows.
        doc.write_text("second version\n", encoding="utf-8")
        sync.scan_memory_docs(self.conn, cfg(), root)
        self.conn.commit()
        texts = [r["text"] for r in self.rows("SELECT text FROM memory")]
        self.assertEqual(texts, ["second version"])

    def test_a_second_run_keeps_the_documents_it_did_not_reread(self):
        """The table is replaced per document, not cleared per run.

        A clear-then-reread-only-changed pass looks idempotent and is not: the
        first sync fills the table, every later sync of the 30-second timer
        empties it, and `tcut memory` answered with the command that kept it
        empty. A run that reads no document must leave every row where it was.
        """
        root = self.tmp / "memory"
        root.mkdir()
        (root / "user_profile.md").write_text("first\n\nsecond\n", encoding="utf-8")
        proj = root / "projects" / "-p--p2-a"
        proj.mkdir(parents=True)
        (proj / "project_memory.md").write_text("project line\n", encoding="utf-8")
        sync.scan_memory_docs(self.conn, cfg(), root)
        self.conn.commit()
        sql = "SELECT scope, idx, text FROM memory ORDER BY scope, idx"
        before = [tuple(r) for r in self.rows(sql)]
        self.assertEqual(len(before), 3, "the fixture did not index both documents")

        again = sync.scan_memory_docs(self.conn, cfg(), root)
        self.conn.commit()
        self.assertEqual(again, 0, "an unchanged document was re-read")
        self.assertEqual([tuple(r) for r in self.rows(sql)], before,
                         "a run that changed nothing emptied the memory table")

    def test_a_deleted_document_takes_its_paragraphs_with_it(self):
        """Replacing per document must still notice a document that is gone."""
        root = self.tmp / "memory"
        root.mkdir()
        (root / "user_profile.md").write_text("kept\n", encoding="utf-8")
        proj = root / "projects" / "-p--p2-a"
        proj.mkdir(parents=True)
        gone = proj / "project_memory.md"
        gone.write_text("dropped\n", encoding="utf-8")
        sync.scan_memory_docs(self.conn, cfg(), root)
        self.conn.commit()
        gone.unlink()
        sync.scan_memory_docs(self.conn, cfg(), root)
        self.conn.commit()
        scopes = {r["scope"] for r in self.rows("SELECT DISTINCT scope FROM memory")}
        self.assertEqual(scopes, {"user_profile"})


# --- 5. snapshot git tags --------------------------------------------------


def _commit_obj(ts):
    """A minimal, valid loose git commit object for ``_commit_time`` to inflate."""
    body = (b"tree " + b"0" * 40 + b"\n"
            b"author A <a@b> " + str(ts).encode() + b" +0000\n"
            b"committer A <a@b> " + str(ts).encode() + b" +0000\n"
            b"\nmessage\n")
    raw = b"commit " + str(len(body)).encode() + b"\x00" + body
    return zlib.compress(raw)


def _tag_obj(name, commit_sha, tagger_ts):
    """A loose annotated-tag object: what Trae's snapshot refs actually name."""
    body = (f"object {commit_sha}\ntype commit\ntag {name}\n"
            f"tagger T <t@b> {tagger_ts} +0800\n\nmessage\n").encode()
    return zlib.compress(b"tag " + str(len(body)).encode() + b"\x00" + body)


class SnapshotsTest(Base):
    def _repo(self, session_id, tags, annotated=False, tagger_skew=7):
        """A throwaway snapshot repo with turn/toolcall tags.

        ``annotated=True`` reproduces what is on the real machine: the ref names a
        ``tag`` object whose ``object`` line points at the commit. Measured on one
        session repo's 87 tags, *every* ref named a tag object. The lightweight form
        this fixture used to write is why a parser that only recognised a ``commit ``
        header stayed green here while returning ``None`` for all 89 turn and 139
        toolcall timestamps at home.
        """
        git = self.tmp / "snapshot" / session_id / "v2" / ".git"
        (git / "refs" / "tags").mkdir(parents=True)
        for tag, ts in tags.items():
            commit_sha = ("%040x" % (abs(hash(tag)) % 16 ** 40))
            sha = ("%040x" % (abs(hash(("tag", tag))) % 16 ** 40)) if annotated else commit_sha
            if annotated:
                self._object(git, commit_sha, _commit_obj(ts))
            self._object(git, sha, _tag_obj(tag, commit_sha, ts + tagger_skew)
                         if annotated else _commit_obj(ts))
            ref = git / "refs" / "tags" / tag
            ref.parent.mkdir(parents=True, exist_ok=True)
            ref.write_text(sha + "\n", encoding="ascii")
        return git

    @staticmethod
    def _object(git, sha, payload):
        obj = git / "objects" / sha[:2] / sha[2:]
        obj.parent.mkdir(parents=True, exist_ok=True)
        obj.write_bytes(payload)

    def test_turn_and_toolcall_tags_become_rows_with_timestamps(self):
        self._repo("sess1", {
            "before-chat-turn-1": 1700000000,
            "after-chat-turn-1": 1700000001,
            "toolcall-msg1-call1": 1700000002,
        })
        n = sync.scan_snapshots(self.conn, cfg(), self.tmp / "snapshot")
        self.conn.commit()
        self.assertEqual(n, 3)
        turns = {r["turn_id"] for r in self.rows("SELECT turn_id FROM turns")}
        self.assertEqual(turns, {"1"})
        ev = self.one("SELECT * FROM toolcall_events")
        self.assertEqual((ev["message_id"], ev["toolcall_id"]), ("msg1", "call1"))
        self.assertEqual(ev["ts"], 1700000002 * 1000,
                         "the commit time must survive the zlib round-trip")

    def test_a_packed_ref_is_read_too(self):
        git = self.tmp / "snapshot" / "sess2" / "v2" / ".git"
        (git / "refs" / "tags").mkdir(parents=True)
        sha = "a" * 40
        (git / "packed-refs").write_text(
            "# pack-refs with: peeled fully-peeled sorted \n"
            f"{sha} refs/tags/after-chat-turn-9\n", encoding="ascii")
        obj = git / "objects" / sha[:2] / sha[2:]
        obj.parent.mkdir(parents=True, exist_ok=True)
        obj.write_bytes(_commit_obj(1700000000))
        sync.scan_snapshots(self.conn, cfg(), self.tmp / "snapshot")
        self.conn.commit()
        self.assertEqual(self.one("SELECT turn_id FROM turns")["turn_id"], "9")

    def test_a_tag_that_is_neither_a_turn_nor_a_toolcall_is_ignored(self):
        self._repo("sess3", {"some-other-tag": 1700000000})
        n = sync.scan_snapshots(self.conn, cfg(), self.tmp / "snapshot")
        self.conn.commit()
        self.assertEqual(n, 0)
        self.assertEqual(self.one("SELECT COUNT(*) c FROM turns")["c"], 0)

    def test_an_annotated_tag_is_peeled_to_the_commit_time(self):
        self._repo("sess5", {"after-chat-turn-1": 1700000000,
                             "toolcall-m1-c1": 1700000005}, annotated=True)
        n = sync.scan_snapshots(self.conn, cfg(), self.tmp / "snapshot")
        self.conn.commit()
        self.assertEqual(n, 2)
        got = {r["turn_id"]: r["ts"] for r in self.rows("SELECT turn_id, ts FROM turns")}
        self.assertEqual(got, {"1": 1700000000 * 1000},
                         "the tag object was not peeled, so the turn kept no time")
        ev = self.one("SELECT ts FROM toolcall_events")
        self.assertEqual(ev["ts"], 1700000005 * 1000,
                         "a toolcall tag was stored undated — every windowed view "
                         "would then treat the row as if it did not exist")
        self.assertEqual(self.one("SELECT COALESCE(SUM(count),0) c FROM unparsed")["c"], 0,
                         "a readable annotated tag must not be reported as a gap")

    def test_the_tagger_line_stands_in_when_only_the_tag_object_is_readable(self):
        # The commit object is the preferred time; a repo whose commit is gone (or
        # packed) still knows when the tag itself was made. Measured at home: the
        # tagger epoch sits about ten seconds after the commit it tags.
        git = self._repo("sess6", {"after-chat-turn-2": 1700000000}, annotated=True)
        commit_sha = "%040x" % (abs(hash("after-chat-turn-2")) % 16 ** 40)
        (git / "objects" / commit_sha[:2] / commit_sha[2:]).unlink()
        sync.scan_snapshots(self.conn, cfg(), self.tmp / "snapshot")
        self.conn.commit()
        self.assertEqual(self.one("SELECT ts FROM turns")["ts"], 1700000007 * 1000,
                         "the tagger fallback did not fire")

    def test_a_tag_whose_objects_cannot_be_read_is_counted_not_silently_undated(self):
        # The gap this pins: a packed or garbage-collected object makes every
        # timestamp NULL. That is survivable once, never silently again.
        git = self.tmp / "snapshot" / "sess7" / "v2" / ".git"
        (git / "refs" / "tags").mkdir(parents=True)
        (git / "refs" / "tags" / "after-chat-turn-3").write_text("b" * 40 + "\n",
                                                                 encoding="ascii")
        sync.scan_snapshots(self.conn, cfg(), self.tmp / "snapshot")
        self.conn.commit()
        self.assertEqual(self.one("SELECT ts FROM turns")["ts"], None)
        rows = self.rows("SELECT reason, count FROM unparsed")
        self.assertEqual([(r["reason"], r["count"]) for r in rows],
                         [("snapshot:time_unreadable", 1)],
                         "an undated row was recorded without saying so")

    def test_a_lightweight_ref_still_reads_its_commit(self):
        self._repo("sess8", {"before-chat-turn-4": 1700000000})
        sync.scan_snapshots(self.conn, cfg(), self.tmp / "snapshot")
        self.conn.commit()
        self.assertEqual(self.one("SELECT ts FROM turns")["ts"], 1700000000 * 1000)

    def test_an_unchanged_repo_is_not_re_read(self):
        self._repo("sess4", {"after-chat-turn-1": 1700000000})
        root = self.tmp / "snapshot"
        sync.scan_snapshots(self.conn, cfg(), root)
        self.conn.commit()
        self.assertEqual(sync.scan_snapshots(self.conn, cfg(), root), 0,
                         "the fingerprint did not hold, so every sync would re-read every repo")
        self.assertEqual(self.one("SELECT COUNT(*) c FROM turns")["c"], 1)


# --- 6. state.vscdb --------------------------------------------------------


class VscdbTest(Base):
    def _vscdb(self, workspace, key_values, folder=None):
        ws = self.tmp / "User" / "workspaceStorage" / workspace
        ws.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(ws / "state.vscdb")
        conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value BLOB)")
        for k, v in key_values.items():
            payload = v if isinstance(v, (bytes, bytearray)) else json.dumps(v)
            conn.execute("INSERT INTO ItemTable(key, value) VALUES(?,?)", (k, payload))
        conn.commit()
        conn.close()
        if folder is not None:
            (ws / "workspace.json").write_text(
                json.dumps({"folder": f"file://{folder}"}), encoding="utf-8")
        return ws

    def setUp(self):
        super().setUp()
        self._old_data = db.TRAE_CN_DATA
        db.TRAE_CN_DATA = self.tmp
        self.addCleanup(lambda: setattr(db, "TRAE_CN_DATA", self._old_data))

    def test_prompt_history_agent_map_defs_and_models_all_land(self):
        self._vscdb("ws1", {
            "icube-ai-agent-storage-input-history": [
                {"inputText": "first prompt"},
                {"inputText": "  "},              # whitespace-only: not a prompt
                {"inputText": "second prompt"},
            ],
            "icube_session_agent_map": {"sess1": "builder"},
            "currentAgentData%abc": {"name": "builder", "type": "custom",
                                     "description": "does builds"},
            "somekey_AI.agent.model.model_list_map": {
                "grp": [{"name": "Model X", "provider": "acme"}]},
            "memento/icube-ai-agent-storage": {"list": [{"sessionId": "sess2"}]},
        }, folder="/home/user/Public")
        n = sync.scan_state_vscdb(self.conn, cfg())
        self.conn.commit()
        self.assertGreaterEqual(n, 5)
        prompts = [r["text"] for r in self.rows(
            "SELECT text FROM prompts ORDER BY idx")]
        self.assertEqual(prompts, ["first prompt", "second prompt"],
                         "a blank entry must not become a prompt row")
        folder = self.one("SELECT folder FROM workspaces WHERE workspace='ws1'")["folder"]
        self.assertEqual(folder, "/home/user/Public")
        self.assertEqual(self.one(
            "SELECT agent FROM sessions WHERE session_id='sess1'")["agent"], "builder")
        self.assertEqual(self.one(
            "SELECT kind FROM agents WHERE name='builder'")["kind"], "custom")
        self.assertEqual(self.one(
            "SELECT provider FROM models WHERE name='Model X'")["provider"], "acme")
        self.assertEqual(self.one(
            "SELECT COUNT(*) c FROM sessions WHERE session_id='sess2'")["c"], 1)

    def test_a_failed_read_does_not_advance_the_cursor(self):
        """A read that raised must be retried, not recorded as already indexed.

        The cursor is written from the file's size and mtime, so writing it after
        a failure told every later sync that a file it could not read had been
        read — the prompts and the catalog stayed missing with no trace.
        """
        ws = self.tmp / "User" / "workspaceStorage" / "ws1"
        ws.mkdir(parents=True, exist_ok=True)
        path = ws / "state.vscdb"
        broken = sqlite3.connect(path)
        broken.execute("CREATE TABLE SomethingElse (key TEXT)")
        broken.commit()
        broken.close()

        sync.scan_state_vscdb(self.conn, cfg())
        self.conn.commit()
        cursor = self.one("SELECT COUNT(*) c FROM sync_state WHERE source = ?",
                          (str(path),))["c"]
        self.assertEqual(cursor, 0,
                         "a failed read left a cursor telling the next sync to skip the file")
        self.assertIn("vscdb:read_failed",
                      {r["reason"] for r in db.q_unparsed(self.conn)})

    def test_store_content_off_keeps_agents_models_and_the_session_list(self):
        self._vscdb("ws1", {
            "icube-ai-agent-storage-input-history": [{"inputText": "secret prompt"}],
            "icube_session_agent_map": {"sess1": "builder"},
            "somekey_AI.agent.model.model_list_map": {
                "grp": [{"name": "Model X", "provider": "acme"}]},
        })
        sync.scan_state_vscdb(self.conn, cfg(store_content=False))
        self.conn.commit()
        self.assertEqual(self.one("SELECT COUNT(*) c FROM prompts")["c"], 0,
                         "a prompt survived with store_content off")
        self.assertEqual(self.one(
            "SELECT agent FROM sessions WHERE session_id='sess1'")["agent"], "builder",
            "the session metadata is not prose and must survive")
        self.assertEqual(self.one(
            "SELECT COUNT(*) c FROM models WHERE name='Model X'")["c"], 1)

    def test_a_percent_encoded_uri_decodes_without_urllib(self):
        self.assertEqual(sync._folder_from_uri("file:///home/user/My%20Dir"),
                         "/home/user/My Dir")
        self.assertEqual(sync._folder_from_uri("file:///home/user/%E4%B8%AD%E6%96%87"),
                         "/home/user/中文")
        self.assertIsNone(sync._folder_from_uri("not-a-uri"))

    def test_a_vscdb_without_our_keys_is_harmless(self):
        self._vscdb("ws1", {"unrelated.key": {"x": 1}})
        n = sync.scan_state_vscdb(self.conn, cfg())
        self.conn.commit()
        self.assertEqual(n, 0)

    # --- the model axis ---------------------------------------------------
    #
    # Trae's catalog is keyed by account and by agent group, and one name appears
    # under many of both: the real footprint holds 284 entries under 42 distinct
    # names. A name-only key did not merely lose detail — it lost 242 advertised
    # models, and the loss looked like a clean sync.

    def test_the_same_name_under_two_accounts_and_groups_keeps_every_row(self):
        self._vscdb("ws1", {
            "acct-A_AI.agent.model.model_list_map": {
                "builder": [{"name": "DeepSeek-V4", "provider": "volc"}],
                "solo_agent": [{"name": "DeepSeek-V4", "provider": "volc"}]},
            "acct-B_AI.agent.model.model_list_map": {
                "builder": [{"name": "DeepSeek-V4", "provider": "acme"}]},
        })
        sync.scan_state_vscdb(self.conn, cfg())
        self.conn.commit()
        rows = self.rows("SELECT account, group_name, provider FROM models"
                         " ORDER BY account, group_name")
        self.assertEqual([(r["account"], r["group_name"], r["provider"])
                          for r in rows],
                         [("acct-A", "builder", "volc"),
                          ("acct-A", "solo_agent", "volc"),
                          ("acct-B", "builder", "acme")],
                         "the catalog collapsed back onto the name alone")

    def test_a_model_entrys_credentials_are_never_stored(self):
        # A custom-provider entry carries `ak`/`sk`/`base_url` next to the fields we
        # do read. The whitelist is the only thing between those and the index.
        self._vscdb("ws1", {
            "acct-A_AI.agent.model.model_list_map": {"builder": [{
                "name": "Model X", "provider": "acme",
                "ak": "AKSENTINEL", "sk": "SKSENTINEL",
                "base_url": "https://sentinel.invalid/v1",
                "custom_config": {"token": "CFGSENTINEL"},
            }]},
        })
        sync.scan_state_vscdb(self.conn, cfg())
        self.conn.commit()
        stored = self.stored_text()
        self.assertIn("Model X", stored, "the entry itself did not land")
        for needle in ("AKSENTINEL", "SKSENTINEL", "sentinel.invalid", "CFGSENTINEL"):
            self.assertNotIn(needle, stored,
                             "%s reached the index" % needle)

    def test_catalog_numbers_come_from_where_trae_puts_them(self):
        self._vscdb("ws1", {
            "acct-A_AI.agent.model.model_list_map": {"builder": [
                {"name": "Rich", "provider": "acme", "model_type": "chat",
                 "fee_model_level": 2, "prompt_max_tokens": 168000,
                 "context_window_size": {"max": [200000], "default": 184000},
                 "features": {"consumption_rate": {"data": {"rate": 0.39}}}},
                {"name": "NoDefault", "provider": "acme",
                 "context_window_size": {"max": [128000]}},
                {"name": "WrongTypes", "provider": "acme",
                 "fee_model_level": True,
                 "context_window_size": {"max": "wide"},
                 "features": {"consumption_rate": {"data": {"rate": "0.39"}}}},
            ]},
        })
        sync.scan_state_vscdb(self.conn, cfg())
        self.conn.commit()
        rich = self.one("SELECT * FROM models WHERE name='Rich'")
        self.assertEqual((rich["fee_level"], rich["prompt_max"],
                          rich["context_window"], rich["consumption_rate"],
                          rich["model_type"]),
                         (2, 168000, 184000, 0.39, "chat"))
        self.assertEqual(
            self.one("SELECT context_window c FROM models WHERE name='NoDefault'")["c"],
            128000, "the default is absent, so max[0] is the window")
        odd = self.one("SELECT * FROM models WHERE name='WrongTypes'")
        self.assertIsNone(odd["fee_level"], "a bool is an int subclass, not a fee level")
        self.assertIsNone(odd["context_window"])
        self.assertIsNone(odd["consumption_rate"],
                          "'0.39' as a string must not become a number")

    def test_each_session_keeps_one_model_row_per_agent_label(self):
        self._vscdb("ws1", {
            "icube_session_agent_map": {"sess1": "builder"},
            "1234:AI.agent.model.session_selected_model": {
                "sess1": {"agent": {"modelId": "agent_1__X_null", "mode": 0},
                          "solo_agent": {"modelId": "solo_1__Y_null", "mode": 3}},
            },
        })
        sync.scan_state_vscdb(self.conn, cfg())
        self.conn.commit()
        rows = self.rows("SELECT agent_label, model_id, mode, account FROM session_models"
                         " ORDER BY agent_label")
        self.assertEqual([(r["agent_label"], r["model_id"], r["mode"], r["account"])
                          for r in rows],
                         [("agent", "agent_1__X_null", 0, "1234"),
                          ("solo_agent", "solo_1__Y_null", 3, "1234")])
        # The list view collapses the two labels, and it must say which it chose.
        self.assertEqual(db.q_sessions(self.conn)[0]["model_id"], "agent_1__X_null")

    def test_a_session_with_no_selection_reads_as_unknown_not_as_a_model(self):
        self._vscdb("ws1", {"icube_session_agent_map": {"sess9": "builder"}})
        sync.scan_state_vscdb(self.conn, cfg())
        self.conn.commit()
        self.assertIsNone(db.q_sessions(self.conn)[0]["model_id"],
                          "an absent selection must not render as some default model")

    def test_every_malformed_usage_shape_has_its_own_unparsed_reason(self):
        # One reason per branch, all provoked in a single store: a format change in
        # Trae has to show up as a named count, never as a clean zero.
        self._vscdb("ws1", {
            "a_AI.agent.model.model_list_map": b"{not json",
            "b_AI.agent.model.model_list_map": [1, 2],
            "c_AI.agent.model.model_list_map": {"g": {"not": "a list"}},
            "d_AI.agent.model.model_list_map": {"g": ["a string"]},
            "e_AI.agent.model.model_list_map": {"g": [{"provider": "x"}]},
            "1:AI.agent.model.session_selected_model": b"{oops",
            "2:AI.agent.model.session_selected_model": [1],
            "3:AI.agent.model.session_selected_model": {"s": {"agent": {}}},
            "4:AI.agent.model.session_selected_model": {"s": "not a dict"},
        })
        sync.scan_state_vscdb(self.conn, cfg())
        self.conn.commit()
        reasons = {r["reason"] for r in db.q_unparsed(self.conn)}
        for reason in ("model_map:not_json", "model_map:shape",
                       "model_map:group_shape", "model_map:entry_shape",
                       "model_map:no_name", "session_model:not_json",
                       "session_model:shape", "session_model:no_model_id"):
            self.assertIn(reason, reasons, "%s was never counted" % reason)


# --- 7. inventory ----------------------------------------------------------


class InventoryTest(Base):
    def setUp(self):
        super().setUp()
        self._old_home = db.TRAE_CN_HOME
        db.TRAE_CN_HOME = self.tmp
        self.addCleanup(lambda: setattr(db, "TRAE_CN_HOME", self._old_home))

    def test_skills_plugins_and_mcps_are_enumerated(self):
        (self.tmp / "skills" / "my-skill").mkdir(parents=True)
        (self.tmp / "builtin_skills" / "sys-skill").mkdir(parents=True)
        (self.tmp / "skills" / "_private").mkdir(parents=True)   # underscore-prefixed: skipped
        plugin = self.tmp / "plugins" / "mkt" / "helper" / "v1"
        (plugin / "skills" / "owned-skill").mkdir(parents=True)
        (plugin / ".trae-plugin").mkdir(parents=True)
        (plugin / ".trae-plugin" / "plugin.json").write_text(
            json.dumps({"version": "1.2.3"}), encoding="utf-8")
        mcp = self.tmp / "mcps" / "project" / "my-server"
        mcp.mkdir(parents=True)
        (mcp / "SERVER_METADATA.json").write_text(
            json.dumps({"server_name": "Friendly Name"}), encoding="utf-8")

        n = sync.scan_inventory(self.conn, cfg())
        self.conn.commit()
        self.assertGreater(n, 0)
        kinds = {r["kind"]: r["c"] for r in self.rows(
            "SELECT kind, COUNT(*) c FROM inventory GROUP BY kind")}
        self.assertEqual(kinds.get("skill"), 3, "user + builtin + plugin-owned, minus _private")
        self.assertEqual(kinds.get("plugin"), 1)
        self.assertEqual(kinds.get("mcp"), 1)
        skill = self.one("SELECT * FROM inventory WHERE name='sys-skill'")
        self.assertEqual(skill["source"], "builtin")
        owned = self.one("SELECT * FROM inventory WHERE name='owned-skill'")
        self.assertEqual((owned["source"], owned["owner_plugin"]), ("plugin", "helper"))
        pl = self.one("SELECT * FROM inventory WHERE kind='plugin'")
        self.assertEqual(pl["version"], "1.2.3", "the plugin manifest version was not read")
        mcp_row = self.one("SELECT * FROM inventory WHERE kind='mcp'")
        self.assertEqual(mcp_row["name"], "Friendly Name",
                         "the server's own name must win over the directory name")
        self.assertEqual(mcp_row["owner_plugin"], "project", "scope is the parent dir")

    def test_inventory_is_rebuilt_not_appended(self):
        (self.tmp / "skills" / "one").mkdir(parents=True)
        sync.scan_inventory(self.conn, cfg())
        self.conn.commit()
        import shutil
        shutil.rmtree(self.tmp / "skills" / "one")
        (self.tmp / "skills" / "two").mkdir(parents=True)
        sync.scan_inventory(self.conn, cfg())
        self.conn.commit()
        names = {r["name"] for r in self.rows("SELECT name FROM inventory")}
        self.assertEqual(names, {"two"}, "a removed skill lingered in the inventory")

    def test_a_plugin_with_no_version_dir_still_lists(self):
        (self.tmp / "plugins" / "mkt" / "bare").mkdir(parents=True)
        sync.scan_inventory(self.conn, cfg())
        self.conn.commit()
        row = self.one("SELECT * FROM inventory WHERE name='bare'")
        self.assertIsNotNone(row)
        self.assertIsNone(row["version"])


# --- 8. finalize -----------------------------------------------------------


# --- 8. credit balance observations ----------------------------------------


BALANCE = ("2026-10-07T08:55:51.467+08:00 [info] [ICubeUsageService] credits mutation "
           'refresh completed {"generation":0,"remaining":154.0244}')
SKIPPED = ("2026-10-07T09:59:27.085+08:00 [warning] [ICubeUsageService] "
           "fetchCreditsUsageInfo skipped: no userInfo")


class CreditLogTest(Base):
    """The only consumption-derived number Trae writes: its credit balance line.

    A balance is a *level*, sampled at app start, and grants raise it between
    samples — so the tests here pin the sampling honesty as much as the parsing.
    """

    def _logs(self, *session_logs):
        """Write `logs/<session>/<relpath>` files; returns the logs root."""
        root = self.tmp / "logs"
        for session, relpath, lines in session_logs:
            path = root / session / relpath
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("".join(l + "\n" for l in lines), encoding="utf-8")
        return root

    def test_the_offset_in_the_stamp_is_honoured_not_treated_as_local(self):
        # Asserted as a *difference between four spellings of one wall clock*, so it
        # holds on a UTC+8 box and a UTC box alike. The first version of this test
        # compared against a UTC constant and stayed green through a mutation that
        # dropped the offset entirely — on this machine +08:00 *is* local time.
        root = self._logs(
            ("plus8", "window1/renderer.log", [BALANCE]),
            ("plus0", "window1/renderer.log", [BALANCE.replace("+08:00", "+00:00")]),
            ("zulu", "window1/renderer.log", [BALANCE.replace("+08:00", "Z")]),
            ("minus5", "window1/renderer.log", [BALANCE.replace("+08:00", "-05:00")]),
        )
        sync.scan_credit_logs(self.conn, cfg(), root)
        self.conn.commit()
        HOUR = 3600 * 1000
        by_session = {r["source"].split("/logs/")[1].split("/")[0]: r["ts"]
                      for r in self.rows("SELECT source, ts FROM credit_events")}
        self.assertEqual(len(by_session), 4, "a spelling did not produce its own row")
        utc = by_session["plus0"]
        self.assertEqual(by_session["zulu"], utc, "Z is UTC, not a local stamp")
        self.assertEqual(by_session["plus8"], utc - 8 * HOUR)
        self.assertEqual(by_session["minus5"], utc + 5 * HOUR)
        self.assertEqual(self.one(
            "SELECT COUNT(DISTINCT remaining) c FROM credit_events")["c"], 1,
            "the same wall clock should not read as four different balances")
        row = self.one("SELECT kind, remaining, generation FROM credit_events LIMIT 1")
        self.assertEqual((row["kind"], row["remaining"], row["generation"]),
                         ("balance", 154.0244, 0))

    def test_a_stamp_without_an_offset_is_read_as_local_time(self):
        root = self._logs(("s1", "window1/renderer.log",
                           ["2026-10-07T08:55:51.467 [info] [ICubeUsageService] "
                            'credits mutation refresh completed {"generation":3,'
                            '"remaining":42}']))
        sync.scan_credit_logs(self.conn, cfg(), root)
        self.conn.commit()
        row = self.one("SELECT ts, generation, remaining FROM credit_events")
        self.assertEqual(row["ts"],
                         int(datetime(2026, 10, 7, 8, 55, 51, 467000).timestamp() * 1000),
                         "a stamp with no offset is local; assuming UTC shifts it")
        self.assertEqual((row["generation"], row["remaining"]), (3, 42.0))

    def test_a_numberless_event_is_kept_as_skipped_and_stays_out_of_the_series(self):
        root = self._logs(("s1", "window1/renderer.log", [BALANCE, SKIPPED]))
        sync.scan_credit_logs(self.conn, cfg(), root)
        self.conn.commit()
        self.assertEqual(self.one(
            "SELECT kind FROM credit_events WHERE kind='skipped'")["kind"], "skipped")
        series = db.q_credits(self.conn)
        self.assertEqual(len(series), 1,
                         "a skipped fetch must not become a data point, let alone a 0")

    def test_the_fall_between_two_balances_is_reported_as_a_lower_bound(self):
        root = self._logs(
            ("s1", "window1/renderer.log",
             ['2026-10-02T10:00:00+08:00 [info] [ICubeUsageService] credits mutation '
              'refresh completed {"generation":0,"remaining":100}',
              '2026-10-03T10:00:00+08:00 [info] [ICubeUsageService] credits mutation '
              'refresh completed {"generation":0,"remaining":1800}',
              '2026-10-04T10:00:00+08:00 [info] [ICubeUsageService] credits mutation '
              'refresh completed {"generation":0,"remaining":154.0244}']))
        sync.scan_credit_logs(self.conn, cfg(), root)
        self.conn.commit()
        series = db.q_credits(self.conn)          # newest first
        self.assertEqual([r["spent_at_least"] for r in series],
                         [1645.9756, 0.0, 0.0],
                         "a grant that raises the balance is not spending")

    def test_the_log_line_around_the_number_is_not_stored(self):
        # The balance line sits among Trae's own log prose, and other lines carry
        # activity payloads with account-flavoured text. Only the numbers ride.
        root = self._logs(("s1", "window1/renderer.log", [
            '[CheckinCredits] invalidation reconciled {"secret":"NEEDLE-IN-PROSE"}',
            BALANCE + "  trailing prose NEEDLE-TRAILING",
        ]))
        sync.scan_credit_logs(self.conn, cfg(), root)
        self.conn.commit()
        stored = self.stored_text()
        self.assertIn("balance", stored)
        for needle in ("NEEDLE-IN-PROSE", "NEEDLE-TRAILING", "CheckinCredits"):
            self.assertNotIn(needle, stored, "%s was stored" % needle)

    def test_main_log_is_walked_too(self):
        root = self._logs(("s1", "main.log", [BALANCE]))
        self.assertEqual(sync.scan_credit_logs(self.conn, cfg(), root), 1)

    def test_an_unknown_usage_event_and_a_missing_stamp_are_both_counted(self):
        root = self._logs(("s1", "window1/renderer.log", [
            '2026-10-07T08:55:51+08:00 [info] [ICubeUsageService] newBehaviour {"x":1}',
            '[ICubeUsageService] no leading timestamp here',
        ]))
        sync.scan_credit_logs(self.conn, cfg(), root)
        self.conn.commit()
        reasons = {r["reason"] for r in db.q_unparsed(self.conn)}
        self.assertIn("credit_log:event_shape", reasons)
        self.assertIn("credit_log:bad_timestamp", reasons)

    def test_an_unchanged_log_is_not_re_read_and_appends_resume_at_the_offset(self):
        root = self._logs(("s1", "window1/renderer.log", [BALANCE]))
        first = sync.scan_credit_logs(self.conn, cfg(), root)
        self.conn.commit()
        path = root / "s1" / "window1" / "renderer.log"
        self.assertEqual(sync.scan_credit_logs(self.conn, cfg(), root), 0,
                         "the cursor did not mark the file as consumed")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(SKIPPED + "\n")
        second = sync.scan_credit_logs(self.conn, cfg(), root)
        self.conn.commit()
        self.assertEqual((first, second), (1, 1))
        self.assertEqual(self.one("SELECT COUNT(*) c FROM credit_events")["c"], 2)

    def test_a_line_without_its_newline_waits_for_the_next_run(self):
        root = self._logs(("s1", "window1/renderer.log", ["noise"]))
        path = root / "s1" / "window1" / "renderer.log"
        path.write_text("noise\n" + BALANCE, encoding="utf-8")   # no trailing \n
        sync.scan_credit_logs(self.conn, cfg(), root)
        self.conn.commit()
        self.assertEqual(self.one("SELECT COUNT(*) c FROM credit_events")["c"], 0,
                         "a tail with no newline was consumed anyway")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n")
        sync.scan_credit_logs(self.conn, cfg(), root)
        self.conn.commit()
        self.assertEqual(self.one("SELECT COUNT(*) c FROM credit_events")["c"], 1,
                         "the line lost its chance to be indexed")


class FinalizeTest(Base):
    def test_counts_and_project_path_are_derived_from_the_rest(self):
        # A summary for a project key, plus a workspace.json that knows the real path.
        proj = self.tmp / "memory" / "projects" / "-home-user--local-share-x--p2-a" / "20260304"
        proj.mkdir(parents=True)
        (proj / "session_memory_abc123.jsonl").write_text(
            json.dumps({"intent": "i", "outcome": "o"}) + "\n", encoding="utf-8")
        sync.scan_session_memory(self.conn, cfg(), self.tmp / "memory" / "projects")
        # Two turns and one toolcall for the same session.
        git = self.tmp / "snapshot" / "abc123" / "v2" / ".git"
        (git / "refs" / "tags").mkdir(parents=True)
        for tag, ts in (("after-chat-turn-1", 1700000000),
                        ("after-chat-turn-2", 1700000005),
                        ("toolcall-m-c", 1700000002)):
            sha = "%040x" % abs(hash(tag))
            ref = git / "refs" / "tags" / tag
            ref.write_text(sha + "\n", encoding="ascii")
            obj = git / "objects" / sha[:2] / sha[2:]
            obj.parent.mkdir(parents=True, exist_ok=True)
            obj.write_bytes(_commit_obj(ts))
        sync.scan_snapshots(self.conn, cfg(), self.tmp / "snapshot")
        # A workspace that resolves the lossy key back to a real, dotted path.
        self.conn.execute(
            "INSERT INTO workspaces(workspace, folder) VALUES(?,?)",
            ("ws", "/home/user/.local/share/x"))
        sync.finalize(self.conn)

        s = self.one("SELECT * FROM sessions WHERE session_id='abc123'")
        self.assertEqual(s["turns"], 2)
        self.assertEqual(s["toolcalls"], 1)
        self.assertEqual(s["first_ts"], 1700000000 * 1000)
        self.assertEqual(s["last_ts"], 1700000005 * 1000)
        self.assertEqual(s["project"], "/home/user/.local/share/x",
                         "workspace.json did not resolve the lossy project key")

    def test_a_day_directory_is_a_day_not_a_measured_time(self):
        """The folder name must not fill ``first_ts``/``last_ts``.

        The day's midnight was written into the two *measured* columns, so a guess
        printed without the ``~`` marker, never counted as unmeasured, and a
        session whose summary moved to another day folder kept its first guess —
        which then fell outside the window of the day it actually belonged to.
        """
        proj = self.tmp / "memory" / "projects" / "-p--p2-a" / "20260304"
        proj.mkdir(parents=True)
        (proj / "session_memory_abc123.jsonl").write_text(
            json.dumps({"intent": "i"}) + "\n", encoding="utf-8")
        sync.scan_session_memory(self.conn, cfg(), self.tmp / "memory" / "projects")
        sync.finalize(self.conn)
        self.conn.commit()

        s = self.one("SELECT * FROM sessions WHERE session_id='abc123'")
        self.assertEqual(s["day"], "20260304", "the day belongs in the day column")
        self.assertIsNone(s["first_ts"],
                          "the day folder's midnight was stored as a measurement")
        self.assertIsNone(s["last_ts"],
                          "the day folder's midnight was stored as a measurement")
        row = db.q_sessions(self.conn)[0]
        self.assertEqual(row["derived_ts"], 1,
                         "a session with no measurement was not marked as derived")
        self.assertEqual(db.q_kpi(self.conn)["unmeasured"], 1,
                         "the session was not counted among the unmeasured")

    def test_a_summary_that_moves_to_another_day_follows_its_day(self):
        """``day`` follows the folder; nothing else was ever measured, so nothing
        else changes — and the new day's window can place the session."""
        root = self.tmp / "memory" / "projects"
        first = root / "-p--p2-a" / "20260304"
        first.mkdir(parents=True)
        path = first / "session_memory_abc123.jsonl"
        path.write_text(json.dumps({"intent": "i"}) + "\n", encoding="utf-8")
        sync.scan_session_memory(self.conn, cfg(), root)
        second = root / "-p--p2-a" / "20260305"
        second.mkdir()
        path.rename(second / path.name)
        sync.scan_session_memory(self.conn, cfg(), root)
        sync.finalize(self.conn)
        self.conn.commit()
        s = self.one("SELECT * FROM sessions WHERE session_id='abc123'")
        self.assertEqual(s["day"], "20260305")
        self.assertIsNone(s["last_ts"])

    def test_a_session_with_no_tags_keeps_zero_counts(self):
        proj = self.tmp / "memory" / "projects" / "-p--p2-a" / "20260304"
        proj.mkdir(parents=True)
        (proj / "session_memory_abc123.jsonl").write_text(
            json.dumps({"intent": "i"}) + "\n", encoding="utf-8")
        sync.scan_session_memory(self.conn, cfg(), self.tmp / "memory" / "projects")
        sync.finalize(self.conn)
        s = self.one("SELECT * FROM sessions WHERE session_id='abc123'")
        self.assertEqual(s["turns"], 0)
        self.assertEqual(s["toolcalls"], 0)


# --- 9. the store_content switch, end to end -------------------------------


class PurgeTest(Base):
    def test_turning_content_off_removes_prose_that_was_already_stored(self):
        """A switch that only affects *future* indexing reads as "still there"."""
        proj = self.tmp / "memory" / "projects" / "-p--p2-a" / "20260304"
        proj.mkdir(parents=True)
        (proj / "session_memory_abc123.jsonl").write_text(
            json.dumps({"intent": "secret", "outcome": "secret",
                        "actions": ["secret"], "learned": ["secret"]}) + "\n",
            encoding="utf-8")
        (proj / "topics.md").write_text(
            "[session_id: abc123 | topic_summary_time: 2026-03-04] secret\n",
            encoding="utf-8")
        sync.scan_session_memory(self.conn, cfg(), self.tmp / "memory" / "projects")
        sync.scan_topics(self.conn, cfg(), self.tmp / "memory" / "projects")
        (self.tmp / "memory" / "user_profile.md").write_text("secret\n", encoding="utf-8")
        sync.scan_memory_docs(self.conn, cfg(), self.tmp / "memory")
        self.conn.commit()
        self.assertTrue(self.one("SELECT intent FROM sessions WHERE session_id='abc123'")["intent"])

        sync._purge_content(self.conn)
        self.conn.commit()
        s = self.one("SELECT * FROM sessions WHERE session_id='abc123'")
        self.assertIsNotNone(s, "purge must not delete the session itself")
        self.assertIsNone(s["intent"])
        self.assertIsNone(s["outcome"])
        self.assertIsNone(self.one("SELECT summary FROM topics")["summary"])
        for table in ("session_actions", "session_learned", "prompts", "memory"):
            self.assertEqual(self.one(f"SELECT COUNT(*) c FROM {table}")["c"], 0,
                             f"{table} still holds prose after purge")


# --- 10. the driver --------------------------------------------------------


class RunTest(Base):
    """``run()`` with the roots overridden — the shape a caller (and the TUI) reads."""

    def _fixtures(self):
        proj = self.tmp / "memory" / "projects" / "-p--p2-a" / "20260304"
        proj.mkdir(parents=True)
        (proj / "session_memory_abc123.jsonl").write_text(
            json.dumps({"intent": "i"}) + "\n", encoding="utf-8")
        (proj / "topics.md").write_text(
            "[session_id: abc123 | topic_summary_time: 2026-03-04] t\n", encoding="utf-8")
        (self.tmp / "memory" / "user_profile.md").write_text("para\n", encoding="utf-8")
        git = self.tmp / "snapshot" / "abc123" / "v2" / ".git"
        (git / "refs" / "tags").mkdir(parents=True)
        sha = "b" * 40
        (git / "refs" / "tags" / "after-chat-turn-1").write_text(sha + "\n", encoding="ascii")
        obj = git / "objects" / sha[:2] / sha[2:]
        obj.parent.mkdir(parents=True, exist_ok=True)
        obj.write_bytes(_commit_obj(1700000000))
        return {
            "memory_projects": self.tmp / "memory" / "projects",
            "memory": self.tmp / "memory",
            "snapshot": self.tmp / "snapshot",
        }

    def test_run_returns_a_summary_with_a_result_per_source(self):
        roots = self._fixtures()
        conn = db.open_db(self.tmp / "run.db")
        try:
            summary = sync.run(db_path=self.tmp / "run.db", quiet=True,
                               roots={**roots})
        finally:
            conn.close()
        self.assertIn("results", summary)
        for label in ("session memory", "topics", "memory docs", "snapshots"):
            self.assertIn(label, summary["results"])
        self.assertEqual(summary["results"]["session memory"], 1)
        self.assertEqual(summary["results"]["topics"], 1)
        self.assertEqual(summary["results"]["snapshots"], 1)
        self.assertEqual(summary["overview"]["sessions"], 1)
        self.assertEqual(summary["overview"]["turns"], 1)
        self.assertEqual(summary["overview"]["projects"], 1)

    def test_a_second_run_indexes_nothing_new(self):
        roots = self._fixtures()
        sync.run(db_path=self.tmp / "run.db", quiet=True, roots=roots)
        second = sync.run(db_path=self.tmp / "run.db", quiet=True, roots=roots)
        self.assertEqual(sum(second["results"].values()), 0,
                         f"an idempotent re-run still reported work: {second['results']}")


if __name__ == "__main__":
    unittest.main()
