"""Adattatori del sistema operativo. I dischi interni non vengono mai proposti."""

import json
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import time

import ctypes
from ctypes import wintypes

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


def windows_disk_device_id(disk_id):
    if not re.fullmatch(r"\d+", str(disk_id)):
        raise AppError("Invalid USB disk.")
    script = (
        "$ErrorActionPreference='Stop'; "
        f"$disk=Get-CimInstance Win32_DiskDrive -Filter 'Index = {disk_id}'; "
        "if ($null -eq $disk -or $disk.InterfaceType -ne 'USB' -or "
        "[string]::IsNullOrWhiteSpace($disk.PNPDeviceID)) { throw 'Validated USB disk not found' }; "
        "[string]$disk.PNPDeviceID"
    )
    device_id = powershell(script).decode("utf-8-sig", errors="replace").strip()
    if not device_id:
        raise AppError("Validated USB disk not found.")
    return device_id


def windows_configuration_manager():
    config = ctypes.WinDLL("cfgmgr32", use_last_error=True)
    config.CM_Locate_DevNodeW.argtypes = [ctypes.POINTER(wintypes.ULONG), wintypes.LPCWSTR, wintypes.ULONG]
    config.CM_Locate_DevNodeW.restype = wintypes.ULONG
    config.CM_Get_Parent.argtypes = [ctypes.POINTER(wintypes.ULONG), wintypes.ULONG, wintypes.ULONG]
    config.CM_Get_Parent.restype = wintypes.ULONG
    config.CM_Get_Device_IDW.argtypes = [wintypes.ULONG, wintypes.LPWSTR, wintypes.ULONG, wintypes.ULONG]
    config.CM_Get_Device_IDW.restype = wintypes.ULONG
    config.CM_Request_Device_EjectW.argtypes = [wintypes.ULONG, ctypes.POINTER(wintypes.ULONG), wintypes.LPWSTR,
                                                 wintypes.ULONG, wintypes.ULONG]
    config.CM_Request_Device_EjectW.restype = wintypes.ULONG
    return config


def windows_usb_parent_device_id(device_id):
    config = windows_configuration_manager()
    node = wintypes.ULONG()
    status = config.CM_Locate_DevNodeW(ctypes.byref(node), device_id, 0)
    if status:
        raise AppError("Windows could not locate the validated USB device for safe removal.")
    parent = wintypes.ULONG()
    status = config.CM_Get_Parent(ctypes.byref(parent), node, 0)
    if status:
        raise AppError("Windows could not locate the physical USB device for safe removal.")
    parent_id = ctypes.create_unicode_buffer(260)
    status = config.CM_Get_Device_IDW(parent, parent_id, len(parent_id), 0)
    if status or not re.fullmatch(r"USB\\VID_[0-9A-F]{4}&PID_[0-9A-F]{4}(?:&[^\\]+)*\\[^\\]+", parent_id.value, re.IGNORECASE):
        raise AppError("Windows did not identify a removable USB device for safe removal.")
    return parent_id.value


def request_windows_device_eject(device_id):
    config = windows_configuration_manager()
    node = wintypes.ULONG()
    status = config.CM_Locate_DevNodeW(ctypes.byref(node), device_id, 0)
    if status:
        raise AppError("Windows could not locate the validated USB device for safe removal.")
    veto_type = wintypes.ULONG()
    veto_name = ctypes.create_unicode_buffer(260)
    status = config.CM_Request_Device_EjectW(node, ctypes.byref(veto_type), veto_name, len(veto_name), 0)
    if status:
        detail = veto_name.value.strip()
        suffix = f" ({detail})" if detail else ""
        raise AppError(f"Windows refused safe removal of the flight controller{suffix}. Close files using it and try again.")


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
        check_cancel(cancel)
        disk_device = windows_disk_device_id(volume.disk_id)
        request_windows_device_eject(windows_usb_parent_device_id(disk_device))
        deadline = time.monotonic() + 15
        while volume.root.exists() and time.monotonic() < deadline:
            check_cancel(cancel)
            time.sleep(0.25)
        if volume.root.exists():
            raise AppError("Windows did not eject storage. Close open files and use Safely Remove Hardware.")


def platform_volumes():
    if sys.platform == "darwin":
        return MacVolumes()
    if sys.platform == "win32":
        return WindowsVolumes()
    raise AppError("This version supports macOS and Windows.")
