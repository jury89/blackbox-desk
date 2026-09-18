"""Operazioni sui log; nessun comando di configurazione o cancellazione flash."""

import datetime
import hashlib
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

from .models import AppError, Cancelled, CopyResult, LogEntry, check_cancel

HEADER = b"H Product:Blackbox flight data recorder by Nicholas Sherlock\n"
BLOCK = 1024 * 1024
SD_NAME = re.compile(r"LOG(\d+)\.BFL", re.I)
FLASH_NAME = re.compile(r"BTFL_(\d+)\.BBL", re.I)


def log_dirs(root):
    return [root] + [p for p in root.iterdir() if p.name.casefold() == "logs" and p.is_dir() and not p.is_symlink()]


def has_layout(root):
    try:
        for folder in log_dirs(root):
            if folder != root:
                return True
            if any(SD_NAME.fullmatch(p.name) or FLASH_NAME.fullmatch(p.name) or p.name.upper() == "BTFL_ALL.BBL" for p in folder.iterdir()):
                return True
        return root.name.upper().startswith("BETAFLT")
    except OSError:
        return False


def recorded_date(path, offset=0):
    with path.open("rb") as handle:
        handle.seek(offset)
        data = handle.read(8192)
    match = re.search(rb"(?:^|\n)H Log start datetime:([^\r\n]+)", data)
    if match:
        try:
            value = datetime.datetime.fromisoformat(match[1].decode().strip().replace("Z", "+00:00"))
            if value.year >= 2020:
                return value.strftime("%d/%m/%Y %H:%M")
        except (ValueError, UnicodeError):
            pass
    return "—"


def make_entry(path, number, offset=0, size=None, extracted=False, *, read_dates=True, info=None):
    info = info or path.stat()
    name = f"VOLO_{number:05d}.BBL" if extracted else path.name
    return LogEntry(name, path, number, info.st_size - offset if size is None else size,
                    info.st_size, info.st_mtime_ns, offset, recorded_date(path, offset) if read_dates else "", extracted)


def split_flash(path, progress, cancel, *, read_dates=True):
    """Scansione sequenziale limitata in RAM; le intestazioni flash sono allineate a 2048 byte."""
    size, position, offsets, tail = path.stat().st_size, 0, [], b""
    if size == 0:
        return []
    with path.open("rb") as handle:
        while True:
            check_cancel(cancel)
            block = handle.read(BLOCK)
            if not block:
                break
            data = tail + block
            base = position - len(tail)
            cursor = data.find(HEADER)
            while cursor >= 0:
                offset = base + cursor
                if offset % 2048 == 0 and (not offsets or offsets[-1] != offset):
                    offsets.append(offset)
                cursor = data.find(HEADER, cursor + 1)
            position += len(block)
            tail = data[-(len(HEADER) - 1):]
            progress("Leggo l'indice dei voli nella flash…", int(position * 100 / max(size, 1)))
    if not offsets:
        raise AppError("Il file complessivo della flash non contiene log riconoscibili.")
    return [make_entry(path, n + 1, start, (offsets[n + 1] if n + 1 < len(offsets) else size) - start, True, read_dates=read_dates)
            for n, start in enumerate(offsets)]


def scan_logs(root, hint="", progress=lambda *_: None, cancel=None, *, read_dates=True):
    sd, flash, combined = [], [], None
    folders = log_dirs(root)
    progress("Leggo l'elenco dei log nella memoria USB…", -1)
    for folder in folders:
        with os.scandir(folder) as listing:
            candidates = list(listing)
        for item in candidates:
            check_cancel(cancel)
            sd_match = SD_NAME.fullmatch(item.name)
            flash_match = FLASH_NAME.fullmatch(item.name) if folder == root else None
            is_combined = folder == root and item.name.upper() == "BTFL_ALL.BBL"
            if not (sd_match or flash_match or is_combined):
                continue
            info = item.stat(follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):
                continue
            path = Path(item.path)
            if sd_match:
                sd.append(make_entry(path, int(sd_match[1]), read_dates=read_dates, info=info))
            elif flash_match:
                flash.append(make_entry(path, int(flash_match[1]), read_dates=read_dates, info=info))
            else:
                combined = path
    if sd and (flash or combined):
        raise AppError("Il disco contiene due organizzazioni Blackbox diverse. Seleziona una memoria senza ambiguità.")
    if sd:
        if hint == "FLASH":
            raise AppError("I file del disco non corrispondono alla memoria indicata dalla FC.")
        storage, logs = "SDCARD", sd
    elif flash or combined:
        if hint == "SDCARD":
            raise AppError("I file del disco non corrispondono alla memoria indicata dalla FC.")
        storage = "FLASH"
        if not flash or max(entry.number for entry in flash) >= 100:
            if combined is None:
                raise AppError("La flash espone 100 log ma manca il file complessivo necessario a trovare gli altri.")
            logs = split_flash(combined, progress, cancel, read_dates=read_dates)
        else:
            logs = flash
    else:
        storage, logs = hint or ("SDCARD" if len(folders) > 1 else "UNKNOWN"), []
    return storage, sorted(logs, key=lambda entry: entry.number, reverse=True)


def validate_entry(root, entry):
    root = root.resolve()
    try:
        relative = entry.path.relative_to(root)
    except ValueError as error:
        raise AppError("Il log selezionato non appartiene alla memoria collegata.") from error
    cursor = root
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise AppError("Un collegamento simbolico non può essere usato come log della FC.")
    if len(relative.parts) > 2 or (len(relative.parts) == 2 and relative.parts[0].casefold() != "logs"):
        raise AppError("Il log non si trova nella cartella Blackbox prevista.")
    info = entry.path.stat()
    if not stat.S_ISREG(info.st_mode) or (info.st_size, info.st_mtime_ns) != (entry.source_size, entry.source_mtime):
        raise AppError(f"{entry.name} è cambiato. Aggiorna l'elenco prima di procedere.")
    if entry.offset < 0 or entry.size < len(HEADER) or entry.offset + entry.size > info.st_size:
        raise AppError(f"{entry.name} è vuoto o incompleto.")
    with entry.path.open("rb") as handle:
        handle.seek(entry.offset)
        if handle.read(len(HEADER)) != HEADER:
            raise AppError(f"{entry.name} non ha un'intestazione Blackbox valida.")


def digest_file(path, cancel=None):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(BLOCK), b""):
            check_cancel(cancel)
            digest.update(block)
    return digest.hexdigest()


def unlock_copy(path):
    """Rende il file locale scrivibile e visibile nel Finder senza alterare i dati."""
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise AppError("La copia locale non è un file regolare.")
    locks = sum(getattr(stat, name, 0) for name in ("UF_IMMUTABLE", "SF_IMMUTABLE", "UF_APPEND", "SF_APPEND"))
    hidden = getattr(stat, "UF_HIDDEN", 0)
    flags = getattr(info, "st_flags", 0)
    if flags & (locks | hidden):
        os.chflags(path, flags & ~(locks | hidden), follow_symlinks=False)
    mode = stat.S_IMODE(info.st_mode) | stat.S_IRUSR | stat.S_IWUSR
    if sys.platform == "win32":
        os.chmod(path, mode)
    else:
        os.chmod(path, mode, follow_symlinks=False)
    if getattr(path.stat(), "st_flags", 0) & locks:
        raise AppError(f"La copia {path.name} risulta ancora bloccata.")
    if getattr(path.stat(), "st_flags", 0) & hidden:
        raise AppError(f"La copia {path.name} risulta ancora nascosta nel Finder.")
    fd = os.open(path, os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0))
    os.close(fd)


def publish_copy(stage, name, checksum, cancel=None):
    original = Path(name)
    if original.name != name or original.suffix.upper() not in (".BFL", ".BBL"):
        raise AppError("Nome del log non valido.")
    family = re.compile(re.escape(original.stem) + r"(?:_([2-9]|[1-9][0-9]+))?" + re.escape(original.suffix), re.I)
    candidates = [p for p in stage.parent.iterdir() if family.fullmatch(p.name)]
    for existing in candidates:
        check_cancel(cancel)
        if existing.is_file() and not existing.is_symlink() and existing.stat().st_size == stage.stat().st_size:
            if digest_file(existing, cancel) == checksum:
                unlock_copy(existing)
                return existing, True
    unlock_copy(stage)
    occupied = {p.name.casefold() for p in candidates}
    number = 1
    while True:
        check_cancel(cancel)
        target = stage.parent / (name if number == 1 else f"{original.stem}_{number}{original.suffix}")
        if target.name.casefold() not in occupied:
            try:
                os.link(stage, target)
                return target, False
            except FileExistsError:
                if target.is_file() and not target.is_symlink() and digest_file(target, cancel) == checksum:
                    unlock_copy(target)
                    return target, True
        number += 1


def copy_log(root, entry, destination, progress=lambda *_: None, cancel=None):
    root, destination = root.resolve(), destination.expanduser().resolve()
    if destination == root or root in destination.parents:
        raise AppError("Scegli una cartella sul computer, fuori dalla memoria del drone.")
    validate_entry(root, entry)
    destination.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".blackbox-", suffix=".partial", dir=destination)
    stage = Path(name)
    try:
        digest, remaining = hashlib.sha256(), entry.size
        with os.fdopen(fd, "wb") as output, entry.path.open("rb") as source:
            source.seek(entry.offset)
            while remaining:
                check_cancel(cancel)
                block = source.read(min(BLOCK, remaining))
                if not block:
                    raise AppError(f"Copia interrotta di {entry.name}.")
                output.write(block)
                digest.update(block)
                remaining -= len(block)
                progress(f"Copio {entry.name}", int(100 * (entry.size - remaining) / entry.size))
            output.flush()
            os.fsync(output.fileno())
        validate_entry(root, entry)
        if stage.stat().st_size != entry.size or digest_file(stage, cancel) != digest.hexdigest():
            raise AppError(f"La verifica della copia di {entry.name} non è riuscita.")
        target, reused = publish_copy(stage, entry.name, digest.hexdigest(), cancel)
    finally:
        stage.unlink(missing_ok=True)
    # Il nome temporaneo nascosto e il nome finale condividono l'inode.
    # Normalizzare dopo la rimozione del temporaneo evita che il file finale
    # mantenga UF_HIDDEN, anche quando si riutilizza una copia già presente.
    unlock_copy(target)
    return CopyResult(entry, target, reused)


def delete_logs(session, entries, confirmed=False, progress=lambda *_: None, cancel=None):
    if not confirmed:
        raise AppError("Conferma la cancellazione dei log selezionati.")
    if not session.can_delete:
        raise AppError("Questa memoria non permette di eliminare singoli log via USB.")
    if not entries or len({entry.path for entry in entries}) != len(entries):
        raise AppError("Selezione dei log non valida.")
    for entry in entries:
        if entry.extracted or entry.offset != 0 or not SD_NAME.fullmatch(entry.path.name):
            raise AppError("Si possono eliminare solo file SDCARD individuali.")
        validate_entry(session.volume.root, entry)
    deleted = []
    for entry in entries:
        try:
            check_cancel(cancel)
            validate_entry(session.volume.root, entry)
            entry.path.unlink()
            deleted.append(entry.name)
            progress(f"Eliminato {entry.name}", int(len(deleted) * 100 / len(entries)))
        except (OSError, AppError) as error:
            error_type = Cancelled if isinstance(error, Cancelled) else AppError
            raise error_type(f"Eliminati {len(deleted)} di {len(entries)} log. {error} Aggiorna l'elenco.") from error
    return deleted


def sd_reset_entries(session):
    """Snapshot dei soli log SDCARD: include file vuoti/incompleti, mai symlink."""
    if not session.can_delete:
        raise AppError("Lo svuotamento diretto richiede una memoria SDCARD scrivibile.")
    entries = []
    for folder in log_dirs(session.volume.root):
        for path in folder.iterdir():
            if not SD_NAME.fullmatch(path.name):
                continue
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise AppError("Un elemento nell'elenco dei log non è un file regolare. Svuotamento bloccato.")
            entries.append((path, info.st_size, info.st_mtime_ns))
    return tuple(sorted(entries))


def reset_sd_logs(plan, confirmed=False, progress=lambda *_: None, cancel=None, validate_volume=lambda: None):
    if not confirmed:
        raise AppError("Conferma lo svuotamento di tutti i log della memoria.")
    validate_volume()
    if sd_reset_entries(plan.session) != plan.entries:
        raise AppError("L'elenco dei log è cambiato dopo la conferma. Rileggilo prima di svuotare la memoria.")
    deleted = 0
    for path, size, modified in plan.entries:
        try:
            check_cancel(cancel)
            validate_volume()
            # Riconvalida anche le cartelle: un collegamento simbolico non può
            # cambiare il destinatario fra conferma e cancellazione.
            root = plan.session.volume.root.resolve()
            relative = path.relative_to(root)
            if len(relative.parts) not in (1, 2) or (len(relative.parts) == 2 and relative.parts[0].casefold() != "logs"):
                raise AppError("Percorso del log non valido.")
            if path.parent.is_symlink() or path.is_symlink():
                raise AppError("Il percorso dei log è stato sostituito.")
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or (info.st_size, info.st_mtime_ns) != (size, modified):
                raise AppError("Un log è cambiato durante lo svuotamento.")
            path.unlink()
            deleted += 1
            progress(f"Svuoto la memoria: eliminati {deleted} di {len(plan.entries)} log…", int(100 * deleted / len(plan.entries)))
        except (OSError, ValueError, AppError) as error:
            raise AppError(f"Svuotamento parziale: eliminati {deleted} di {len(plan.entries)} log. Aggiorna l'elenco. {error}") from error
    validate_volume()
    if sd_reset_entries(plan.session):
        raise AppError("Sono comparsi altri log durante lo svuotamento. Aggiorna l'elenco.")
    return deleted
