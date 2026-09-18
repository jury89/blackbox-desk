import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from PySide6.QtCore import QItemSelectionModel, QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from blackboxdesk import local_files
from blackboxdesk.app import Window
from blackboxdesk.models import AppError, Cancelled


class LocalFilesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_create_folder_and_reject_collision_without_overwriting(self):
        path = local_files.create_folder(self.root, "Voli del weekend")
        self.assertTrue(path.is_dir())
        (path / "keep.txt").write_text("keep")
        with self.assertRaises(AppError):
            local_files.create_folder(self.root, path.name)
        self.assertEqual((path / "keep.txt").read_text(), "keep")

    def test_invalid_folder_names_cannot_escape_current_directory(self):
        for name in ("", ".", "..", "../outside", "/tmp/outside", "a/b", "a\\b", "a:", "a\0b", " trailing ", "end.", "CON", "nul.txt"):
            with self.subTest(name=name), self.assertRaises(AppError):
                local_files.create_folder(self.root, name)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_missing_directory_and_fc_directory_cannot_be_created_in(self):
        with self.assertRaises(AppError):
            local_files.create_folder(self.root / "missing", "test")
        for method in (lambda: local_files.create_folder(self.root, "test", self.root),
                       lambda: local_files.plan_trash(self.root, [], self.root)):
            with self.assertRaises(AppError):
                method()

    def test_trash_file_and_nonempty_folder_preserves_other_files(self):
        current = self.root / "current"
        current.mkdir()
        trash = self.root / "fake-trash"
        trash.mkdir()
        folder = current / "Voli"
        folder.mkdir()
        (folder / "notes.txt").write_text("also included")
        log = current / "flight.bbl"
        log.write_bytes(b"log")
        keep = current / "keep.bfl"
        keep.write_bytes(b"keep")
        plan = local_files.plan_trash(current, [log, folder, log])
        with mock.patch.object(local_files, "move_to_trash", side_effect=lambda p: p.rename(trash / p.name)):
            moved = local_files.trash_items(plan, confirmed=True)
        self.assertEqual(moved, [log, folder])
        self.assertFalse(folder.exists())
        self.assertEqual((trash / "Voli" / "notes.txt").read_text(), "also included")
        self.assertEqual(keep.read_bytes(), b"keep")

    def test_no_confirmation_no_trash_call(self):
        log = self.root / "test.bfl"
        log.touch()
        plan = local_files.plan_trash(self.root, [log])
        with mock.patch.object(local_files, "move_to_trash") as move:
            with self.assertRaises(AppError):
                local_files.trash_items(plan)
        move.assert_not_called()
        self.assertTrue(log.exists())

    def test_trash_rejects_outside_current_directory_fc_and_ancestors(self):
        fc = self.root / "fc"
        fc.mkdir()
        for selected, protected in ((self.root.parent, None), (self.root, None), (fc, fc), (fc, fc / "logs")):
            with self.subTest(selected=selected, protected=protected), self.assertRaises(AppError):
                local_files.plan_trash(self.root, [selected], protected)
        if os.name != "nt":
            alias = self.root / "alias-fc"
            alias.symlink_to(fc, target_is_directory=True)
            with self.assertRaises(AppError):
                local_files.plan_trash(self.root, [alias], fc)

    def test_changed_selection_after_confirmation_is_rejected_before_any_move(self):
        a, b = self.root / "a.bfl", self.root / "b.bbl"
        a.touch()
        b.touch()
        plan = local_files.plan_trash(self.root, [a, b])
        b.write_bytes(b"changed")
        with mock.patch.object(local_files, "move_to_trash") as move:
            with self.assertRaises(AppError):
                local_files.trash_items(plan, confirmed=True)
        move.assert_not_called()
        self.assertTrue(a.exists())

    def test_changed_parent_is_rejected(self):
        root = self.root / "current"
        root.mkdir()
        log = root / "a.bfl"
        log.touch()
        plan = local_files.plan_trash(root, [log])
        root.rename(self.root / "old")
        root.mkdir()
        log.touch()
        with mock.patch.object(local_files, "move_to_trash") as move:
            with self.assertRaises(AppError):
                local_files.trash_items(plan, confirmed=True)
        move.assert_not_called()

    def test_trash_failure_never_permanently_deletes(self):
        path = self.root / "keep.bfl"
        path.write_text("keep")
        with mock.patch.object(local_files, "QFile") as file:
            file.return_value.moveToTrash.return_value = False
            file.return_value.errorString.return_value = "Access denied"
            with self.assertRaisesRegex(AppError, "non è stato eliminato definitivamente"):
                local_files.move_to_trash(path)
            file.assert_called_once_with(str(path))
            file.return_value.remove.assert_not_called()
        self.assertEqual(path.read_text(), "keep")

    def test_partial_failure_and_cancel_report_completed_count(self):
        a, b = self.root / "a.bfl", self.root / "b.bfl"
        a.touch()
        b.touch()
        plan = local_files.plan_trash(self.root, [a, b])
        with mock.patch.object(local_files, "move_to_trash", side_effect=[None, AppError("locked")]):
            with self.assertRaisesRegex(AppError, "1 di 2"):
                local_files.trash_items(plan, confirmed=True)
        cancel = threading.Event()
        cancel.set()
        with mock.patch.object(local_files, "move_to_trash") as move:
            with self.assertRaisesRegex(Cancelled, "0 elementi"):
                local_files.trash_items(plan, confirmed=True, cancel=cancel)
        move.assert_not_called()

    @unittest.skipIf(os.name == "nt", "symlink richiede privilegi specifici su Windows")
    def test_symlink_is_passed_to_trash_without_resolving_target(self):
        target = self.root / "target.bfl"
        target.write_text("keep")
        link = self.root / "link.bfl"
        link.symlink_to(target)
        plan = local_files.plan_trash(self.root, [link])
        with mock.patch.object(local_files, "move_to_trash") as move:
            local_files.trash_items(plan, confirmed=True)
        move.assert_called_once_with(link)
        self.assertEqual(target.read_text(), "keep")


class LocalActionsUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = Window(demo=True, interactive=False)
        self.window.show()
        self.browser = self.window.browser
        self.root = self.browser.path
        self.wait_for(lambda: self.browser.model.rowCount(self.browser.view.rootIndex()) == 3)

    def tearDown(self):
        self.window.pool.waitForDone(10000)
        self.application.processEvents()
        self.window.close()

    def wait_for(self, predicate):
        until = time.monotonic() + 5
        while not predicate() and time.monotonic() < until:
            self.application.processEvents()
            time.sleep(.01)
        self.assertTrue(predicate())

    def click_row(self, row, modifiers=Qt.KeyboardModifier.NoModifier):
        index = self.browser.model.index(row, 0, self.browser.view.rootIndex())
        QTest.mouseClick(self.browser.view.viewport(), Qt.MouseButton.LeftButton, modifiers,
                         self.browser.view.visualRect(index).center())
        self.application.processEvents()
        return index

    def test_single_click_visible_selection_and_multi_selection(self):
        view = self.browser.view
        index = self.browser.model.index(0, 0, view.rootIndex())
        rectangle = view.visualRect(index)
        point = QPoint(rectangle.right() - 8, rectangle.center().y())
        before = view.viewport().grab().toImage().pixelColor(point)
        self.click_row(0)
        self.assertEqual(len(self.browser.selected_paths()), 1)
        self.assertEqual(self.browser.path, self.root)
        selected = view.viewport().grab().toImage().pixelColor(point)
        self.assertNotEqual(before, selected)
        self.browser.path_edit.setFocus()
        self.application.processEvents()
        inactive = view.viewport().grab().toImage().pixelColor(point)
        self.assertNotEqual(inactive, before)
        self.assertGreater(inactive.blue() - inactive.red(), 15)
        self.assertEqual(len(self.browser.selected_paths()), 1)
        self.assertTrue(self.browser.trash_button.isEnabled())
        self.click_row(2, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(len(self.browser.selected_paths()), 2)
        self.assertFalse(view.dragEnabled())

    def test_create_folder_from_button_cancel_and_success(self):
        with mock.patch("blackboxdesk.app.QInputDialog.getText", return_value=("Cancelled", False)):
            self.browser.new_folder_button.click()
        self.assertFalse((self.root / "Cancelled").exists())
        with mock.patch("blackboxdesk.app.QInputDialog.getText", return_value=("Nuovi voli", True)):
            self.browser.new_folder_button.click()
            self.wait_for(lambda: not self.window.busy)
        self.assertTrue((self.root / "Nuovi voli").is_dir())
        self.wait_for(lambda: self.browser.model.path_index(self.root / "Nuovi voli").isValid())
        self.assertEqual(self.browser.selected_paths(), [self.root / "Nuovi voli"])

    def test_local_confirm_cancel_is_default_and_mentions_all_folder_contents(self):
        self.click_row(0)
        observed = []
        def cancel_dialog():
            dialog = self.application.activeModalWidget()
            observed.append((dialog.defaultButton().text(), dialog.informativeText(), dialog.detailedText()))
            dialog.reject()
        QTimer.singleShot(0, cancel_dialog)
        with mock.patch.object(local_files, "move_to_trash") as move:
            self.browser.trash_button.click()
        move.assert_not_called()
        self.assertEqual(observed[0][0], "Annulla")
        self.assertIn("TUTTO il contenuto", observed[0][1])
        self.assertIn(str(self.root), observed[0][2])

    def test_confirmed_local_trash_updates_list_without_changing_fc(self):
        self.window.set_session(self.window.backend.connect(self.window.backend.device))
        self.click_row(2)
        path = self.browser.selected_paths()[0]
        fake_trash = self.window.backend.computer_root.parent / "Trash test"
        fake_trash.mkdir()
        with mock.patch.object(self.window, "confirm_local_trash", return_value=True), \
             mock.patch.object(local_files, "move_to_trash", side_effect=lambda p: p.rename(fake_trash / p.name)):
            self.browser.trash_button.click()
            self.wait_for(lambda: not self.window.busy)
        self.assertFalse(path.exists())
        self.wait_for(lambda: self.browser.model.rowCount(self.browser.view.rootIndex()) == 2)
        self.assertFalse(self.browser.trash_button.isEnabled())
        self.assertEqual(len(self.window.session.logs), 6)
        self.assertIn("Spostati nel Cestino: 1.", self.window.status.text())

    def test_navigation_clears_local_selection_and_busy_blocks_mutations(self):
        self.click_row(0)
        folder = self.browser.selected_paths()[0]
        self.browser.navigate(folder)
        self.assertEqual(self.browser.selected_paths(), [])
        self.assertFalse(self.browser.trash_button.isEnabled())
        self.window.busy = True
        self.window.update_actions()
        self.assertFalse(self.browser.new_folder_button.isEnabled())
        with mock.patch("blackboxdesk.app.QInputDialog.getText") as dialog:
            self.window.create_local_folder()
        dialog.assert_not_called()
        self.window.busy = False


if __name__ == "__main__":
    unittest.main()
