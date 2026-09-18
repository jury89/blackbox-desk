import unittest

from blackboxdesk.models import AppError
from blackboxdesk import msp


def board(name):
    names = [b"STM32F7X2", name.encode(), b"TEST"]
    return b"TEST" + b"\0" * 4 + b"".join(bytes((len(value),)) + value for value in names)


class FakeMSP(msp.MSP):
    def __init__(self, changes=None):
        self.answers = {
            msp.API: b"\0\x01\x30", msp.VARIANT: b"BTFL", msp.VERSION: b"\x1a\x06\x01",
            msp.BOARD: board("ANOTHER_FC_H7"), msp.STATUS: b"\0" * 15,
            msp.BLACKBOX: b"\x01\x02", msp.REBOOT: b"\x02\x01",
        }
        self.answers.update(changes or {})
        self.calls = []
        self.cancel = None
        self._erase_authorized = False

    def request(self, command, payload=b"", timeout=3):
        self.calls.append((command, payload))
        result = self.answers[command]
        if isinstance(result, Exception):
            raise result
        return result


class MSPTests(unittest.TestCase):
    def test_known_packet(self):
        self.assertEqual(msp.packet(68, b"\x02"), b"$M<\x01\x44\x02\x47")

    def test_fragmentation_noise_and_bad_checksum(self):
        good = msp.packet(2, b"BTFL").replace(b"$M<", b"$M>")
        bad = good[:-1] + bytes((good[-1] ^ 255,))
        buffer = bytearray(b"noise" + bad + good[:5])
        self.assertIsNone(msp.pop_reply(buffer))
        buffer.extend(good[5:])
        self.assertEqual(msp.pop_reply(buffer), (2, b"BTFL", False))

    def test_other_board_supported(self):
        identity = FakeMSP().identify()
        self.assertEqual(identity.board, "ANOTHER_FC_H7")
        self.assertEqual(identity.storage, "SDCARD")

    def test_flash_and_multiple_board_names(self):
        for name in ["SPEEDYBEEF7V3", "MATEKH743", "OTHER_BOARD"]:
            self.assertEqual(FakeMSP({msp.BOARD: board(name), msp.BLACKBOX: b"\x01\x01"}).identify().storage, "FLASH")

    def test_non_betaflight_armed_old_api_and_bad_memory_refused(self):
        for changes in [
            {msp.VARIANT: b"INAV"}, {msp.STATUS: b"\0" * 6 + b"\x01" + b"\0" * 8},
            {msp.API: b"\0\x01\x20"}, {msp.BLACKBOX: b"\x01\x03"}, {msp.BOARD: b"short"},
        ]:
            with self.subTest(changes=changes):
                with self.assertRaises(AppError):
                    FakeMSP(changes).identify()

    def test_reboot_only_msc(self):
        connection = FakeMSP()
        connection.reboot_storage()
        self.assertEqual(connection.calls, [(68, b"\x02")])

    def test_not_ready_refused(self):
        with self.assertRaises(AppError):
            FakeMSP({msp.REBOOT: b"\x02\0"}).reboot_storage()

    def test_disconnect_after_reboot_is_tolerated(self):
        FakeMSP({msp.REBOOT: OSError("disconnected")}).reboot_storage()

    def test_unknown_and_destructive_commands_blocked(self):
        connection = msp.MSP("unused")
        for command, payload in [(72, b""), (250, b""), (68, b"\x01")]:
            with self.assertRaises(AppError):
                connection.request(command, payload)
