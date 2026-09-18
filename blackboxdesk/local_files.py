"""Explicit computer actions: create folders and use the Trash, never permanently erase."""

from dataclasses import dataclass
from pathlib import Path
import re
import stat

from PySide6.QtCore import QFile

from .models import AppError, Cancelled


def directory(root, protected_root=None):
    root = Path(root)
    if root.resolve() != root or not root.is_dir():
        raise AppError("The local folder changed or is no longer available. Refresh the list.")
    if protected_root:
        protected = Path(protected_root).resolve()
        if root == protected or protected in root.parents:
            raise AppError("These controls are available only in the Computer pane, outside flight controller storage.")
    return root


def create_folder(root, name, protected_root=None):
    root = directory(root, protected_root)
    # One name, portable between macOS and Windows; no paths or overwrites.
    if (not name or name in {".", ".."} or name != name.strip() or name.endswith(".")
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
            or re.fullmatch(r"(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", name)):
        raise AppError("Enter a valid folder name without paths or special characters.")
    path = root / name
    try:
        path.mkdir()
    except FileExistsError as error:
        raise AppError(f"An item named “{name}” already exists. Choose another name.") from error
    except OSError as error:
        raise AppError(f"Cannot create “{name}”: {error}") from error
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
        raise AppError("The selection does not belong to the displayed folder. Refresh the list.")
    resolved = path.resolve()
    if path.is_mount():
        raise AppError("You cannot move a volume to the Trash.")
    if protected_root:
        protected = Path(protected_root).resolve()
        if resolved == protected or protected in resolved.parents or resolved in protected.parents:
            raise AppError("The selection includes flight controller storage. Use the controls in the Flight controller pane.")


def plan_trash(root, paths, protected_root=None):
    root = directory(root, protected_root)
    entries = []
    for path in dict.fromkeys(map(Path, paths)):
        validate_child(root, path, protected_root)
        info = identity(path)
        if not (stat.S_ISDIR(info[2]) or stat.S_ISREG(info[2]) or stat.S_ISLNK(info[2])):
            raise AppError("You can select only local files and folders.")
        entries.append(TrashEntry(path, info, stat.S_ISDIR(info[2])))
    if not entries:
        raise AppError("Select at least one file or folder on the computer.")
    return TrashPlan(root, identity(root)[:2], tuple(entries))


def move_to_trash(path):
    file = QFile(str(path))
    if not file.moveToTrash():
        raise AppError(f"Cannot move “{path.name}” to the Trash: {file.errorString()}. The file was not permanently deleted.")


def trash_items(plan, protected_root=None, *, confirmed=False, progress=None, cancel=None):
    if not confirmed:
        raise AppError("Moving items to the Trash requires confirmation.")
    directory(plan.root, protected_root)
    if identity(plan.root)[:2] != plan.root_identity:
        raise AppError("The folder changed after confirmation. Refresh the list.")
    # Validate the entire selection before starting; do not follow links while trashing.
    for entry in plan.entries:
        validate_child(plan.root, entry.path, protected_root)
        if identity(entry.path) != entry.identity:
            raise AppError(f"“{entry.path.name}” changed after confirmation. Refresh the list.")
    moved = []
    for entry in plan.entries:
        if cancel and cancel.is_set():
            raise Cancelled(f"Operation cancelled. {len(moved)} items were already moved to the Trash.")
        try:
            directory(plan.root, protected_root)
            if identity(plan.root)[:2] != plan.root_identity or identity(entry.path) != entry.identity:
                raise AppError("The selection changed after confirmation.")
            validate_child(plan.root, entry.path, protected_root)
            if progress:
                progress(f"Moving to Trash {entry.path.name}", int(100 * len(moved) / len(plan.entries)))
            move_to_trash(entry.path)
            moved.append(entry.path)
        except (OSError, AppError) as error:
            raise AppError(f"{len(moved)} of {len(plan.entries)} items moved to the Trash. {error}") from error
    return moved
