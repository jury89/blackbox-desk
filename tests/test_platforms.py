from pathlib import Path
import plistlib
import tempfile
from threading import Event
import unittest
from unittest import mock

from blackboxdesk.models import AppError, Cancelled, Volume
from blackboxdesk.platforms import MacVolumes, WindowsVolumes
from blackboxdesk import platforms


class MacTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.info = {
            "MountPoint": str(self.root), "Internal": False, "BusProtocol": "USB",
            "DeviceIdentifier": "disk27s1", "ParentWholeDisk": "disk27", "VolumeUUID": "uuid-one",
            "VolumeName": "SPEEDYBEE", "WritableMedia": True, "WritableVolume": True,
        }
        self.adapter = MacVolumes()
        self.volume = self.adapter.from_info(self.info)

    def tearDown(self):
        self.temp.cleanup()

    def test_actual_mac_writable_keys(self):
        self.assertFalse(self.volume.read_only)
        self.assertTrue(self.adapter.from_info(dict(self.info, WritableVolume=False)).read_only)

    def test_missing_writability_is_conservative(self):
        info = self.info.copy()
        info.pop("WritableVolume")
        self.assertTrue(self.adapter.from_info(info).read_only)

    def test_internal_non_usb_and_wrong_parent_rejected(self):
        for changes in [{"Internal": True}, {"BusProtocol": "PCI-Express"}, {"ParentWholeDisk": "disk30"}]:
            self.assertIsNone(self.adapter.from_info(dict(self.info, **changes)))

    def test_swapped_volume_uuid_rejected(self):
        with mock.patch.object(self.adapter, "info", return_value=dict(self.info, VolumeUUID="different")):
            with self.assertRaises(AppError):
                self.adapter.validate(self.volume)

    def test_eject_unmounts_exact_parent_without_device_eject_or_force(self):
        with mock.patch.object(self.adapter, "info", return_value=self.info), mock.patch.object(platforms, "run", return_value=b"") as run:
            self.adapter.eject(self.volume)
        run.assert_called_once_with(["/usr/sbin/diskutil", "unmountDisk", "disk27"], timeout=30)

    def test_eject_swapped_identity_does_not_unmount_disk(self):
        with mock.patch.object(self.adapter, "info", return_value=dict(self.info, VolumeUUID="other")), mock.patch.object(platforms, "run") as run:
            with self.assertRaises(AppError):
                self.adapter.eject(self.volume)
            run.assert_not_called()

    def test_eject_cancelled_during_validation_does_not_unmount(self):
        cancel = Event()
        def validate(_):
            cancel.set()
            return self.volume
        with mock.patch.object(self.adapter, "validate", side_effect=validate), mock.patch.object(platforms, "run") as run:
            with self.assertRaises(Cancelled):
                self.adapter.eject(self.volume, cancel)
            run.assert_not_called()

    def test_unmounted_attached_fc_is_not_proposed(self):
        raw = plistlib.dumps({"AllDisksAndPartitions": [{"Partitions": [{"DeviceIdentifier": "disk27s1"}]}]})
        with mock.patch.object(platforms, "run", return_value=raw), mock.patch.object(self.adapter, "info", return_value=dict(self.info, MountPoint="")):
            self.assertEqual(self.adapter.list(), [])

    def test_reconnected_same_fc_is_available_again(self):
        raw = plistlib.dumps({"AllDisksAndPartitions": [{"Partitions": [{"DeviceIdentifier": "disk27s1"}]}]})
        with mock.patch.object(platforms, "run", return_value=raw), mock.patch.object(self.adapter, "info", side_effect=[dict(self.info, MountPoint=""), self.info]):
            self.assertEqual(self.adapter.list(), [])
            self.assertEqual(self.adapter.list(), [self.volume])

    def test_eject_failure_propagated(self):
        with mock.patch.object(self.adapter, "info", return_value=self.info), mock.patch.object(platforms, "run", side_effect=AppError("busy")):
            with self.assertRaisesRegex(AppError, "busy"):
                self.adapter.eject(self.volume)

    def test_eject_still_mounted_rejected(self):
        with mock.patch.object(self.adapter, "info", return_value=self.info), mock.patch.object(platforms, "run", return_value=b""), mock.patch.object(Path, "is_mount", return_value=True):
            with self.assertRaisesRegex(AppError, "still mounted"):
                self.adapter.eject(self.volume)

    def test_list_probes_only_external_partitions(self):
        raw = plistlib.dumps({"AllDisksAndPartitions": [{"Partitions": [{"DeviceIdentifier": "disk27s1"}]}]})
        with mock.patch.object(platforms, "run", return_value=raw) as run, mock.patch.object(self.adapter, "info", return_value=self.info):
            self.assertEqual(self.adapter.list(), [self.volume])
        self.assertEqual(run.call_args.args[0][-2:], ["external", "physical"])


class WindowsContractTests(unittest.TestCase):
    """Contratti simulati; non costituiscono una prova su Windows reale."""
    def test_windows_usb_json(self):
        data = b'[{"root":"E:\\\\","label":"FC","disk":"3","identity":"abc","readOnly":false}]'
        with mock.patch.object(platforms, "powershell", return_value=data):
            volumes = WindowsVolumes().list()
        self.assertEqual(len(volumes), 1)
        self.assertFalse(volumes[0].read_only)

    def test_invalid_windows_drive_ignored(self):
        data = b'[{"root":"C:/unsafe","disk":"3","identity":"abc"}]'
        with mock.patch.object(platforms, "powershell", return_value=data):
            self.assertEqual(WindowsVolumes().list(), [])

    def test_missing_drive_prevents_eject(self):
        volume = Volume(Path("E:\\"), "FC", "3", "abc", False)
        adapter = WindowsVolumes()
        with mock.patch.object(adapter, "list", return_value=[]), mock.patch.object(platforms, "powershell") as ps:
            with self.assertRaises(AppError):
                adapter.eject(volume)
            ps.assert_not_called()
