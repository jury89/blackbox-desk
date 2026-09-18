"""Interfaccia desktop. Le operazioni USB e sui file lavorano fuori dal thread grafico."""

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
import threading
import uuid

from PySide6.QtCore import QMimeData, QObject, QRunnable, QSettings, QStandardPaths, Qt, QThreadPool, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QMainWindow, QMessageBox, QProgressBar, QPushButton, QSizePolicy,
    QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import __version__
from .backend import Backend, DemoBackend
from .models import AppError, Cancelled
from .layout import build_workspace
from . import local_files

LOG_MIME = "application/x-blackboxdesk-fc-logs"


STYLE = """
QWidget { color: #172B46; font-size: 13px; }
QMainWindow, QWidget#body { background: #FFFFFF; }
QFrame#fcPane { background: #F1F5FA; border-top: 1px solid #DCE4EF; }
QFrame#localPane { background: #FFFFFF; border-top: 1px solid #DCE4EF; }
QSplitter::handle { background: #DCE4EF; }
QSplitter::handle:hover { background: #8FAADD; }
QLabel#title { font-size: 22px; font-weight: 600; }
QLabel#paneTitle { font-size: 17px; font-weight: 600; }
QLabel#section { font-size: 15px; font-weight: 600; }
QLabel#muted { color: #62738B; }
QLabel#connection { font-size: 14px; font-weight: 600; }
QLabel#emptyTitle { font-size: 21px; font-weight: 500; }
QLabel#banner { background: #FFF1CA; color: #6C5100; padding: 9px 14px; }
QLabel#capability { color: #62738B; font-size: 12px; }
QPushButton { background: #FFFFFF; border: 1px solid #CBD6E5; border-radius: 6px; padding: 9px 13px; }
QPushButton:hover { border-color: #7C99C0; background: #F4F7FC; }
QPushButton:pressed { background: #E5EDF9; }
QPushButton:focus { border: 2px solid #245AD1; }
QPushButton:disabled { color: #98A5B7; border-color: #E1E6EE; background: #F3F5F8; }
QPushButton#primary { background: #245AD1; color: white; border-color: #245AD1; font-weight: 600; }
QPushButton#primary:hover { background: #194CB9; }
QPushButton#primary:disabled { background: #BBCBEA; color: #FFFFFF; border-color: #BBCBEA; }
QPushButton#danger { color: #B63D49; }
QPushButton#danger:disabled { color: #B1A4A7; }
QPushButton#small { padding: 5px 10px; font-size: 12px; }
QComboBox { background: white; border: 1px solid #CBD6E5; border-radius: 6px; padding: 8px; }
QComboBox QAbstractItemView { background: white; selection-background-color: #E6EEFC; }
QLineEdit { background: white; border: 1px solid #CBD6E5; border-radius: 5px; padding: 8px; }
QLineEdit:focus { border-color: #245AD1; }
QCheckBox { spacing: 8px; }
QTableWidget, QTreeView { background: #FFFFFF; alternate-background-color: #F7F9FC; border: 1px solid #DCE4EF; border-radius: 5px; gridline-color: transparent; selection-background-color: #DBE8FD; selection-color: #172B46; }
QTreeView[dropActive="true"] { border: 2px solid #245AD1; background: #EDF3FF; }
QHeaderView::section { background: #F1F5FA; color: #62738B; border: none; border-bottom: 1px solid #DCE4EF; padding: 10px 8px; font-size: 12px; }
QTableWidget::item { padding: 7px; border-bottom: 1px solid #EEF2F7; }
QTreeView::item { height: 36px; border-bottom: 1px solid #EEF2F7; }
QTreeView::item:selected { background: #DBE8FD; color: #172B46; }
QTreeView::item:selected:!active { background: #DBE8FD; color: #172B46; }
QTableWidget::item:focus { border: 1px solid #245AD1; }
QProgressBar { border: none; border-radius: 3px; background: #E9EFF7; height: 6px; }
QProgressBar::chunk { background: #245AD1; border-radius: 3px; }
QToolTip { background: #172B46; color: white; padding: 6px; }
"""


def app_icon(size=128):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#245AD1"))
    painter.drawRoundedRect(0, 0, size, size, size * 0.23, size * 0.23)
    path = QPainterPath()
    path.moveTo(size * 0.18, size * 0.61)
    path.lineTo(size * 0.36, size * 0.61)
    path.lineTo(size * 0.49, size * 0.32)
    path.lineTo(size * 0.61, size * 0.68)
    path.lineTo(size * 0.74, size * 0.47)
    path.lineTo(size * 0.83, size * 0.47)
    painter.setPen(QPen(QColor("white"), size * 0.055, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.drawPath(path)
    painter.end()
    return pixmap


def human_size(size):
    return f"{size / (1024 * 1024):.1f} MB" if size >= 1024 * 1024 else f"{size / 1024:.0f} KB"


class JobSignals(QObject):
    progress = Signal(str, int)
    done = Signal(object, object)


class Job(QRunnable):
    def __init__(self, function, cancel):
        super().__init__()
        self.function, self.cancel = function, cancel
        self.signals = JobSignals()

    def run(self):
        try:
            result = self.function(self.signals.progress.emit, self.cancel)
            self.signals.done.emit(result, None)
        except Exception as error:
            self.signals.done.emit(None, error)


class DateSignals(QObject):
    entry = Signal(int, int, str, str)
    failed = Signal(int, str)
    done = Signal(int)


class DateJob(QRunnable):
    def __init__(self, backend, session, generation, cancel):
        super().__init__()
        self.backend, self.session = backend, session
        self.generation, self.cancel = generation, cancel
        self.signals = DateSignals()

    def run(self):
        try:
            self.backend.read_dates(self.session,
                lambda row, date, error: self.signals.entry.emit(self.generation, row, date, error), self.cancel)
        except Cancelled:
            pass
        except Exception as error:
            self.signals.failed.emit(self.generation, str(error))
        finally:
            self.signals.done.emit(self.generation)


class Window(QMainWindow):
    def __init__(self, backend=None, demo=False, interactive=True):
        super().__init__()
        self.backend = backend or (DemoBackend() if demo else Backend())
        self.demo, self.interactive = demo, interactive
        self.session, self.busy, self.job = None, False, None
        self.cancel_event = threading.Event()
        self.close_after_job = False
        self.can_cancel = True
        self.date_generation, self.date_job = 0, None
        self.date_cancel = threading.Event()
        self.closing_dates = False
        self.connection_timings = {}
        self.drag_token = uuid.uuid4().hex
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.settings = QSettings("local.jury", "BlackboxDesk")
        default_dir = str(Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)) / "Blackbox")
        if isinstance(self.backend, DemoBackend):
            self.destination = self.backend.computer_root
        else:
            self.destination = Path(self.settings.value("destination", default_dir)) if interactive else Path(default_dir)
        self.copied_names = set()
        self.setWindowTitle("Betaflight Blackbox Desk" + (" — Demo" if demo else ""))
        self.setWindowIcon(QIcon(app_icon()))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(1220, 780)
        self.setMinimumSize(1040, 670)
        self.setStyleSheet(STYLE)
        self.build_ui()
        self.update_actions()

    def label(self, text, name="", wrap=False):
        label = QLabel(text)
        label.setObjectName(name)
        label.setWordWrap(wrap)
        return label

    def button(self, text, action, name=""):
        button = QPushButton(text)
        button.setObjectName(name)
        button.clicked.connect(action)
        return button

    def build_ui(self):
        build_workspace(self, app_icon)

    def selected(self):
        if not self.session:
            return []
        return [self.session.logs[row] for row in sorted({i.row() for i in self.table.selectionModel().selectedRows()})
                if row < len(self.session.logs)]

    def drag_mime(self):
        if self.busy or not self.session:
            return None
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        if not rows:
            return None
        mime = QMimeData()
        mime.setData(LOG_MIME, json.dumps({"session": self.drag_token, "rows": rows}).encode())
        return mime

    def entries_from_drag(self, mime, source):
        if self.busy or not self.session or source is not self.table or not mime.hasFormat(LOG_MIME):
            return []
        try:
            raw = bytes(mime.data(LOG_MIME))
            if len(raw) > 131072:
                return []
            data = json.loads(raw)
            rows = data.get("rows")
            if data.get("session") != self.drag_token or not isinstance(rows, list) or not rows:
                return []
            if any(type(row) is not int or not 0 <= row < len(self.session.logs) for row in rows):
                return []
            if len(set(rows)) != len(rows):
                return []
            return [self.session.logs[row] for row in sorted(rows)]
        except (ValueError, TypeError, AttributeError):
            return []

    def can_drop_logs(self, mime, source, destination):
        return bool(self.entries_from_drag(mime, source) and self.browser.destination_allowed(destination))

    def drop_logs(self, mime, source, destination):
        entries = self.entries_from_drag(mime, source)
        if not entries or not self.browser.destination_allowed(destination):
            return False
        if not self.browser.navigate(destination, allow_missing=True):
            return False
        self.copy_entries(entries)
        return True

    def destination_changed(self, path):
        self.destination = Path(path)
        self.save_preferences()

    @Slot()
    def update_actions(self, *_):
        if not hasattr(self, "copy_button"):
            return
        available = self.session is not None
        selected = self.selected() if available else []
        enabled = not self.busy
        self.scan_button.setEnabled(enabled and not available)
        self.connect_button.setEnabled(enabled and not available and self.device_combo.currentData() is not None)
        self.device_combo.setEnabled(enabled and not available)
        self.eject_button.setEnabled(enabled and available)
        device = self.device_combo.currentData()
        reset_possible = (available and (self.session.storage == "FLASH" or self.session.can_delete)) or (not available and device is not None and bool(device.port))
        self.reset_button.setEnabled(enabled and reset_possible)
        self.reset_button.setToolTip("Elimina tutti i log Blackbox dopo conferma. Per la FLASH serve la connessione USB normale.")
        self.refresh_button.setEnabled(enabled and available)
        self.latest_button.setEnabled(enabled and available and bool(self.session.logs))
        self.copy_button.setEnabled(enabled and bool(selected))
        self.delete_button.setEnabled(enabled and bool(selected) and self.session.can_delete)
        self.delete_button.setToolTip("Eliminazione definitiva, dopo conferma." if available and self.session.can_delete else "La cancellazione singola richiede una memoria SDCARD scrivibile.")
        self.all_button.setEnabled(enabled and available and bool(self.session.logs))
        self.none_button.setEnabled(enabled and available and bool(self.session.logs))
        self.browser.set_locked(not enabled)
        self.auto_eject.setEnabled(enabled)
        self.table.setEnabled(enabled)
        self.selection_label.setText(f"{len(selected)} selezionati · {human_size(sum(e.size for e in selected))}" if selected else "Nessun log selezionato")

    def start(self, function, success, cancellable=True):
        if self.busy:
            return
        self.cancel_dates()
        self.busy = True
        self.cancel_event = threading.Event()
        self.can_cancel = cancellable
        self.success_callback = success
        self.progress.setRange(0, 0)
        self.progress.show()
        self.cancel_button.setVisible(cancellable)
        self.update_actions()
        self.job = Job(function, self.cancel_event)
        self.job.signals.progress.connect(self.on_progress)
        self.job.signals.done.connect(self.on_done)
        self.pool.start(self.job)

    @Slot(str, int)
    def on_progress(self, message, percent):
        self.status.setText(message)
        self.progress.setRange(0, 0 if percent < 0 else 100)
        if percent >= 0:
            self.progress.setValue(percent)

    @Slot(object, object)
    def on_done(self, result, error):
        self.busy = False
        self.browser.set_locked(False)
        self.browser.refresh()
        self.progress.hide()
        self.cancel_button.hide()
        if error:
            self.status.setText(str(error))
            if self.interactive and not self.close_after_job and not isinstance(error, Cancelled):
                QMessageBox.warning(self, "Operazione non completata", str(error))
        else:
            self.success_callback(result)
        self.update_actions()
        if not self.busy and self.session and not self.close_after_job:
            self.start_dates()
        if self.close_after_job:
            self.close_after_job = False
            if error:
                if self.interactive:
                    QMessageBox.warning(self, "Memoria ancora collegata", str(error))
            else:
                self.session = None
                self.close()

    def scan(self):
        self.status.setText("Cerco FC e memorie USB…")
        self.start(lambda p, c: self.backend.discover(p, c), self.show_devices)

    def show_devices(self, devices):
        self.device_combo.clear()
        for device in devices:
            self.device_combo.addItem(device.label, device)
        if not devices:
            self.device_combo.addItem("Nessun dispositivo trovato", None)
        self.status.setText(f"{len(devices)} dispositivi trovati. Scegli la FC e premi Connetti." if devices else "Nessuna FC trovata. Collega un cavo USB dati e premi Cerca.")

    def connect_device(self):
        device = self.device_combo.currentData()
        if device:
            self.start(lambda p, c: self.backend.connect(device, p, c), self.set_session)

    def set_session(self, session):
        self.cancel_dates()
        self.session = session
        self.connection_timings = session.timings
        self.drag_token = uuid.uuid4().hex
        self.browser.source_root = session.volume.root.resolve()
        self.copied_names.clear()
        self.connection_title.setText(session.board)
        location = "File di esempio locali" if session.demo else str(session.volume.root)
        self.connection_detail.setText(f"{location} · {'SD / integrata' if session.storage == 'SDCARD' else session.storage}")
        self.total_label.setText(f"{len(session.logs)} log · {human_size(sum(e.size for e in session.logs))}")
        self.table.blockSignals(True)
        self.table.setRowCount(len(session.logs))
        for row, entry in enumerate(session.logs):
            for column, text in enumerate([entry.name, entry.recorded or "…", human_size(entry.size), "Ultimo" if row == 0 else "Disponibile"]):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                if column == 1 and not entry.recorded:
                    item.setToolTip("La data verrà letta in background. Puoi già copiare il log.")
                if column == 2:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if entry.extracted:
                    item.setToolTip("Volo individuato nel file complessivo della flash; verrà estratto durante la copia.")
                self.table.setItem(row, column, item)
        self.table.blockSignals(False)
        if session.logs:
            self.table.selectRow(0)
        self.stack.setCurrentIndex(0 if session.logs else 1)
        if not session.logs:
            self.empty_title.setText("La memoria non contiene log")
            self.empty_detail.setText("Dopo un volo registrato dalla Blackbox,\nricollega la FC e aggiorna l'elenco.")
        if session.can_delete:
            self.capability.setText("Puoi copiare i log o eliminarli dalla FC dopo conferma. La data è mostrata solo quando registrata nel log.")
        elif session.storage == "FLASH":
            self.capability.setText("Memoria flash: puoi copiare i log oppure usare Svuota memoria per eliminarli tutti. Non è possibile eliminarne uno solo.")
        else:
            self.capability.setText("Memoria di sola lettura: puoi copiare i log, ma non eliminarli da questa connessione.")
        duration = session.timings.get("Totale fino all'elenco")
        ready = f"Memoria pronta in {duration:.1f} s." if duration is not None else "Memoria pronta."
        self.status.setText(ready + " L'ultimo log è già selezionato.")
        self.update_actions()
        self.start_dates()

    def cancel_dates(self):
        self.date_cancel.set()
        self.date_generation += 1

    def start_dates(self):
        if self.busy or not self.session or self.closing_dates or not any(not entry.recorded for entry in self.session.logs):
            return
        if self.date_job is not None and not self.date_cancel.is_set():
            return
        self.cancel_dates()
        self.date_cancel = threading.Event()
        self.date_job = DateJob(self.backend, self.session, self.date_generation, self.date_cancel)
        self.date_job.signals.entry.connect(self.on_date)
        self.date_job.signals.failed.connect(self.on_dates_failed)
        self.date_job.signals.done.connect(self.on_dates_done)
        # Lo stesso worker della copia: nessun accesso USB in parallelo. Una nuova
        # operazione interrompe i metadati dopo la singola lettura già in corso.
        self.pool.start(self.date_job)

    @Slot(int, int, str, str)
    def on_date(self, generation, row, recorded, error):
        if generation != self.date_generation or not self.session or not 0 <= row < len(self.session.logs):
            return
        self.session.logs[row] = replace(self.session.logs[row], recorded=recorded)
        item = self.table.item(row, 1)
        item.setText(recorded)
        item.setToolTip(error or recorded)

    @Slot(int, str)
    def on_dates_failed(self, generation, error):
        if generation == self.date_generation and self.session:
            for row, entry in enumerate(self.session.logs):
                if not entry.recorded:
                    self.on_date(generation, row, "—", "Data non disponibile: " + error)

    @Slot(int)
    def on_dates_done(self, generation):
        if generation == self.date_generation:
            self.date_job = None

    def select_rows(self, checked):
        if checked:
            self.table.selectAll()
        else:
            self.table.clearSelection()
        self.update_actions()

    def refresh(self):
        if self.session:
            session = self.session
            self.start(lambda p, c: self.backend.refresh(session, p, c), self.set_session)

    def copy_latest(self):
        if self.session and self.session.logs:
            self.copy_entries([self.session.logs[0]])

    def copy_selected(self):
        self.copy_entries(self.selected())

    def copy_entries(self, entries):
        if not self.session or not entries:
            return
        session, destination, eject_after = self.session, self.destination, self.auto_eject.isChecked()
        self.start(lambda p, c: self.backend.copy(session, entries, destination, eject_after, p, c), self.copy_done)

    def copy_done(self, report):
        results = report["results"]
        if results:
            self.browser.navigate(results[0].path.parent)
        self.browser.refresh()
        reused = sum(result.reused for result in results)
        message = f"{len(results)} log verificati in {self.destination}."
        if reused:
            message += f" {reused} già presenti."
        if report["ejected"]:
            self.clear_session()
            message += " Memoria espulsa: puoi scollegare il cavo."
        elif report["eject_error"]:
            message += " Espulsione non riuscita: " + report["eject_error"]
        else:
            self.copied_names.update(result.entry.name for result in results)
            for row, entry in enumerate(self.session.logs):
                if entry.name in self.copied_names:
                    self.table.item(row, 3).setText("Copiato")
        self.status.setText(message)

    def delete_selected(self):
        entries = self.selected()
        if not entries or not self.session.can_delete:
            return
        names = "\n".join(entry.name for entry in entries[:12])
        if len(entries) > 12:
            names += f"\n… e altri {len(entries) - 12}"
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Elimina dalla FC")
        box.setText(f"Eliminare definitivamente {len(entries)} log dalla memoria della FC?")
        box.setInformativeText(names + "\n\nQuesta operazione non può essere annullata.")
        delete = box.addButton("Elimina dalla FC", QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton("Annulla", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.exec()
        if box.clickedButton() != delete:
            return
        session = self.session
        self.start(lambda p, c: self.backend.delete(session, entries, True, p, c), self.delete_done)

    def delete_done(self, report):
        self.set_session(report["session"])
        self.status.setText(f"Eliminati {len(report['deleted'])} log dalla FC.")

    def confirm_reset(self, details):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Svuota memoria Blackbox")
        box.setText("Eliminare definitivamente TUTTI i log della memoria indicata?")
        box.setInformativeText(details + "\n\nI log sulla FC verranno persi. Le copie sul computer rimangono disponibili. Questa operazione non può essere annullata.")
        erase = box.addButton("Svuota memoria", QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton("Annulla", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.exec()
        return box.clickedButton() == erase

    def reset_memory(self):
        if self.busy:
            return
        if self.session:
            if self.session.can_delete:
                session = self.session
                self.start(lambda p, c: self.backend.prepare_sd_reset(session, p, c), self.confirm_sd_reset)
            elif self.session.storage == "FLASH":
                box = QMessageBox(self)
                box.setWindowTitle("Svuota memoria FLASH")
                box.setText("Per svuotare la FLASH bisogna uscire dalla modalità disco USB.")
                box.setInformativeText("1. Premi Espelli e continua.\n2. Scollega tutte le alimentazioni della FC e ricollega solo USB.\n3. Premi Cerca, scegli la FC e premi Svuota memoria, prima di Connetti.\n\nLa conferma della cancellazione verrà chiesta dopo aver identificato la FC. Qui non viene ancora cancellato nulla.")
                proceed = box.addButton("Espelli e continua", QMessageBox.ButtonRole.AcceptRole)
                cancel = box.addButton("Annulla", QMessageBox.ButtonRole.RejectRole)
                box.setDefaultButton(cancel)
                box.exec()
                if box.clickedButton() == proceed:
                    session = self.session
                    self.start(lambda p, c: self.backend.eject(session, p, c), self.reset_reconnect)
            return
        device = self.device_combo.currentData()
        if device and device.port:
            self.start(lambda p, c: self.backend.prepare_flash_reset(device, p, c), self.confirm_flash_reset)

    def reset_reconnect(self, _):
        self.clear_session()
        self.status.setText("Memoria espulsa. Scollega tutte le alimentazioni e ricollega USB; premi Cerca, scegli la FC e poi Svuota memoria (prima di Connetti).")

    def confirm_sd_reset(self, plan):
        if not plan.entries:
            self.status.setText("La memoria non contiene file di log da eliminare.")
            return
        size = sum(entry[1] for entry in plan.entries)
        details = (f"{plan.session.board}\nMemoria: {plan.session.volume.label}\n{plan.session.volume.root}\n"
                   f"Tutti i {len(plan.entries)} file di log: {human_size(size)}.\n"
                   "Sono inclusi anche i log vuoti o incompleti. Eventuali file diversi dai log rimangono sulla memoria.")
        if self.confirm_reset(details):
            self.start(lambda p, c: self.backend.reset_sd(plan, True, p, c), self.reset_sd_done)
        else:
            self.status.setText("Svuotamento annullato. Nessun log eliminato.")

    def reset_sd_done(self, report):
        self.set_session(report["session"])
        self.status.setText(f"Memoria Blackbox svuotata: eliminati {report['deleted']} log e liberato il loro spazio.")

    def confirm_flash_reset(self, plan):
        details = (f"{plan.board} · Betaflight {plan.firmware}\nFC: {plan.device.port}\n"
                   f"Identificativo: {plan.uid}\nFLASH Blackbox: {human_size(plan.capacity)}; usati: {human_size(plan.used)}.\n"
                   "Verrà cancellata l'intera memoria Blackbox. Attendi il completamento mantenendo la FC collegata.")
        if self.confirm_reset(details):
            self.start(lambda p, c: self.backend.reset_flash(plan, True, p, c), self.reset_flash_done, cancellable=False)
        else:
            self.status.setText("Svuotamento annullato. Nessun comando di cancellazione inviato.")

    def reset_flash_done(self, state):
        self.status.setText(f"Memoria FLASH svuotata e verificata: {human_size(state['capacity'])} disponibili, 0 byte usati. Puoi premere Connetti per aprire la memoria.")

    def eject(self):
        if self.session:
            session = self.session
            self.start(lambda p, c: self.backend.eject(session, p, c), self.eject_done)

    def eject_done(self, _):
        self.clear_session()
        self.status.setText("Memoria espulsa. Per usarla di nuovo, scollega e ricollega il cavo USB, poi premi Cerca.")

    def clear_session(self):
        self.cancel_dates()
        self.drag_token = uuid.uuid4().hex
        self.browser.source_root = None
        self.session = None
        self.device_combo.clear()
        self.device_combo.addItem("Cerca una FC collegata", None)
        self.table.setRowCount(0)
        self.stack.setCurrentIndex(1)
        self.empty_title.setText("Memoria espulsa")
        self.empty_detail.setText("I log salvati sono nella cartella sul computer.\nScollega e ricollega il cavo USB, poi premi Cerca.")
        self.connection_title.setText("Memoria scollegata")
        self.connection_detail.setText("Scollega e ricollega USB per una nuova sessione.")
        self.total_label.setText("Nessuna memoria aperta")
        self.capability.setText("I log salvati sul computer rimangono disponibili.")

    def cancel(self):
        if not self.can_cancel:
            return
        self.cancel_event.set()
        self.status.setText("Annullo l'operazione in corso…")

    def choose_destination(self):
        self.browser.choose_folder()

    def local_error(self, error):
        self.status.setText(str(error))
        if self.interactive:
            QMessageBox.warning(self, "Operazione locale non completata", str(error))

    def create_local_folder(self):
        if self.busy or not self.browser.new_folder_button.isEnabled():
            return
        root, protected = self.browser.path, self.browser.source_root
        name, accepted = QInputDialog.getText(self, "Nuova cartella sul computer", f"Crea in: {root}\n\nNome della cartella:")
        if not accepted:
            return
        def created(path):
            self.browser.select_path(path)
            self.status.setText(f"Cartella creata: {path}")
        self.start(lambda p, c: local_files.create_folder(root, name, protected), created)

    def confirm_local_trash(self, plan):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Elimina dal computer")
        box.setTextFormat(Qt.TextFormat.PlainText)
        selection_text = "1 elemento" if len(plan.entries) == 1 else f"{len(plan.entries)} elementi"
        box.setText(f"Spostare {selection_text} nel Cestino?")
        names = "\n".join(entry.path.name for entry in plan.entries[:12])
        if len(plan.entries) > 12:
            names += f"\n… e altri {len(plan.entries) - 12} (vedi dettagli)"
        details = f"Cartella: {plan.root}\n\n{names}"
        if any(entry.is_directory for entry in plan.entries):
            details += "\n\nLe cartelle saranno spostate con TUTTO il contenuto, inclusi i file non mostrati nell'elenco."
        details += "\n\nPuoi recuperare gli elementi dal Cestino finché non viene svuotato."
        box.setInformativeText(details)
        box.setDetailedText("\n".join(str(entry.path) for entry in plan.entries))
        trash = box.addButton("Sposta nel Cestino", QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton("Annulla", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.setEscapeButton(cancel)
        box.exec()
        return box.clickedButton() is trash

    def trash_local_selected(self):
        if self.busy or not self.browser.trash_button.isEnabled():
            return
        protected = self.browser.source_root
        try:
            plan = local_files.plan_trash(self.browser.path, self.browser.selected_paths(), protected)
        except (OSError, ValueError, RuntimeError, AppError) as error:
            self.local_error(error)
            return
        if not self.confirm_local_trash(plan):
            return
        self.start(lambda p, c: local_files.trash_items(plan, protected, confirmed=True, progress=p, cancel=c),
                   lambda moved: self.status.setText(f"Spostati nel Cestino: {len(moved)}. Cartella: {plan.root}"))

    def save_preferences(self, *_):
        if self.interactive and not self.demo:
            self.settings.setValue("destination", str(self.destination))
            self.settings.setValue("auto_eject", self.auto_eject.isChecked())

    def open_destination(self):
        if self.destination.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.destination)))
        else:
            self.status.setText("La cartella verrà creata quando copierai il primo log.")

    def about(self):
        timing_text = ""
        if self.connection_timings:
            timing_text = "\n\nUltimo collegamento (date lette successivamente):\n" + "\n".join(
                f"{label}: {seconds:.2f} s" for label, seconds in self.connection_timings.items())
        QMessageBox.information(self, "Betaflight Blackbox Desk", f"Betaflight Blackbox Desk {__version__}\n\nFC Betaflight 4.3+ con Blackbox e USB Mass Storage.\nFLASH: copia e svuotamento completo tramite connessione USB normale.\nSDCARD scrivibile: copia, cancellazione singola e di tutti i log.\n\nLa versione Windows richiede una build e una verifica su Windows.\nNessun account, caricamento online o servizio in background.\n\nPython · PySide6 / Qt (LGPLv3) · pySerial{timing_text}")

    def closeEvent(self, event):
        if self.busy:
            if not self.can_cancel:
                self.status.setText("Svuotamento FLASH in corso: attendi il completamento e mantieni la FC collegata.")
                event.ignore()
                return
            self.cancel()
            self.status.setText("Annullo l'operazione. Attendi il termine prima di chiudere.")
            event.ignore()
            return
        if self.session and self.interactive and not self.closing_dates:
            answer = QMessageBox.question(self, "Chiudi Blackbox Desk", "Vuoi espellere la memoria della FC prima di chiudere?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Yes)
            if answer == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if answer == QMessageBox.StandardButton.Yes:
                self.close_after_job = True
                self.eject()
                event.ignore()
                return
        self.cancel_dates()
        if self.pool.activeThreadCount():
            self.closing_dates = True
            QTimer.singleShot(100, self.close)
            event.ignore()
            return
        if isinstance(self.backend, DemoBackend):
            self.backend.close()
        event.accept()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Betaflight Blackbox Desk")
    parser.add_argument("--demo", action="store_true", help="Usa file di esempio locali, senza dispositivi reali")
    parser.add_argument("--snapshot", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    application = QApplication.instance() or QApplication(sys.argv[:1])
    application.setApplicationName("Betaflight Blackbox Desk")
    application.setApplicationVersion(__version__)
    application.setFont(QFont("Helvetica Neue" if sys.platform == "darwin" else "Segoe UI", 11))
    window = Window(demo=args.demo or bool(args.snapshot), interactive=not (args.snapshot or args.smoke_test))
    window.show()
    if args.snapshot:
        window.show_devices(window.backend.discover())
        session = window.backend.connect(window.backend.device)
        window.set_session(session)
        snapshot_attempts = 0
        def snapshot():
            nonlocal snapshot_attempts
            snapshot_attempts += 1
            if window.browser.model.rowCount(window.browser.view.rootIndex()) < 3 and snapshot_attempts < 30:
                QTimer.singleShot(100, snapshot)
                return
            args.snapshot.parent.mkdir(parents=True, exist_ok=True)
            window.grab().save(str(args.snapshot))
            window.close()
            application.quit()
        QTimer.singleShot(250, snapshot)
    elif args.smoke_test:
        QTimer.singleShot(500, window.close)
        QTimer.singleShot(700, application.quit)
    else:
        QTimer.singleShot(100, window.scan)
    return application.exec()


if __name__ == "__main__":
    sys.exit(main())
