import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication, QEvent, Qt

from blackboxdesk.app import Window
from blackboxdesk.backend import Backend, DemoBackend, DemoVolumes
from blackboxdesk.models import AppError, Cancelled, Device, Volume
from blackboxdesk.msp import Identity
from blackboxdesk import files


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.demo = DemoBackend()
        self.session = self.demo.connect(self.demo.device)
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)

    def tearDown(self):
        self.demo.close()
        self.temp.cleanup()

    def test_copy_multiple_then_eject(self):
        def eject(volume, cancel):
            self.assertEqual(len(list(self.output.glob("*.BFL"))), 2)
        with mock.patch.object(self.demo.volumes, "eject", side_effect=eject) as eject_mock:
            result = self.demo.copy(self.session, self.session.logs[:2], self.output)
        self.assertTrue(result["ejected"])
        self.assertEqual(len(result["results"]), 2)
        eject_mock.assert_called_once()

    def test_no_eject_option(self):
        with mock.patch.object(self.demo.volumes, "eject") as eject:
            self.demo.copy(self.session, self.session.logs[:1], self.output, False)
        eject.assert_not_called()

    def test_failed_copy_never_ejects(self):
        with mock.patch.object(files, "copy_log", side_effect=AppError("copy failed")), mock.patch.object(self.demo.volumes, "eject") as eject:
            with self.assertRaisesRegex(AppError, "Completed 0"):
                self.demo.copy(self.session, self.session.logs[:1], self.output)
        eject.assert_not_called()

    def test_failed_eject_preserves_verified_copy(self):
        with mock.patch.object(self.demo.volumes, "eject", side_effect=AppError("busy")):
            result = self.demo.copy(self.session, self.session.logs[:1], self.output)
        self.assertFalse(result["ejected"])
        self.assertEqual(result["eject_error"], "busy")
        self.assertTrue(result["results"][0].path.exists())

    def test_delete_confirmed_then_refresh(self):
        result = self.demo.delete(self.session, self.session.logs[:2], True)
        self.assertEqual(len(result["deleted"]), 2)
        self.assertEqual(len(result["session"].logs), 4)

    def test_device_changed_prevents_copy_and_delete(self):
        with mock.patch.object(self.demo.volumes, "validate", side_effect=AppError("changed")):
            with self.assertRaises(AppError):
                self.demo.copy(self.session, self.session.logs[:1], self.output)
            with self.assertRaises(AppError):
                self.demo.delete(self.session, self.session.logs[:1], True)

    def serial_backend(self, lists):
        volumes = mock.Mock()
        volumes.list.side_effect = lists
        factory = mock.MagicMock()
        connection = factory.return_value.__enter__.return_value
        connection.identify.return_value = Identity("ALTRA_FC_F405", "4.5.2", "SDCARD")
        return Backend(volumes, factory), connection

    def test_other_fc_connects_only_to_new_blackbox_volume(self):
        backend, connection = self.serial_backend([[], [self.session.volume]])
        result = backend.connect(Device("test", "FC", port="/test/serial"))
        self.assertIn("ALTRA_FC_F405", result.board)
        self.assertEqual(result.logs[0].name, "LOG00016.BFL")
        connection.reboot_storage.assert_called_once()

    def test_two_new_volumes_are_rejected(self):
        other = Volume(self.output, "USB estranea", "other", "other", False)
        backend, _ = self.serial_backend([[], [self.session.volume, other]])
        with self.assertRaisesRegex(AppError, "Multiple USB storage"):
            backend.connect(Device("test", "FC", port="/test/serial"))

    def test_unrelated_new_volume_is_rejected(self):
        other = Volume(self.output, "USB estranea", "other", "other", False)
        backend, _ = self.serial_backend([[], [other]])
        with self.assertRaisesRegex(AppError, "cannot be identified"):
            backend.connect(Device("test", "FC", port="/test/serial"))

    def test_cancel_after_partial_copy_reports_retained_files(self):
        cancel = threading.Event()
        original = files.copy_log
        def copy_then_cancel(*args, **kwargs):
            result = original(*args, **kwargs)
            cancel.set()
            return result
        with mock.patch.object(files, "copy_log", side_effect=copy_then_cancel), mock.patch.object(self.demo.volumes, "eject") as eject:
            with self.assertRaisesRegex(Cancelled, "Completed 1 of 2"):
                self.demo.copy(self.session, self.session.logs[:2], self.output, cancel=cancel)
        self.assertEqual(len(list(self.output.glob("*.BFL"))), 1)
        eject.assert_not_called()


class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.backend = DemoBackend()
        self.window = Window(self.backend, demo=True, interactive=False)
        self.window.set_session(self.backend.connect(self.backend.device))
        self.temp = tempfile.TemporaryDirectory()
        self.window.destination = Path(self.temp.name)

    def tearDown(self):
        self.window.pool.waitForDone(10000)
        self.application.processEvents()
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.temp.cleanup()

    def wait_job(self):
        deadline = time.monotonic() + 10
        while self.window.busy and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(0.01)
        self.assertFalse(self.window.busy)

    def test_table_and_latest_selection(self):
        self.assertEqual(self.window.table.rowCount(), 6)
        self.assertEqual(self.window.selected()[0].name, "LOG00016.BFL")
        self.assertTrue(self.window.copy_button.isEnabled())
        self.assertTrue(self.window.delete_button.isEnabled())

    def test_flash_disables_delete_but_allows_copy(self):
        self.window.session.storage = "FLASH"
        self.window.update_actions()
        self.assertFalse(self.window.delete_button.isEnabled())
        self.assertTrue(self.window.copy_button.isEnabled())

    def test_selection_controls(self):
        self.window.select_rows(True)
        self.assertEqual(len(self.window.selected()), 6)
        self.window.select_rows(False)
        self.assertEqual(self.window.selected(), [])
        self.assertFalse(self.window.copy_button.isEnabled())

    def test_background_copy_and_eject_updates_ui(self):
        self.window.copy_latest()
        self.assertTrue(self.window.busy)
        self.wait_job()
        self.assertIsNone(self.window.session)
        self.assertTrue((Path(self.temp.name) / "LOG00016.BFL").exists())
        self.assertIn("Storage ejected", self.window.status.text())

    def test_copy_keep_mounted_updates_row(self):
        self.window.auto_eject.setChecked(False)
        self.window.copy_latest()
        self.wait_job()
        self.assertIsNotNone(self.window.session)
        self.assertEqual(self.window.table.item(0, 3).text(), "Copied")

    def test_modal_style_is_applied_only_on_windows(self):
        self.assertEqual("QMessageBox { background: #FFFFFF; color: #172B46; }" in self.window.styleSheet(),
                         sys.platform == "win32")


if __name__ == "__main__":
    unittest.main()
