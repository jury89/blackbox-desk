import datetime
from dataclasses import replace
from pathlib import Path
import tempfile
import time

from serial.tools import list_ports

from . import files
from .models import AppError, Cancelled, Device, FlashResetPlan, SDResetPlan, Session, Volume, check_cancel
from .msp import MSP
from .platforms import platform_volumes


class Backend:
    def __init__(self, volumes=None, msp_factory=MSP):
        self.volumes = volumes or platform_volumes()
        self.msp_factory = msp_factory

    def discover(self, progress=lambda *_: None, cancel=None):
        check_cancel(cancel)
        devices = []
        for port in list_ports.comports():
            if port.vid is not None:
                devices.append(Device("serial:" + port.device, f"{port.description} ({port.device})", port=port.device))
        for volume in self.volumes.list():
            check_cancel(cancel)
            if files.has_layout(volume.root):
                devices.append(Device("volume:" + str(volume.root), f"{volume.label} — USB storage", volume=volume))
        return devices

    def connect(self, device, progress=lambda *_: None, cancel=None):
        started = time.monotonic()
        timings = {}
        def scan(volume, board, hint=""):
            scan_start = time.monotonic()
            storage, logs = files.scan_logs(volume.root, hint, progress, cancel, read_dates=False)
            timings["Elenco log"] = time.monotonic() - scan_start
            timings["Totale fino all'elenco"] = time.monotonic() - started
            return Session(volume, board, storage, logs, timings=timings)
        if device.volume:
            volume = self.volumes.validate(device.volume)
            timings["Verifica disco già montato"] = time.monotonic() - started
            return scan(volume, "Betaflight · storage already connected")
        before = {(v.disk_id, v.identity, str(v.root)) for v in self.volumes.list()}
        timings["Initial disk search"] = time.monotonic() - started
        phase_start = time.monotonic()
        progress("Reading the flight controller model and storage…", -1)
        with self.msp_factory(device.port, cancel) as connection:
            identity = connection.identify()
            timings["Identificazione FC"] = time.monotonic() - phase_start
            phase_start = time.monotonic()
            progress(f"{identity.board} · Betaflight {identity.firmware}. Opening USB storage…", -1)
            connection.reboot_storage()
        timings["Comando modalità USB"] = time.monotonic() - phase_start
        phase_start = time.monotonic()
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            check_cancel(cancel)
            candidates = [v for v in self.volumes.list() if (v.disk_id, v.identity, str(v.root)) not in before]
            if len(candidates) > 1:
                raise AppError("Multiple USB storage devices appeared. Press Search and explicitly select the flight controller storage.")
            if candidates:
                volume = candidates[0]
                timings["Attesa disco USB"] = time.monotonic() - phase_start
                layout_start = time.monotonic()
                if not files.has_layout(volume.root) and not volume.label.upper().startswith("BETAFLT"):
                    raise AppError("The new USB disk cannot be identified as Blackbox storage. Press Search and select flight controller storage.")
                timings["Riconoscimento cartelle Blackbox"] = time.monotonic() - layout_start
                return scan(volume, f"{identity.board} · {identity.firmware}", identity.storage)
            progress(f"Attendo il disco USB della FC… {time.monotonic() - phase_start:.0f} s", -1)
            if cancel is not None:
                cancel.wait(0.7)
            else:
                time.sleep(0.7)
        raise AppError("USB storage did not appear. Check ‘Activate Mass Storage’ in Betaflight and try again.")

    def refresh(self, session, progress=lambda *_: None, cancel=None):
        volume = self.volumes.validate(session.volume)
        storage, logs = files.scan_logs(volume.root, session.storage, progress, cancel, read_dates=False)
        cached = {(entry.path, entry.source_size, entry.source_mtime, entry.offset): entry.recorded for entry in session.logs}
        logs = [replace(entry, recorded=cached.get((entry.path, entry.source_size, entry.source_mtime, entry.offset), "")) for entry in logs]
        return Session(volume, session.board, storage, logs, session.demo, session.timings)

    def read_dates(self, session, emit, cancel=None):
        """Optional metadata: cancellable between one file and the next."""
        check_cancel(cancel)
        self.volumes.validate(session.volume)
        for row, entry in enumerate(tuple(session.logs)):
            check_cancel(cancel)
            if entry.recorded:
                continue
            try:
                info = entry.path.lstat()
                if entry.path.is_symlink() or entry.path.parent.is_symlink() or (info.st_size, info.st_mtime_ns) != (entry.source_size, entry.source_mtime):
                    raise AppError("The log changed: refresh the list.")
                recorded = files.recorded_date(entry.path, entry.offset)
                check_cancel(cancel)
                emit(row, recorded, "")
            except OSError as error:
                emit(row, "—", str(error))
            except Cancelled:
                raise
            except AppError as error:
                emit(row, "—", str(error))

    def copy(self, session, entries, destination, eject_after=True, progress=lambda *_: None, cancel=None):
        if not entries:
            raise AppError("Select at least one log to copy.")
        current = self.volumes.validate(session.volume)
        results = []
        for index, entry in enumerate(entries):
            def report(message, percent):
                progress(message, int((index + percent / 100) * 100 / len(entries)))
            try:
                check_cancel(cancel)
                self.volumes.validate(current)
                results.append(files.copy_log(current.root, entry, destination, report, cancel))
            except Cancelled as error:
                raise Cancelled(f"Copy cancelled. Completed {len(results)} of {len(entries)} logs; copies already saved remain on the computer.") from error
            except (OSError, AppError) as error:
                raise AppError(f"Completed {len(results)} of {len(entries)} logs. Copies already saved remain on the computer. {error}") from error
        eject_error, ejected = "", False
        if eject_after:
            progress("Copies verified. Ejecting storage…", -1)
            try:
                self.volumes.eject(current, cancel)
                ejected = True
            except (OSError, AppError, TimeoutError) as error:
                eject_error = str(error)
        return {"results": results, "ejected": ejected, "eject_error": eject_error}

    def delete(self, session, entries, confirmed=False, progress=lambda *_: None, cancel=None):
        current = self.volumes.validate(session.volume)
        if current.read_only:
            raise AppError("Storage is read-only.")
        deleted = files.delete_logs(session, entries, confirmed, progress, cancel)
        return {"deleted": deleted, "session": self.refresh(session, progress, cancel)}

    def eject(self, session, progress=lambda *_: None, cancel=None):
        progress("Ejecting flight controller storage…", -1)
        self.volumes.eject(session.volume, cancel)
        return True

    def prepare_flash_reset(self, device, progress=lambda *_: None, cancel=None):
        if not device.port or device.volume:
            raise AppError("To empty FLASH, select the flight controller in normal USB mode before pressing Connect.")
        progress("Checking the flight controller and FLASH storage space…", -1)
        with self.msp_factory(device.port, cancel) as connection:
            identity = connection.identify()
            if identity.storage != "FLASH":
                raise AppError("This flight controller uses SDCARD. Press Connect, then Empty storage from the USB disk.")
            uid = connection.uid()
            state = connection.flash_summary()
            if not state["ready"]:
                raise AppError("FLASH storage is busy. Wait for the operation on the flight controller to finish.")
        return FlashResetPlan(device, identity.board, identity.firmware, uid, state["capacity"], state["used"])

    def reset_flash(self, plan, confirmed=False, progress=lambda *_: None, cancel=None):
        if not confirmed:
            raise AppError("Confirm complete emptying of Blackbox storage.")
        with self.msp_factory(plan.device.port, cancel) as connection:
            return connection.erase_flash(plan.uid, plan.capacity, confirmed=True, progress=progress)

    def prepare_sd_reset(self, session, progress=lambda *_: None, cancel=None):
        check_cancel(cancel)
        current = self.volumes.validate(session.volume)
        current_session = Session(current, session.board, session.storage, session.logs, session.demo)
        return SDResetPlan(current_session, files.sd_reset_entries(current_session))

    def reset_sd(self, plan, confirmed=False, progress=lambda *_: None, cancel=None):
        def validate_volume():
            current = self.volumes.validate(plan.session.volume)
            if current.read_only:
                raise AppError("Storage became read-only.")
        deleted = files.reset_sd_logs(plan, confirmed, progress, cancel, validate_volume)
        return {"deleted": deleted, "session": self.refresh(plan.session, progress, cancel)}


class DemoVolumes:
    def __init__(self, volume):
        self.volume = volume

    def list(self):
        return [self.volume] if self.volume.root.exists() else []

    def validate(self, volume):
        if volume != self.volume or not volume.root.exists():
            raise AppError("Demo storage is unavailable.")
        return volume

    def eject(self, volume, cancel=None):
        self.validate(volume)  # No action on real disks.


class DemoBackend(Backend):
    def __init__(self):
        self.directory = tempfile.TemporaryDirectory(prefix="blackbox-desk-demo-")
        root = Path(self.directory.name) / "Demo storage"
        (root / "LOGS").mkdir(parents=True)
        for n, size in enumerate([280, 940, 1600, 620, 2200, 1200], start=11):
            header = files.HEADER + f"H Log start datetime:2026-09-17T10:{n:02d}:00\nH Data version:2\n".encode()
            (root / "LOGS" / f"LOG{n:05d}.BFL").write_bytes(header + b"\0" * (size * 1024))
        volume = Volume(root.resolve(), "Demo storage", "demo", "demo", False)
        super().__init__(DemoVolumes(volume))
        self.device = Device("demo", "Demo flight controller — no real device", volume=volume)
        self.computer_root = Path(self.directory.name) / "Computer demo"
        (self.computer_root / "Da analizzare").mkdir(parents=True)
        (self.computer_root / "Voli del weekend").mkdir()
        (self.computer_root / "LOG00012.BFL").write_bytes((root / "LOGS" / "LOG00012.BFL").read_bytes())

    def discover(self, progress=lambda *_: None, cancel=None):
        return [self.device]

    def connect(self, device, progress=lambda *_: None, cancel=None):
        session = super().connect(device, progress, cancel)
        session.board, session.demo = "SpeedyBee F7 V3 · dimostrazione", True
        return session

    def close(self):
        self.directory.cleanup()
