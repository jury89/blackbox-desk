import os
from pathlib import Path
import stat
import tempfile
import threading
import unittest
from unittest import mock

from blackboxdesk import files
from blackboxdesk.models import AppError, Cancelled, Session, Volume


class FileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.fc = self.root / "FC"
        (self.fc / "LOGS").mkdir(parents=True)
        self.output = self.root / "saved"
        self.volume = Volume(self.fc, "FC", "test", "test", False)

    def tearDown(self):
        self.temp.cleanup()

    def log(self, name="LOG00016.BFL", body=b"flight", folder=None):
        path = (folder or self.fc / "LOGS") / name
        path.write_bytes(files.HEADER + b"H Log start datetime:2026-09-17T10:00:00Z\n" + body)
        return path

    def entry(self, **kwargs):
        return files.make_entry(self.log(**kwargs), 16)

    def test_numeric_order_and_actual_log_date(self):
        self.log("LOG00009.BFL")
        newest = self.log("log00101.bfl")
        os.utime(newest, (1, 1))
        kind, entries = files.scan_logs(self.fc)
        self.assertEqual(kind, "SDCARD")
        self.assertEqual([entry.number for entry in entries], [101, 9])
        self.assertEqual(entries[0].recorded, "17/09/2026 10:00")

    def test_source_date_not_inferred_from_filesystem(self):
        path = self.log()
        path.write_bytes(files.HEADER + b"data")
        self.assertEqual(files.recorded_date(path), "—")

    def test_no_logs_is_valid_empty_sd_session(self):
        self.assertEqual(files.scan_logs(self.fc), ("SDCARD", []))

    def test_conflicting_storage_hint_refused(self):
        self.log()
        with self.assertRaises(AppError):
            files.scan_logs(self.fc, "FLASH")

    def test_mixed_sd_flash_refused(self):
        self.log()
        self.log("BTFL_001.BBL", folder=self.fc)
        with self.assertRaises(AppError):
            files.scan_logs(self.fc)

    def test_virtual_flash_more_than_100_flights(self):
        self.log("BTFL_100.BBL", folder=self.fc)
        combined = self.fc / "BTFL_ALL.BBL"
        parts = [(files.HEADER + str(n).encode()).ljust(2048, b"\xff") for n in range(110)]
        combined.write_bytes(b"".join(parts))
        kind, entries = files.scan_logs(self.fc)
        self.assertEqual(kind, "FLASH")
        self.assertEqual(len(entries), 110)
        self.assertEqual(entries[0].number, 110)
        result = files.copy_log(self.fc, entries[0], self.output)
        self.assertEqual(result.path.read_bytes(), parts[-1])
        self.assertEqual(result.path.name, "FLIGHT_00110.BBL")

    def test_combined_header_crosses_read_boundary(self):
        combined = self.fc / "BTFL_ALL.BBL"
        combined.write_bytes(files.HEADER.ljust(2048, b"\xff") + files.HEADER + b"X" * (files.BLOCK + 80))
        entries = files.split_flash(combined, lambda *_: None, None)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[1].offset, 2048)

    def test_capped_flash_without_combined_refused(self):
        self.log("BTFL_100.BBL", folder=self.fc)
        with self.assertRaises(AppError):
            files.scan_logs(self.fc)

    def test_original_name_and_identical_repeat(self):
        entry = self.entry()
        result = files.copy_log(self.fc, entry, self.output)
        repeat = files.copy_log(self.fc, entry, self.output)
        self.assertEqual(result.path.name, "LOG00016.BFL")
        self.assertEqual(result.path.read_bytes(), entry.path.read_bytes())
        self.assertTrue(repeat.reused)
        self.assertEqual(len(list(self.output.iterdir())), 1)

    def test_different_same_name_gets_numbered(self):
        first = files.copy_log(self.fc, self.entry(body=b"one"), self.output)
        second = files.copy_log(self.fc, self.entry(body=b"two"), self.output)
        self.assertEqual(second.path.name, "LOG00016_2.BFL")
        self.assertNotEqual(first.path.read_bytes(), second.path.read_bytes())

    def test_changed_source_refused(self):
        entry = self.entry()
        entry.path.write_bytes(files.HEADER + b"changed")
        with self.assertRaisesRegex(AppError, "changed"):
            files.copy_log(self.fc, entry, self.output)

    def test_invalid_header_refused(self):
        path = self.log()
        path.write_bytes(b"X" * 100)
        with self.assertRaisesRegex(AppError, "header"):
            files.copy_log(self.fc, files.make_entry(path, 16), self.output)

    def test_destination_inside_fc_refused(self):
        with self.assertRaisesRegex(AppError, "outside"):
            files.copy_log(self.fc, self.entry(), self.fc / "copy")

    def test_cancelled_copy_leaves_no_partial(self):
        entry = self.entry(body=b"X" * (files.BLOCK * 2))
        cancel = threading.Event()
        def progress(*_):
            cancel.set()
        with self.assertRaises(Cancelled):
            files.copy_log(self.fc, entry, self.output, progress, cancel)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_checksum_failure_not_published(self):
        with mock.patch.object(files, "digest_file", return_value="bad"):
            with self.assertRaises(AppError):
                files.copy_log(self.fc, self.entry(), self.output)
        self.assertEqual(list(self.output.iterdir()), [])

    @unittest.skipUnless(hasattr(os, "chflags"), "macOS flags")
    def test_locked_source_copied_without_unlocking_source(self):
        entry = self.entry()
        os.chmod(entry.path, 0o400)
        os.chflags(entry.path, stat.UF_IMMUTABLE)
        try:
            result = files.copy_log(self.fc, entry, self.output)
            self.assertTrue(entry.path.stat().st_flags & stat.UF_IMMUTABLE)
            self.assertFalse(result.path.stat().st_flags & stat.UF_IMMUTABLE)
            self.assertTrue(result.path.stat().st_mode & stat.S_IWUSR)
        finally:
            os.chflags(entry.path, 0)

    @unittest.skipUnless(hasattr(os, "chflags"), "macOS flags")
    def test_existing_copy_unlocked(self):
        entry = self.entry()
        result = files.copy_log(self.fc, entry, self.output)
        os.chflags(result.path, stat.UF_IMMUTABLE)
        try:
            repeat = files.copy_log(self.fc, entry, self.output)
            self.assertTrue(repeat.reused)
            self.assertFalse(repeat.path.stat().st_flags & stat.UF_IMMUTABLE)
        finally:
            os.chflags(result.path, 0)

    @unittest.skipUnless(hasattr(os, "chflags") and hasattr(stat, "UF_HIDDEN"), "macOS hidden flag")
    def test_existing_hidden_copy_is_made_visible_when_reused(self):
        entry = self.entry()
        result = files.copy_log(self.fc, entry, self.output)
        os.chflags(result.path, result.path.stat().st_flags | stat.UF_HIDDEN)
        repeat = files.copy_log(self.fc, entry, self.output)
        self.assertTrue(repeat.reused)
        self.assertFalse(repeat.path.stat().st_flags & stat.UF_HIDDEN)
        self.assertEqual(repeat.path.read_bytes(), entry.path.read_bytes())
        self.assertEqual(list(self.output.iterdir()), [result.path])

    @unittest.skipUnless(hasattr(os, "chflags") and hasattr(stat, "UF_HIDDEN"), "macOS hidden flag")
    def test_new_copy_visible_after_temporary_file_cleanup(self):
        entry = self.entry()
        original_unlink = Path.unlink
        # macOS/file providers can mark an inode hidden while its temporary
        # dot-name exists, even after the final hard link has been created.
        def unlink_with_hidden_inode(path, *args, **kwargs):
            if path.name.startswith(".blackbox-"):
                os.chflags(path, path.stat().st_flags | stat.UF_HIDDEN)
            return original_unlink(path, *args, **kwargs)
        with mock.patch.object(Path, "unlink", unlink_with_hidden_inode):
            result = files.copy_log(self.fc, entry, self.output)
        self.assertFalse(result.reused)
        self.assertFalse(result.path.stat().st_flags & stat.UF_HIDDEN)
        self.assertEqual(result.path.read_bytes(), entry.path.read_bytes())
        self.assertEqual(list(self.output.iterdir()), [result.path])

    def test_delete_requires_confirmation(self):
        entry = self.entry()
        with self.assertRaises(AppError):
            files.delete_logs(Session(self.volume, "FC", "SDCARD"), [entry])
        self.assertTrue(entry.path.exists())

    def test_delete_only_selected(self):
        entry = self.entry()
        other = self.log("LOG00017.BFL")
        deleted = files.delete_logs(Session(self.volume, "FC", "SDCARD"), [entry], True)
        self.assertEqual(deleted, [entry.name])
        self.assertFalse(entry.path.exists())
        self.assertTrue(other.exists())

    def test_delete_flash_readonly_and_duplicate_selection_refused(self):
        entry = self.entry()
        for session, entries in [
            (Session(self.volume, "FC", "FLASH"), [entry]),
            (Session(Volume(self.fc, "FC", "d", "i", True), "FC", "SDCARD"), [entry]),
            (Session(self.volume, "FC", "SDCARD"), [entry, entry]),
        ]:
            with self.subTest(session=session, entries=len(entries)):
                with self.assertRaises(AppError):
                    files.delete_logs(session, entries, True)
        self.assertTrue(entry.path.exists())

    def test_delete_prevalidates_entire_selection(self):
        first = self.entry()
        second = files.make_entry(self.log("LOG00017.BFL"), 17)
        second.path.write_bytes(b"changed")
        with self.assertRaises(AppError):
            files.delete_logs(Session(self.volume, "FC", "SDCARD"), [first, second], True)
        self.assertTrue(first.path.exists())

    def test_delete_outside_root_refused(self):
        outside = self.log("LOG00017.BFL", folder=self.root)
        entry = files.make_entry(outside, 17)
        with self.assertRaises(AppError):
            files.delete_logs(Session(self.volume, "FC", "SDCARD"), [entry], True)
        self.assertTrue(outside.exists())

    @unittest.skipIf(os.name == "nt", "Windows symlink privilege may be unavailable")
    def test_symlink_not_deleted(self):
        entry = self.entry()
        original = entry.path.read_bytes()
        entry.path.unlink()
        target = self.root / "other"
        target.write_bytes(original)
        entry.path.symlink_to(target)
        with self.assertRaises(AppError):
            files.delete_logs(Session(self.volume, "FC", "SDCARD"), [entry], True)
        self.assertTrue(target.exists())


if __name__ == "__main__":
    unittest.main()
