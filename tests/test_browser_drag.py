import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

from PySide6.QtCore import QCoreApplication, QEvent, QItemSelectionModel, QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtWidgets import QApplication

from blackboxdesk.app import LOG_MIME, Window
from blackboxdesk.backend import DemoBackend


class DropEvent:
    def __init__(self, mime, source, position=QPoint(5, 5), actions=None):
        self.mime, self.origin, self.point = mime, source, QPointF(position)
        self.actions = actions if actions is not None else Qt.DropAction.CopyAction | Qt.DropAction.MoveAction
        self.accepted, self.action = False, None

    def mimeData(self): return self.mime
    def source(self): return self.origin
    def position(self): return self.point
    def possibleActions(self): return self.actions
    def setDropAction(self, action): self.action = action
    def accept(self): self.accepted = True
    def ignore(self): self.accepted = False


class BrowserDragTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.backend = DemoBackend()
        self.window = Window(self.backend, demo=True, interactive=False)
        self.session = self.backend.connect(self.backend.device)
        self.window.set_session(self.session)
        self.window.auto_eject.setChecked(False)
        self.temp = tempfile.TemporaryDirectory()
        self.target = Path(self.temp.name).resolve()
        self.window.browser.navigate(self.target)
        self.window.show()
        self.application.processEvents()

    def tearDown(self):
        self.window.pool.waitForDone(10000)
        self.application.processEvents()
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.temp.cleanup()

    def wait_for(self, predicate):
        until = time.monotonic() + 5
        while not predicate() and time.monotonic() < until:
            self.application.processEvents()
            time.sleep(0.01)
        self.assertTrue(predicate())

    def select(self, rows):
        self.window.table.clearSelection()
        for row in rows:
            self.window.table.selectionModel().select(self.window.table.model().index(row, 0),
                QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)

    def drop_background(self, mime=None, source=None):
        view = self.window.browser.view
        event = DropEvent(mime or self.window.drag_mime(), source or self.window.table,
                          QPoint(10, view.viewport().height() - 10))
        view.dropEvent(event)
        return event

    def visible_names(self):
        browser = self.window.browser
        parent = browser.view.rootIndex()
        return [browser.model.fileName(browser.model.index(row, 0, parent))
                for row in range(browser.model.rowCount(parent))]

    def test_local_browser_shows_folders_first_and_only_logs_case_insensitive(self):
        (self.target / "Voli").mkdir()
        (self.target / "Z cartella.bbl").mkdir()
        (self.target / "note.txt").write_text("notes")
        (self.target / "manuale.PDF").write_bytes(b"pdf")
        (self.target / "backup.bfl.zip").write_bytes(b"zip")
        for name in ("flight.bbl", "a.BFL", "b.BbL", "c.bfl"):
            (self.target / name).write_bytes(b"flight")
        browser = self.window.browser
        expected = ["Voli", "Z cartella.bbl", "a.BFL", "b.BbL", "c.bfl", "flight.bbl"]
        browser.refresh()
        self.wait_for(lambda: self.visible_names() == expected)
        self.assertEqual(Path(browser.model.filePath(browser.view.rootIndex())), self.target)
        self.assertEqual(browser.count.text(), "2 folders · 4 Blackbox logs")
        self.assertTrue(browser.filesystem.isReadOnly())

    @unittest.skipUnless(sys.platform == "win32", "Windows hidden entries")
    def test_local_browser_hides_dot_files_and_folders(self):
        (self.target / ".private").mkdir()
        (self.target / ".hidden.bfl").write_bytes(b"flight")
        (self.target / "Voli").mkdir()
        (self.target / "shown.bfl").write_bytes(b"flight")
        browser = self.window.browser
        browser.refresh()
        self.wait_for(lambda: self.visible_names() == ["Voli", "shown.bfl"])
        self.assertEqual(browser.count.text(), "1 folder · 1 Blackbox log")

    def test_folders_stay_first_for_each_sort_column_and_direction(self):
        for name in ("Z folder", "A folder"):
            (self.target / name).mkdir()
        for name, size, timestamp in (("a.bbl", 100, 100000), ("b.bfl", 5, 200000)):
            path = self.target / name
            path.write_bytes(b"x" * size)
            os.utime(path, (timestamp, timestamp))
        self.window.browser.refresh()
        self.wait_for(lambda: len(self.visible_names()) == 4)
        browser = self.window.browser
        for column, ascending_logs in ((0, ["a.bbl", "b.bfl"]), (1, ["b.bfl", "a.bbl"]), (3, ["a.bbl", "b.bfl"])):
            for order in (Qt.SortOrder.AscendingOrder, Qt.SortOrder.DescendingOrder):
                with self.subTest(column=column, order=order):
                    browser.view.sortByColumn(column, order)
                    self.application.processEvents()
                    names = self.visible_names()
                    self.assertEqual(set(names[:2]), {"A folder", "Z folder"})
                    self.assertEqual(names[2:], ascending_logs if order == Qt.SortOrder.AscendingOrder else ascending_logs[::-1])
                    # Il drop deve usare la cartella mostrata, anche dopo l'ordinamento.
                    index = browser.model.index(0, 0, browser.view.rootIndex())
                    point = browser.view.visualRect(index).center()
                    self.assertEqual(browser.view.destination_at(point), self.target / names[0])

    def test_filtered_browser_updates_when_logs_appear_and_disappear(self):
        other = self.target / "notes.txt"
        other.write_text("notes")
        browser = self.window.browser
        browser.refresh()
        self.wait_for(lambda: browser.filesystem.index(str(other)).isValid())
        self.assertEqual(self.visible_names(), [])
        self.assertEqual(browser.count.text(), "0 folders · 0 Blackbox logs")
        log = self.target / "new.BFL"
        other.rename(log)
        browser.refresh()
        self.wait_for(lambda: self.visible_names() == ["new.BFL"])
        self.assertEqual(browser.count.text(), "0 folders · 1 Blackbox log")
        log.rename(other)
        browser.refresh()
        self.wait_for(lambda: self.visible_names() == [])
        self.assertEqual(browser.count.text(), "0 folders · 0 Blackbox logs")

    def test_double_click_folder_back_up_and_typed_path_change_destination(self):
        child = self.target / "Voli"
        child.mkdir()
        browser = self.window.browser
        self.wait_for(lambda: browser.model.path_index(child).isValid())
        browser.open_directory(browser.model.path_index(child))
        self.assertEqual(self.window.destination, child)
        browser.go_back()
        self.assertEqual(self.window.destination, self.target)
        browser.path_edit.setText(str(child))
        browser.path_edit.returnPressed.emit()
        self.assertEqual(self.window.destination, child)
        browser.up_button.click()
        self.assertEqual(self.window.destination, self.target)

    def test_invalid_path_does_not_change_destination(self):
        self.assertFalse(self.window.browser.navigate(self.target / "missing"))
        self.assertEqual(self.window.destination, self.target)

    def test_multiselect_drag_copies_and_keeps_fc_files(self):
        self.select([0, 2, 4])
        entries = self.window.selected()
        event = self.drop_background()
        self.assertTrue(event.accepted)
        self.assertEqual(event.action, Qt.DropAction.CopyAction)
        self.wait_for(lambda: not self.window.busy)
        self.assertEqual(len(list(self.target.glob("*.BFL"))), 3)
        for entry in entries:
            self.assertEqual((self.target / entry.name).read_bytes(), entry.path.read_bytes())
        self.assertEqual(len(self.session.logs), 6)
        self.window.browser.refresh()
        self.wait_for(lambda: len(self.visible_names()) == 3)

    def test_drop_on_subfolder_copies_inside_that_folder(self):
        folder = self.target / "Voli"
        folder.mkdir()
        browser = self.window.browser
        self.wait_for(lambda: browser.model.path_index(folder).isValid())
        self.application.processEvents()
        point = browser.view.visualRect(browser.model.path_index(folder)).center()
        self.assertEqual(browser.view.destination_at(point), folder)
        event = DropEvent(self.window.drag_mime(), self.window.table, point)
        browser.view.dropEvent(event)
        self.assertTrue(event.accepted)
        self.wait_for(lambda: not self.window.busy)
        self.assertTrue((folder / "LOG00016.BFL").is_file())
        self.assertEqual(self.window.destination, folder)
        self.assertFalse((self.target / "LOG00016.BFL").exists())

    def test_external_files_and_reverse_drag_are_rejected(self):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(self.target / "note.txt"))])
        incoming = DropEvent(mime, self.window.browser.view)
        self.window.table.dragEnterEvent(incoming)
        self.window.table.dropEvent(incoming)
        self.assertFalse(incoming.accepted)
        self.assertFalse(self.window.table.acceptDrops())
        self.assertFalse(self.window.browser.view.dragEnabled())
        self.window.browser.view.dropEvent(incoming)
        self.assertFalse(incoming.accepted)
        self.assertFalse(self.window.busy)

    def test_drag_uses_internal_ids_and_offers_copy_only(self):
        mime = self.window.drag_mime()
        self.assertFalse(mime.hasUrls())
        with mock.patch("blackboxdesk.browser.QDrag") as drag:
            self.window.table.startDrag(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction)
        drag.return_value.exec.assert_called_once_with(Qt.DropAction.CopyAction, Qt.DropAction.CopyAction)

    def test_stale_and_forged_drag_cannot_start_transfer(self):
        mime = self.window.drag_mime()
        self.assertFalse(self.window.can_drop_logs(mime, None, self.target))
        self.window.set_session(self.session)
        self.assertFalse(self.window.can_drop_logs(mime, self.window.table, self.target))
        for rows in [[-1], [100], [True], [0, 0], []]:
            mime.setData(LOG_MIME, json.dumps({"session": self.window.drag_token, "rows": rows}).encode())
            self.assertFalse(self.window.drop_logs(mime, self.window.table, self.target))
        self.assertFalse(self.window.busy)

    def test_drop_into_fc_or_symlink_to_fc_is_rejected(self):
        mime = self.window.drag_mime()
        self.assertFalse(self.window.can_drop_logs(mime, self.window.table, self.session.volume.root))
        self.assertFalse(self.window.browser.navigate(self.session.volume.root))
        if os.name != "nt":
            alias = self.target / "alias FC"
            alias.symlink_to(self.session.volume.root, target_is_directory=True)
            self.assertFalse(self.window.can_drop_logs(mime, self.window.table, alias))

    def test_drag_with_only_move_action_is_rejected(self):
        event = DropEvent(self.window.drag_mime(), self.window.table, actions=Qt.DropAction.MoveAction)
        self.window.browser.view.dropEvent(event)
        self.assertFalse(event.accepted)

    def test_transfer_locks_navigation_and_blocks_another_drop(self):
        self.window.busy = True
        self.window.update_actions()
        self.assertFalse(self.window.browser.navigate(self.target.parent))
        self.assertFalse(self.window.browser.path_edit.isEnabled())
        self.assertIsNone(self.window.drag_mime())
        self.window.busy = False
        self.window.update_actions()

    def test_drop_into_missing_default_folder_creates_and_lists_it(self):
        target = self.target / "Blackbox nuova"
        self.window.browser.navigate(target, allow_missing=True)
        self.assertIsNone(self.window.browser.view.model())
        event = self.drop_background()
        self.assertTrue(event.accepted)
        self.wait_for(lambda: not self.window.busy)
        self.assertTrue((target / "LOG00016.BFL").exists())
        self.wait_for(lambda: self.window.browser.model.path_index(target / "LOG00016.BFL").isValid())

    def test_drag_respects_auto_eject_and_copied_file_stays_visible(self):
        self.window.auto_eject.setChecked(True)
        event = self.drop_background()
        self.assertTrue(event.accepted)
        self.wait_for(lambda: not self.window.busy)
        self.assertIsNone(self.window.session)
        self.assertTrue((self.target / "LOG00016.BFL").is_file())
        self.assertEqual(self.window.browser.path, self.target)
