"""Adattatori del sistema operativo. I dischi interni non vengono mai proposti."""

import json
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import time

from .models import AppError, Volume, check_cancel


def run(args, timeout=15):
    options = {"capture_output": True, "timeout": timeout}
    if sys.platform == "win32":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    result = subprocess.run(args, **options)
    if result.returncode:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise AppError(message or "The operating system did not complete the disk operation.")
    return result.stdout


class MacVolumes:
    def info(self, target):
        try:
            result = plistlib.loads(run(["/usr/sbin/diskutil", "info", "-plist", str(target)]))
        except (ValueError, plistlib.InvalidFileException) as error:
            raise AppError("USB disk information cannot be read.") from error
        if not isinstance(result, dict):
            raise AppError("Invalid USB disk information.")
        return result

    def from_info(self, info):
        mount = info.get("MountPoint")
        if info.get("Internal") is not False or info.get("BusProtocol") != "USB" or not mount:
            return None
        device = info.get("DeviceIdentifier", "")
        disk = info.get("ParentWholeDisk") or device
        if not re.fullmatch(r"disk\d+", disk) or not re.fullmatch(re.escape(disk) + r"(?:s\d+)*", device):
            return None
        root = Path(mount).resolve()
        identity = str(info.get("VolumeUUID") or info.get("MediaUUID") or device)
        read_only = not bool(info.get("WritableVolume", False) and info.get("WritableMedia", False))
        return Volume(root, info.get("VolumeName") or root.name, disk, identity, read_only)

    def list(self):
        data = plistlib.loads(run(["/usr/sbin/diskutil", "list", "-plist", "external", "physical"]))
        volumes = []
        for disk in data.get("AllDisksAndPartitions", []):
            for part in disk.get("Partitions") or [disk]:
                identifier = part.get("DeviceIdentifier", "")
                if not re.fullmatch(r"disk\d+(?:s\d+)*", identifier):
                    continue
                try:
                    volume = self.from_info(self.info(identifier))
                    if volume:
                        volumes.append(volume)
                except AppError:
                    continue  # Unmounted partition or a disk just disconnected.
        return volumes

    def validate(self, volume):
        current = self.from_info(self.info(volume.root))
        if current is None or (current.root, current.disk_id, current.identity) != (volume.root, volume.disk_id, volume.identity):
            raise AppError("Storage was disconnected or replaced. Reconnect the flight controller.")
        return current

    def eject(self, volume, cancel=None):
        check_cancel(cancel)
        self.validate(volume)
        # Some Betaflight MSC devices reappear immediately after `eject` on
        # macOS (observed on SpeedyBee F7 V3). Unmount the whole disk instead:
        # files are closed/flushed, while the USB device stays attached and
        # macOS leaves its volumes unmounted until the next USB connection.
        # No force, persistent automount rules, or device blacklist.
        check_cancel(cancel)
        run(["/usr/sbin/diskutil", "unmountDisk", volume.disk_id], timeout=30)
        if volume.root.is_mount():
            raise AppError("Storage is still mounted. Close files and programs using it, then try Eject flight controller again.")


WINDOWS_VOLUMES = r"""
$ErrorActionPreference = 'Stop'
$rows = @()
Get-Disk | Where-Object { $_.BusType -eq 'USB' } | ForEach-Object {
    $disk = $_
    Get-Partition -DiskNumber $disk.Number | Where-Object { $_.DriveLetter } | ForEach-Object {
        $partition = $_
        $volume = $partition | Get-Volume
        $rows += [pscustomobject]@{
            root = ([string]$partition.DriveLetter + ':\')
            label = [string]$volume.FileSystemLabel
            disk = [string]$disk.Number
            identity = ([string]$disk.UniqueId + '|' + [string]$partition.Guid + '|' + [string]$volume.UniqueId)
            readOnly = [bool]($disk.IsReadOnly -or $partition.IsReadOnly)
        }
    }
}
ConvertTo-Json -InputObject @($rows) -Compress -Depth 4
"""


def powershell(script):
    # Il contenuto variabile inserito negli script è limitato a lettere di unità validate.
    script = "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); " + script
    return run(["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script], timeout=30)


class WindowsVolumes:
    def list(self):
        try:
            data = json.loads(powershell(WINDOWS_VOLUMES).decode("utf-8-sig"))
        except (UnicodeError, ValueError) as error:
            raise AppError("Windows did not return the USB storage list.") from error
        if isinstance(data, dict):
            data = [data]
        volumes = []
        for item in data or []:
            if not re.fullmatch(r"[A-Za-z]:\\", item.get("root", "")) or not str(item.get("disk", "")).isdigit():
                continue
            volumes.append(Volume(Path(item["root"]), item.get("label") or item["root"],
                                  str(item["disk"]), item["identity"], bool(item.get("readOnly", True))))
        return volumes

    def validate(self, volume):
        for current in self.list():
            if (current.root, current.disk_id, current.identity) == (volume.root, volume.disk_id, volume.identity):
                return current
        raise AppError("Storage was disconnected or replaced. Reconnect the flight controller.")

    def eject(self, volume, cancel=None):
        check_cancel(cancel)
        self.validate(volume)
        drive = str(volume.root)[:2]
        if not re.fullmatch(r"[A-Za-z]:", drive):
            raise AppError("Invalid USB drive.")
        powershell(f"$ErrorActionPreference='Stop'; $shell=New-Object -ComObject Shell.Application; "
                   f"$item=$shell.Namespace(17).ParseName('{drive}'); "
                   "if ($null -eq $item) { throw 'USB storage not found' }; $item.InvokeVerb('Eject')")
        deadline = time.monotonic() + 15
        while volume.root.exists() and time.monotonic() < deadline:
            time.sleep(0.25)
        if volume.root.exists():
            raise AppError("Windows did not eject storage. Close open files and use Safely Remove Hardware.")


def platform_volumes():
    if sys.platform == "darwin":
        return MacVolumes()
    if sys.platform == "win32":
        return WindowsVolumes()
    raise AppError("This version supports macOS and Windows.")
