from dataclasses import dataclass, field
from pathlib import Path


class AppError(Exception):
    pass


class Cancelled(AppError):
    pass


@dataclass(frozen=True)
class Volume:
    root: Path
    label: str
    disk_id: str
    identity: str
    read_only: bool = True


@dataclass(frozen=True)
class Device:
    key: str
    label: str
    port: str = ""
    volume: Volume | None = None


@dataclass(frozen=True)
class LogEntry:
    name: str
    path: Path
    number: int
    size: int
    source_size: int
    source_mtime: int
    offset: int = 0
    recorded: str = "—"
    extracted: bool = False


@dataclass
class Session:
    volume: Volume
    board: str
    storage: str
    logs: list[LogEntry] = field(default_factory=list)
    demo: bool = False
    timings: dict[str, float] = field(default_factory=dict)

    @property
    def can_delete(self):
        return self.storage == "SDCARD" and not self.volume.read_only


@dataclass(frozen=True)
class CopyResult:
    entry: LogEntry
    path: Path
    reused: bool


@dataclass(frozen=True)
class FlashResetPlan:
    device: Device
    board: str
    firmware: str
    uid: str
    capacity: int
    used: int


@dataclass(frozen=True)
class SDResetPlan:
    session: Session
    # Path, byte size and modification time captured before confirmation.
    entries: tuple[tuple[Path, int, int], ...]


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise Cancelled("Operazione annullata.")
