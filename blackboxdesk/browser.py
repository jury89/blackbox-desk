"""Liste file native e drag interno, esclusivamente in direzione FC → computer."""

from pathlib import Path

from PySide6.QtCore import QCollator, QDir, QItemSelectionModel, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QFileSystemModel, QHeaderView, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTreeView, QVBoxLayout, QWidget,
)


class FCLogTable(QTableWidget):
    def __init__(self, owner):
        super().__init__(0, 4)
        self.owner = owner
        self.setSelectionBehavior(self.SelectionBehavior.SelectRows)
        self.setSelectionMode(self.SelectionMode.ExtendedSelection)
        self.setEditTriggers(self.EditTrigger.NoEditTriggers)
        self.setDragDropMode(self.DragDropMode.DragOnly)
        self.setDragEnabled(True)
        self.setAcceptDrops(False)
        self.viewport().setAcceptDrops(False)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setAccessibleName("Log presenti sulla flight controller")

    def startDrag(self, supported_actions):
        mime = self.owner.drag_mime()
        if mime is None:
            return
        drag = QDrag(self)
        drag.setMimeData(mime)
        # Nessun MoveAction: il completamento del drag non rimuove righe o log.
        drag.exec(Qt.DropAction.CopyAction, Qt.DropAction.CopyAction)

    def dragEnterEvent(self, event):
        event.ignore()

    def dragMoveEvent(self, event):
        event.ignore()

    def dropEvent(self, event):
        event.ignore()


class LocalFileModel(QFileSystemModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Icone leggere e costanti, senza interrogare servizi di anteprima
        # del sistema operativo per ogni file o cartella della destinazione.
        self.icons = {}
        for folder in (False, True):
            pixmap = QPixmap(20, 20)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            if folder:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#7599D4"))
                painter.drawRoundedRect(1, 3, 9, 6, 1.5, 1.5)
                painter.setBrush(QColor("#94B5E7"))
                painter.drawRoundedRect(1, 6, 18, 12, 2, 2)
            else:
                painter.setPen(QPen(QColor("#91A1B6"), 1))
                painter.setBrush(QColor("#FFFFFF"))
                painter.drawRoundedRect(4, 2, 12, 16, 1, 1)
                painter.drawLine(7, 8, 13, 8)
                painter.drawLine(7, 11, 13, 11)
                painter.drawLine(7, 14, 11, 14)
            painter.end()
            self.icons[folder] = QIcon(pixmap)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and index.column() == 0 and role == Qt.ItemDataRole.DecorationRole:
            return self.icons[self.isDir(index)]
        return super().data(index, role)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return ["Nome", "Dimensione", "Tipo", "Modificato"][section]
        return super().headerData(section, orientation, role)


class LocalLogFilterModel(QSortFilterProxyModel):
    """Cartelle navigabili sempre in cima, poi solo log Blackbox locali."""

    def __init__(self, source, parent=None):
        super().__init__(parent)
        self.collator = QCollator()
        self.collator.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.collator.setNumericMode(True)
        self.setSourceModel(source)

    def filterAcceptsRow(self, row, parent):
        source = self.sourceModel()
        index = source.index(row, 0, parent)
        return source.isDir(index) or Path(source.fileName(index)).suffix.casefold() in {".bbl", ".bfl"}

    def lessThan(self, left, right):
        source = self.sourceModel()
        left_dir, right_dir = source.isDir(left), source.isDir(right)
        if left_dir != right_dir:
            # Qt inverte il confronto in ordine decrescente: compensiamo solo
            # per i gruppi, così le cartelle restano davanti in entrambe le direzioni.
            return left_dir if self.sortOrder() == Qt.SortOrder.AscendingOrder else right_dir
        if left.column() == 1 and not left_dir:
            a, b = source.size(left), source.size(right)
            if a != b:
                return a < b
        if left.column() == 3:
            a, b = source.lastModified(left), source.lastModified(right)
            if a != b:
                return a < b
        return self.collator.compare(source.fileName(left), source.fileName(right)) < 0

    def path_index(self, path):
        return self.mapFromSource(self.sourceModel().index(str(path)))

    def filePath(self, index):
        return self.sourceModel().filePath(self.mapToSource(index))

    def fileName(self, index):
        return self.sourceModel().fileName(self.mapToSource(index))

    def isDir(self, index):
        return self.sourceModel().isDir(self.mapToSource(index))


class LocalFilesView(QTreeView):
    def __init__(self, browser):
        super().__init__()
        self.browser = browser
        self.setRootIsDecorated(False)
        self.setItemsExpandable(False)
        self.setUniformRowHeights(True)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(self.SelectionBehavior.SelectRows)
        self.setSelectionMode(self.SelectionMode.ExtendedSelection)
        self.setEditTriggers(self.EditTrigger.NoEditTriggers)
        self.setDragDropMode(self.DragDropMode.DropOnly)
        self.setDragEnabled(False)
        self.setAcceptDrops(True)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setDropIndicatorShown(False)
        self.setSortingEnabled(True)
        self.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.setAccessibleName("Cartelle e log Blackbox sul computer")

    def startDrag(self, supported_actions):
        return  # I file del computer non diventano mai sorgenti di un drag.

    def destination_at(self, point):
        index = self.indexAt(point)
        if self.model() is not None and index.isValid() and self.model().isDir(index):
            return Path(self.model().filePath(index))
        return self.browser.path

    def allowed(self, event):
        target = self.destination_at(event.position().toPoint())
        return bool(self.isEnabled() and event.possibleActions() & Qt.DropAction.CopyAction
                    and self.browser.allow_drop(event.mimeData(), event.source(), target))

    def highlight(self, active, target=None):
        if bool(self.property("dropActive")) != active:
            self.setProperty("dropActive", active)
            self.style().unpolish(self)
            self.style().polish(self)
            self.viewport().update()
        self.browser.hint.setText(f"Rilascia per copiare in «{target.name or target}»" if active and target else self.browser.default_hint)

    def dragEnterEvent(self, event):
        self.dragMoveEvent(event)

    def dragMoveEvent(self, event):
        if self.allowed(event):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            self.highlight(True, self.destination_at(event.position().toPoint()))
        else:
            event.ignore()
            self.highlight(False)

    def dragLeaveEvent(self, event):
        self.highlight(False)
        event.accept()

    def dropEvent(self, event):
        target = self.destination_at(event.position().toPoint())
        allowed = self.allowed(event)
        self.highlight(False)
        if allowed and self.browser.receive_drop(event.mimeData(), event.source(), target):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.model() is None or self.model().rowCount(self.rootIndex()) == 0:
            painter = QPainter(self.viewport())
            painter.setPen(QColor("#62738B"))
            painter.drawText(self.viewport().rect().adjusted(18, 20, -18, -20), Qt.AlignmentFlag.AlignCenter,
                             "Trascina qui i log della FC\noppure scegli un'altra cartella.")


class LocalBrowser(QWidget):
    path_changed = Signal(object)
    message = Signal(str)

    def __init__(self, path, allow_drop, receive_drop):
        super().__init__()
        self.path = Path(path).expanduser().resolve()
        self.history = []
        self.locked = False
        self.source_root = None
        self.allow_drop, self.receive_drop = allow_drop, receive_drop
        self.default_hint = "Doppio clic sulle cartelle per entrare. Rilascia i log qui o su una sottocartella."
        self.filesystem = LocalFileModel(self)
        self.filesystem.setReadOnly(True)
        self.filesystem.setOption(QFileSystemModel.Option.DontUseCustomDirectoryIcons, True)
        self.filesystem.setFilter(QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot)
        self.model = LocalLogFilterModel(self.filesystem, self)
        self.filesystem.directoryLoaded.connect(self.directory_loaded)
        self.model.rowsInserted.connect(self.update_count)
        self.model.rowsRemoved.connect(self.update_count)
        self.model.layoutChanged.connect(self.update_count)
        self.model.modelReset.connect(self.update_count)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        navigation = QHBoxLayout()
        self.back_button = QPushButton("←")
        self.back_button.setAccessibleName("Cartella precedente")
        self.back_button.setToolTip("Indietro")
        self.up_button = QPushButton("↑")
        self.up_button.setAccessibleName("Cartella superiore")
        self.up_button.setToolTip("Cartella superiore")
        for button in (self.back_button, self.up_button):
            button.setFixedWidth(36)
            navigation.addWidget(button)
        self.choose_button = QPushButton("Scegli…")
        self.refresh_button = QPushButton("Aggiorna")
        navigation.addWidget(self.choose_button)
        navigation.addStretch()
        navigation.addWidget(self.refresh_button)
        layout.addLayout(navigation)
        self.path_edit = QLineEdit(str(self.path))
        self.path_edit.setAccessibleName("Percorso della cartella sul computer")
        self.path_edit.setToolTip("Scrivi un percorso e premi Invio")
        self.path_edit.setMinimumWidth(0)
        layout.addWidget(self.path_edit)
        self.count = QLabel()
        self.count.setObjectName("muted")
        self.count.setMinimumHeight(34)
        self.count.setWordWrap(True)
        actions = QHBoxLayout()
        actions.addWidget(self.count, 1)
        self.new_folder_button = QPushButton("Nuova cartella…")
        self.new_folder_button.setToolTip("Crea una sottocartella nella cartella corrente")
        self.trash_button = QPushButton("Elimina…")
        self.trash_button.setObjectName("danger")
        self.trash_button.setToolTip("Sposta gli elementi locali selezionati nel Cestino, dopo conferma")
        actions.addWidget(self.new_folder_button)
        actions.addWidget(self.trash_button)
        layout.addLayout(actions)
        self.view = LocalFilesView(self)
        layout.addWidget(self.view, 1)
        self.hint = QLabel(self.default_hint)
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)
        self.hint.setMinimumHeight(40)
        layout.addWidget(self.hint)
        self.back_button.clicked.connect(self.go_back)
        self.up_button.clicked.connect(lambda: self.navigate(self.path.parent))
        self.choose_button.clicked.connect(self.choose_folder)
        self.refresh_button.clicked.connect(self.refresh)
        self.path_edit.returnPressed.connect(lambda: self.navigate(Path(self.path_edit.text())))
        self.view.doubleClicked.connect(self.open_directory)
        self.refresh()

    def destination_allowed(self, path):
        try:
            target = Path(path).expanduser().resolve()
            return self.source_root is None or (target != self.source_root and self.source_root not in target.parents)
        except (OSError, RuntimeError):
            return False

    def navigate(self, path, remember=True, allow_missing=False):
        if self.locked:
            return False
        try:
            target = Path(path).expanduser().resolve()
            if not self.destination_allowed(target):
                raise ValueError("Scegli una cartella sul computer, fuori dalla memoria della FC.")
            if not target.is_dir() and not (allow_missing and not target.exists()):
                raise ValueError("La cartella non esiste o non è accessibile.")
        except (ValueError, OSError, RuntimeError) as error:
            self.path_edit.setText(str(self.path))
            self.message.emit(str(error))
            return False
        if remember and target != self.path:
            self.history.append(self.path)
        if target != self.path:
            self.view.clearSelection()
        self.path = target
        self.path_edit.setText(str(target))
        self.path_edit.setToolTip(str(target))
        self.refresh()
        self.path_changed.emit(target)
        return True

    def go_back(self):
        if self.history and not self.locked:
            target = self.history[-1]
            if self.navigate(target, remember=False, allow_missing=True):
                self.history.pop()
                self.set_locked(False)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Cartella sul computer", str(self.path if self.path.exists() else self.path.parent))
        if folder:
            self.navigate(folder)

    def open_directory(self, index):
        if self.view.model() is not None and self.model.isDir(index):
            self.navigate(Path(self.model.filePath(index)))

    def selected_paths(self):
        if self.view.model() is None:
            return []
        return [Path(self.model.filePath(index)) for index in self.view.selectionModel().selectedRows()
                if index.parent() == self.view.rootIndex()]

    def select_path(self, path):
        index = self.model.path_index(path)
        if index.isValid() and index.parent() == self.view.rootIndex():
            self.view.selectionModel().setCurrentIndex(index,
                QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)
            self.view.scrollTo(index)
            self.view.setFocus()

    def update_local_actions(self, *_):
        available = not self.locked and self.path.is_dir() and self.destination_allowed(self.path)
        self.new_folder_button.setEnabled(available)
        selected = self.selected_paths()
        self.trash_button.setEnabled(available and bool(selected))
        selection_text = "1 elemento selezionato sul computer" if len(selected) == 1 else f"{len(selected)} elementi selezionati sul computer"
        self.hint.setText(selection_text if selected else self.default_hint)

    def refresh(self):
        if self.path.is_dir():
            root_index = self.model.mapFromSource(self.filesystem.setRootPath(str(self.path)))
            if self.view.model() is not self.model:
                self.view.setModel(self.model)
                self.view.selectionModel().selectionChanged.connect(self.update_local_actions)
            self.view.setRootIndex(root_index)
            self.view.hideColumn(2)
            self.view.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            self.view.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
            self.view.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
            self.view.setColumnWidth(1, 88)
            self.view.setColumnWidth(3, 134)
        else:
            self.view.setModel(None)
        self.update_count()
        self.set_locked(self.locked)

    def directory_loaded(self, path):
        if Path(path).resolve() == self.path and self.view.model() is self.model:
            self.view.setRootIndex(self.model.path_index(self.path))
            self.update_count()

    def update_count(self, *_):
        if not hasattr(self, "view"):
            return
        if not self.path.exists():
            self.count.setText("La cartella verrà creata alla prima copia")
        else:
            parent = self.model.path_index(self.path)
            count = self.model.rowCount(parent) if parent.isValid() else 0
            folders = sum(self.model.isDir(self.model.index(row, 0, parent)) for row in range(count))
            folder_label = "cartella" if folders == 1 else "cartelle"
            self.count.setText(f"{folders} {folder_label} · {count - folders} log Blackbox")

    def set_locked(self, locked):
        self.locked = locked
        self.back_button.setEnabled(not locked and bool(self.history))
        self.up_button.setEnabled(not locked and self.path.parent != self.path)
        for widget in (self.choose_button, self.refresh_button, self.path_edit, self.view):
            widget.setEnabled(not locked)
        self.update_local_actions()
