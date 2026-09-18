"""Operazioni esplicite sul computer: creazione e cestino, mai erase definitivo."""

from dataclasses import dataclass
from pathlib import Path
import re
import stat

from PySide6.QtCore import QFile

from .models import AppError, Cancelled


def directory(root, protected_root=None):
    root = Path(root)
    if root.resolve() != root or not root.is_dir():
        raise AppError("La cartella locale è cambiata o non è più disponibile. Aggiorna l'elenco.")
    if protected_root:
        protected = Path(protected_root).resolve()
        if root == protected or protected in root.parents:
            raise AppError("Questi comandi sono disponibili soltanto nel pannello Computer, fuori dalla memoria della FC.")
    return root


def create_folder(root, name, protected_root=None):
    root = directory(root, protected_root)
    # Un solo nome, portabile fra macOS e Windows; nessun percorso o sovrascrittura.
    if (not name or name in {".", ".."} or name != name.strip() or name.endswith(".")
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
            or re.fullmatch(r"(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", name)):
        raise AppError("Inserisci un nome di cartella valido, senza percorsi o caratteri speciali.")
    path = root / name
    try:
        path.mkdir()
    except FileExistsError as error:
        raise AppError(f"Esiste già un elemento chiamato «{name}». Scegli un altro nome.") from error
    except OSError as error:
        raise AppError(f"Non posso creare «{name}»: {error}") from error
    return path


@dataclass(frozen=True)
class TrashEntry:
    path: Path
    identity: tuple
    is_directory: bool


@dataclass(frozen=True)
class TrashPlan:
    root: Path
    root_identity: tuple
    entries: tuple[TrashEntry, ...]


def identity(path):
    info = path.lstat()
    return (info.st_dev, info.st_ino, info.st_mode, info.st_mtime_ns)


def validate_child(root, path, protected_root=None):
    if path.parent != root or path.name in {"", ".", ".."}:
        raise AppError("La selezione non appartiene alla cartella mostrata. Aggiorna l'elenco.")
    resolved = path.resolve()
    if path.is_mount():
        raise AppError("Non puoi spostare un volume nel Cestino.")
    if protected_root:
        protected = Path(protected_root).resolve()
        if resolved == protected or protected in resolved.parents or resolved in protected.parents:
            raise AppError("La selezione include la memoria della FC. Usa i comandi nel pannello Flight controller.")


def plan_trash(root, paths, protected_root=None):
    root = directory(root, protected_root)
    entries = []
    for path in dict.fromkeys(map(Path, paths)):
        validate_child(root, path, protected_root)
        info = identity(path)
        if not (stat.S_ISDIR(info[2]) or stat.S_ISREG(info[2]) or stat.S_ISLNK(info[2])):
            raise AppError("Puoi selezionare soltanto file e cartelle locali.")
        entries.append(TrashEntry(path, info, stat.S_ISDIR(info[2])))
    if not entries:
        raise AppError("Seleziona almeno un file o una cartella sul computer.")
    return TrashPlan(root, identity(root)[:2], tuple(entries))


def move_to_trash(path):
    file = QFile(str(path))
    if not file.moveToTrash():
        raise AppError(f"Impossibile spostare «{path.name}» nel Cestino: {file.errorString()}. Il file non è stato eliminato definitivamente.")


def trash_items(plan, protected_root=None, *, confirmed=False, progress=None, cancel=None):
    if not confirmed:
        raise AppError("Lo spostamento nel Cestino richiede conferma.")
    directory(plan.root, protected_root)
    if identity(plan.root)[:2] != plan.root_identity:
        raise AppError("La cartella è cambiata dopo la conferma. Aggiorna l'elenco.")
    # Valida tutta la selezione prima di iniziare; non seguire link quando si cestina.
    for entry in plan.entries:
        validate_child(plan.root, entry.path, protected_root)
        if identity(entry.path) != entry.identity:
            raise AppError(f"«{entry.path.name}» è cambiato dopo la conferma. Aggiorna l'elenco.")
    moved = []
    for entry in plan.entries:
        if cancel and cancel.is_set():
            raise Cancelled(f"Operazione annullata. {len(moved)} elementi già spostati nel Cestino.")
        try:
            directory(plan.root, protected_root)
            if identity(plan.root)[:2] != plan.root_identity or identity(entry.path) != entry.identity:
                raise AppError("La selezione è cambiata dopo la conferma.")
            validate_child(plan.root, entry.path, protected_root)
            if progress:
                progress(f"Sposto nel Cestino {entry.path.name}", int(100 * len(moved) / len(plan.entries)))
            move_to_trash(entry.path)
            moved.append(entry.path)
        except (OSError, AppError) as error:
            raise AppError(f"{len(moved)} di {len(plan.entries)} elementi spostati nel Cestino. {error}") from error
    return moved
