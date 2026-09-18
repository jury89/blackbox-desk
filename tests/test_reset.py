import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import struct
import tempfile
import threading
import time
import unittest
from unittest import mock

from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from blackboxdesk import files, msp
from blackboxdesk.app import Window
from blackboxdesk.backend import Backend, DemoBackend
from blackboxdesk.models import AppError, Cancelled, Device, FlashResetPlan
from test_msp import FakeMSP


UID_BYTES = bytes(range(12))
UID_TEXT = UID_BYTES.hex().upper()
CAPACITY = 8 * 1024 * 1024


def summary(ready=True, used=4096):
    return struct.pack("<BIII", 3 if ready else 2, 128, CAPACITY, used)


class EraseMSP(FakeMSP):
    def __init__(self, states=None, changes=None):
        answers = {msp.BLACKBOX: b"\x01\x01", msp.UID: UID_BYTES, msp.FLASH_ERASE: b""}
        answers.update(changes or {})
        super().__init__(answers)
        self.states = iter(states or [summary(), summary(False, 0), summary(True, 0)])

    def request(self, command, payload=b"", timeout=3):
        if command == msp.FLASH_SUMMARY:
            self.calls.append((command, payload))
            return next(self.states)
        if command == msp.FLASH_ERASE and not self._erase_authorized:
            raise AssertionError("Erase senza autorizzazione interna")
        return super().request(command, payload, timeout)


class FlashEraseTests(unittest.TestCase):
    def assert_no_erase(self, connection):
        self.assertNotIn((msp.FLASH_ERASE, b""), connection.calls)

    def test_confirmation_required_before_any_command(self):
        connection = EraseMSP()
        with self.assertRaises(AppError):
            connection.erase_flash(UID_TEXT, CAPACITY)
        self.assertEqual(connection.calls, [])

    def test_wrong_fc_storage_armed_and_busy_are_refused(self):
        cases = [
            EraseMSP(changes={msp.UID: b"X" * 12}),
            EraseMSP(changes={msp.BLACKBOX: b"\x01\x02"}),
            EraseMSP(changes={msp.STATUS: b"\0" * 6 + b"\x01" + b"\0" * 8}),
            EraseMSP([summary(False)]),
        ]
        for connection in cases:
            with self.subTest(connection=connection):
                with self.assertRaises(AppError):
                    connection.erase_flash(UID_TEXT, CAPACITY, True)
                self.assert_no_erase(connection)

    def test_capacity_change_and_cancel_before_erase_refused(self):
        connection = EraseMSP()
        with self.assertRaises(AppError):
            connection.erase_flash(UID_TEXT, CAPACITY * 2, True)
        self.assert_no_erase(connection)
        connection = EraseMSP()
        connection.cancel = threading.Event()
        connection.cancel.set()
        with self.assertRaises(Cancelled):
            connection.erase_flash(UID_TEXT, CAPACITY, True)
        self.assert_no_erase(connection)

    def test_waits_for_ready_and_zero_used_then_reports_success(self):
        connection = EraseMSP([summary(), summary(False, 0), summary(True, 512), summary(True, 0)])
        with mock.patch.object(msp.time, "sleep"):
            result = connection.erase_flash(UID_TEXT, CAPACITY, True)
        self.assertEqual(result["used"], 0)
        self.assertTrue(result["ready"])
        self.assertEqual(connection.calls.count((msp.FLASH_ERASE, b"")), 1)
        self.assertFalse(connection._erase_authorized)

    def test_connection_loss_never_retries_erase_or_claims_success(self):
        connection = EraseMSP(changes={msp.FLASH_ERASE: TimeoutError("ack lost")})
        with self.assertRaisesRegex(AppError, "non verificato"):
            connection.erase_flash(UID_TEXT, CAPACITY, True)
        self.assertEqual(connection.calls.count((msp.FLASH_ERASE, b"")), 1)
        self.assertFalse(connection._erase_authorized)

    def test_erase_timeout_is_not_success(self):
        connection = EraseMSP()
        with mock.patch.object(msp.time, "monotonic", side_effect=[0, 601]):
            with self.assertRaisesRegex(AppError, "non verificato"):
                connection.erase_flash(UID_TEXT, CAPACITY, True)

    def test_cancel_after_send_does_not_interrupt_hardware_monitoring(self):
        connection = EraseMSP()
        event = threading.Event()
        connection.cancel = event
        def progress(*_):
            event.set()
        with mock.patch.object(msp.time, "sleep"):
            result = connection.erase_flash(UID_TEXT, CAPACITY, True, progress)
        self.assertTrue(result["ready"])
        self.assertIs(connection.cancel, event)

    def test_bad_summary_and_uid_refused(self):
        for data in [b"bad", struct.pack("<BIII", 1, 128, CAPACITY, 0), struct.pack("<BIII", 3, 128, CAPACITY, CAPACITY + 1)]:
            with self.subTest(data=data), self.assertRaises(AppError):
                EraseMSP([data]).flash_summary()
        with self.assertRaises(AppError):
            EraseMSP(changes={msp.UID: b"\0" * 12}).uid()


class ResetBackendTests(unittest.TestCase):
    def setUp(self):
        self.backend = DemoBackend()
        self.session = self.backend.connect(self.backend.device)

    def tearDown(self):
        self.backend.close()

    def test_sd_unconfirmed_keeps_every_log(self):
        plan = self.backend.prepare_sd_reset(self.session)
        with self.assertRaises(AppError):
            self.backend.reset_sd(plan)
        self.assertEqual(len(files.sd_reset_entries(self.session)), 6)

    def test_sd_reset_clears_all_logs_including_incomplete_leaves_other_files(self):
        root = self.session.volume.root
        (root / "LOGS" / "LOG00099.BFL").write_bytes(b"")
        (root / "LOGS" / "LOG00100.BFL").write_bytes(b"incomplete")
        other = root / "settings.txt"
        other.write_text("keep")
        (root / ".Trashes").mkdir()
        trash = root / ".Trashes" / "LOG00001.BFL"
        trash.write_text("keep")
        plan = self.backend.prepare_sd_reset(self.session)
        result = self.backend.reset_sd(plan, True)
        self.assertEqual(result["deleted"], 8)
        self.assertEqual(result["session"].logs, [])
        self.assertEqual(other.read_text(), "keep")
        self.assertTrue(trash.exists())

    def test_changed_sd_listing_or_volume_aborts_before_deletion(self):
        plan = self.backend.prepare_sd_reset(self.session)
        (self.session.volume.root / "LOGS" / "LOG00099.BFL").write_bytes(b"new")
        with self.assertRaisesRegex(AppError, "cambiato"):
            self.backend.reset_sd(plan, True)
        self.assertEqual(len(files.sd_reset_entries(self.session)), 7)
        with mock.patch.object(self.backend.volumes, "validate", side_effect=AppError("replaced")):
            with self.assertRaises(AppError):
                self.backend.reset_sd(plan, True)
        self.assertEqual(len(files.sd_reset_entries(self.session)), 7)

    def test_sd_cancel_reports_partial_and_preserves_remaining(self):
        plan = self.backend.prepare_sd_reset(self.session)
        event = threading.Event()
        def progress(*_):
            event.set()
        with self.assertRaisesRegex(AppError, "eliminati 1 di 6"):
            self.backend.reset_sd(plan, True, progress, event)
        self.assertEqual(len(files.sd_reset_entries(self.session)), 5)

    def test_flash_preparation_only_reads_and_backend_requires_confirmation(self):
        factory = mock.MagicMock()
        connection = EraseMSP([summary()])
        factory.return_value.__enter__.return_value = connection
        backend = Backend(self.backend.volumes, factory)
        device = Device("serial", "Test FC", port="/test/serial")
        plan = backend.prepare_flash_reset(device)
        self.assertEqual(plan.uid, UID_TEXT)
        self.assertNotIn((msp.FLASH_ERASE, b""), connection.calls)
        factory.reset_mock()
        with self.assertRaises(AppError):
            backend.reset_flash(plan)
        factory.assert_not_called()

    def test_empty_flash_after_reset_is_a_valid_empty_session(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "BTFL_ALL.BBL").write_bytes(b"")
            self.assertEqual(files.scan_logs(root), ("FLASH", []))


class ResetUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.backend = DemoBackend()
        self.window = Window(self.backend, demo=True, interactive=False)
        self.window.set_session(self.backend.connect(self.backend.device))

    def tearDown(self):
        self.window.pool.waitForDone(10000)
        self.application.processEvents()
        self.window.busy = False
        self.window.close()

    def wait_job(self):
        until = time.monotonic() + 10
        while self.window.busy and time.monotonic() < until:
            self.application.processEvents()
            time.sleep(0.01)
        self.assertFalse(self.window.busy)

    def test_actual_confirmation_defaults_to_cancel_and_closing_is_cancel(self):
        default = []
        def close_dialog():
            dialog = self.application.activeModalWidget()
            default.append(dialog.defaultButton().text())
            dialog.reject()
        QTimer.singleShot(0, close_dialog)
        self.assertFalse(self.window.confirm_reset("Memoria di prova"))
        self.assertEqual(default, ["Annulla"])

    def test_sd_reset_dialog_cancel_preserves_files(self):
        with mock.patch.object(self.window, "confirm_reset", return_value=False) as confirm:
            self.window.reset_memory()
            self.wait_job()
        confirm.assert_called_once()
        self.assertEqual(len(self.window.session.logs), 6)

    def test_sd_reset_confirmation_updates_table(self):
        with mock.patch.object(self.window, "confirm_reset", return_value=True):
            self.window.reset_memory()
            self.wait_job()
        self.assertEqual(self.window.session.logs, [])
        self.assertEqual(self.window.table.rowCount(), 0)
        self.assertIn("svuotata", self.window.status.text())

    def test_flash_reset_cancel_never_calls_backend(self):
        plan = FlashResetPlan(Device("serial", "FC", port="/test"), "FC", "4.5", UID_TEXT, CAPACITY, 512)
        with mock.patch.object(self.window, "confirm_reset", return_value=False), mock.patch.object(self.backend, "reset_flash") as erase:
            self.window.confirm_flash_reset(plan)
        erase.assert_not_called()

    def test_hardware_erase_cannot_be_closed_or_cancelled_mid_operation(self):
        self.window.busy, self.window.can_cancel = True, False
        event = QCloseEvent()
        self.window.closeEvent(event)
        self.window.cancel()
        self.assertFalse(event.isAccepted())
        self.assertFalse(self.window.cancel_event.is_set())

    def test_reset_available_for_flash_and_selected_serial_without_logs(self):
        self.window.session.storage = "FLASH"
        self.window.update_actions()
        self.assertTrue(self.window.reset_button.isEnabled())
        self.window.clear_session()
        self.window.show_devices([Device("serial", "FC", port="/test")])
        self.window.update_actions()
        self.assertTrue(self.window.reset_button.isEnabled())
