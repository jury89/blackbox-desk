import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
import tempfile
from pathlib import Path
import threading
import time
import unittest
from unittest import mock

from PySide6.QtWidgets import QApplication

from blackboxdesk import files, msp
from blackboxdesk.app import Window
from blackboxdesk.backend import DemoBackend
from blackboxdesk.models import Cancelled


class FastListingTests(unittest.TestCase):
    def setUp(self):
        self.backend = DemoBackend()
        self.addCleanup(self.backend.close)

    def test_17_logs_listed_without_opening_file_contents(self):
        root = self.backend.device.volume.root
        for n in range(1, 12):
            (root / "LOGS" / f"LOG{n:05d}.BFL").write_bytes(files.HEADER + b"flight")
        # 1..16, più il diciassettesimo: simula la quantità riportata dall'utente.
        (root / "LOGS" / "LOG00017.BFL").write_bytes(files.HEADER + b"flight")
        with mock.patch.object(Path, "open", side_effect=AssertionError("Lettura contenuto durante elenco")):
            session = self.backend.connect(self.backend.device)
        self.assertEqual(len(session.logs), 17)
        self.assertEqual(session.logs[0].number, 17)
        self.assertTrue(all(entry.recorded == "" for entry in session.logs))
        self.assertGreaterEqual(session.timings["Totale fino all'elenco"], session.timings["Elenco log"])

    def test_deferred_dates_can_cancel_before_second_log(self):
        session = self.backend.connect(self.backend.device)
        cancel = threading.Event()
        seen = []
        def emit(row, date, error):
            seen.append((row, date, error))
            cancel.set()
        with self.assertRaises(Cancelled):
            self.backend.read_dates(session, emit, cancel)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0], (0, "17/09/2026 10:16", ""))

    def test_refresh_preserves_dates_only_for_unchanged_files(self):
        session = self.backend.connect(self.backend.device)
        self.backend.read_dates(session, lambda row, date, error: session.logs.__setitem__(row, replace(session.logs[row], recorded=date)))
        changed = session.logs[0].path
        changed.write_bytes(files.HEADER + b"changed")
        with mock.patch.object(files, "recorded_date", side_effect=AssertionError("Nessuna lettura in refresh")):
            updated = self.backend.refresh(session)
        self.assertEqual(updated.logs[0].recorded, "")
        self.assertEqual(updated.logs[1].recorded, session.logs[1].recorded)

    def test_date_read_failure_does_not_lose_other_entries(self):
        session = self.backend.connect(self.backend.device)
        seen = []
        with mock.patch.object(files, "recorded_date", side_effect=[OSError("read error")] + ["—"] * 5):
            self.backend.read_dates(session, lambda *args: seen.append(args))
        self.assertEqual(len(seen), 6)
        self.assertIn("read error", seen[0][2])
        self.assertEqual(seen[1], (1, "—", ""))

    def test_small_msp_reply_never_waits_for_1024_bytes(self):
        packet = bytearray(msp.packet(msp.VARIANT, b"BTFL").replace(b"$M<", b"$M>"))
        sizes = []
        class Serial:
            @property
            def in_waiting(self):
                return len(packet)
            def write(self, data):
                return len(data)
            def read(self, size):
                sizes.append(size)
                assert size <= len(packet), "Attesa artificiale fino al timeout seriale"
                data = bytes(packet[:size])
                del packet[:size]
                return data
        connection = msp.MSP("test")
        connection.connection = Serial()
        self.assertEqual(connection.request(msp.VARIANT), b"BTFL")
        self.assertEqual(sizes, [10])


class DeferredDatesUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.backend = DemoBackend()
        self.window = Window(self.backend, demo=True, interactive=False)
        self.release = threading.Event()

    def tearDown(self):
        self.release.set()
        self.window.cancel_dates()
        self.window.pool.waitForDone(10000)
        self.application.processEvents()
        self.window.close()

    def wait_for(self, predicate):
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(.01)
        self.assertTrue(predicate())

    def test_rows_and_copy_available_before_dates_complete(self):
        entered = threading.Event()
        def slow_dates(session, emit, cancel):
            entered.set()
            self.release.wait(5)
            if not cancel.is_set():
                emit(0, "17/09/2026 10:16", "")
        with mock.patch.object(self.backend, "read_dates", side_effect=slow_dates):
            self.window.set_session(self.backend.connect(self.backend.device))
            self.assertTrue(entered.wait(2))
            self.assertEqual(self.window.table.rowCount(), 6)
            self.assertEqual(self.window.table.item(0, 1).text(), "…")
            self.assertTrue(self.window.copy_button.isEnabled())
            self.assertFalse(self.window.busy)
            self.release.set()
            self.wait_for(lambda: self.window.table.item(0, 1).text() == "17/09/2026 10:16")

    def test_copy_preempts_dates_and_stale_results_cannot_change_table(self):
        entered = threading.Event()
        stopped = threading.Event()
        def slow_dates(session, emit, cancel):
            entered.set()
            cancel.wait(5)
            stopped.set()
            emit(0, "STALE", "")
        with mock.patch.object(self.backend, "read_dates", side_effect=slow_dates):
            self.window.set_session(self.backend.connect(self.backend.device))
            self.assertTrue(entered.wait(2))
            self.window.copy_latest()
            self.wait_for(lambda: not self.window.busy)
        self.assertTrue(stopped.is_set())
        self.assertIsNone(self.window.session)  # espulsione automatica dopo copia
        self.assertTrue((self.window.destination / "LOG00016.BFL").is_file())

    def test_dates_do_not_reset_selection_and_old_generation_is_ignored(self):
        session = self.backend.connect(self.backend.device)
        with mock.patch.object(self.backend, "read_dates"):
            self.window.set_session(session)
            self.window.pool.waitForDone(10000)
        self.window.table.selectRow(3)
        generation = self.window.date_generation
        self.window.on_date(generation, 0, "17/09/2026 10:16", "")
        self.assertEqual(self.window.selected()[0].number, 13)
        self.window.cancel_dates()
        self.window.on_date(generation, 0, "STALE", "")
        self.assertEqual(self.window.table.item(0, 1).text(), "17/09/2026 10:16")


if __name__ == "__main__":
    unittest.main()
