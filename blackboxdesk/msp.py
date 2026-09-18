"""MSP v1: identificazione, ingresso MSC ed erase Blackbox con conferma."""

from dataclasses import dataclass
import struct
import subprocess
import sys
import time

import serial

from .models import AppError, check_cancel

API, VARIANT, VERSION, BOARD, REBOOT, BLACKBOX, STATUS = 1, 2, 3, 4, 68, 80, 101
FLASH_SUMMARY, FLASH_ERASE, UID = 70, 72, 160
ALLOWED = {API, VARIANT, VERSION, BOARD, BLACKBOX, STATUS, REBOOT, FLASH_SUMMARY, UID}


def packet(command, payload=b""):
    body = bytes((len(payload), command)) + payload
    checksum = 0
    for byte in body:
        checksum ^= byte
    return b"$M<" + body + bytes((checksum,))


def pop_reply(buffer):
    while len(buffer) >= 3:
        if buffer[:3] not in (b"$M>", b"$M!"):
            del buffer[0]
            continue
        if len(buffer) < 6 or len(buffer) < buffer[3] + 6:
            return None
        frame = bytes(buffer[:buffer[3] + 6])
        checksum = 0
        for byte in frame[3:-1]:
            checksum ^= byte
        if checksum != frame[-1]:
            del buffer[0]
            continue
        del buffer[:len(frame)]
        return frame[4], frame[5:-1], frame[2:3] == b"!"
    return None


@dataclass(frozen=True)
class Identity:
    board: str
    firmware: str
    storage: str


class MSP:
    def __init__(self, port, cancel=None):
        self.port, self.cancel = port, cancel
        self.connection = None
        self.buffer = bytearray()
        self._erase_authorized = False

    def __enter__(self):
        try:
            if sys.platform == "darwin":
                busy = subprocess.run(["/usr/sbin/lsof", "-t", self.port], capture_output=True, timeout=5)
                if busy.stdout.strip():
                    raise AppError("La FC è già in uso. Premi Disconnect nell'app Betaflight e riprova.")
            kwargs = {} if sys.platform == "win32" else {"exclusive": True}
            self.connection = serial.Serial(self.port, 115200, timeout=0.15, write_timeout=2, **kwargs)
            self.connection.reset_input_buffer()
            return self
        except serial.SerialException as error:
            raise AppError("Non riesco ad aprire la FC. Disconnettila dall'app Betaflight e riprova.") from error

    def __exit__(self, *_):
        if self.connection:
            self.connection.close()

    def request(self, command, payload=b"", timeout=3):
        erase_allowed = command == FLASH_ERASE and self._erase_authorized and payload == b""
        if (command not in ALLOWED and not erase_allowed) or (command == REBOOT and payload != b"\x02"):
            raise AppError("Comando non consentito: l'app non cambia la configurazione della FC.")
        check_cancel(self.cancel)
        frame = packet(command, payload)
        if self.connection.write(frame) != len(frame):
            raise AppError("Invio USB incompleto.")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            check_cancel(self.cancel)
            reply = pop_reply(self.buffer)
            if reply:
                received, body, rejected = reply
                if received != command:
                    continue
                if rejected:
                    message = "Il firmware non supporta la modalità disco USB richiesta." if command == REBOOT else "La FC non supporta un comando di lettura necessario."
                    raise AppError(message)
                return body
            # Attendi il primo byte, poi consuma soltanto quelli già disponibili:
            # read(1024) aspetterebbe il timeout anche per risposte MSP brevissime.
            self.buffer.extend(self.connection.read(max(1, min(1024, self.connection.in_waiting))))
        raise TimeoutError("La FC non risponde. Chiudi la connessione in Betaflight e riprova.")

    def identify(self):
        api = self.request(API)
        if len(api) < 3 or api[1] != 1 or api[2] < 44:
            raise AppError("Serve Betaflight con protocollo MSP 1.44 o successivo (Betaflight 4.3+).")
        if self.request(VARIANT) != b"BTFL":
            raise AppError("Il dispositivo selezionato non usa Betaflight.")
        version, board = self.request(VERSION), self.request(BOARD)
        names, offset = [], 8
        for _ in range(3):
            if offset >= len(board) or offset + 1 + board[offset] > len(board):
                raise AppError("Identificazione della FC incompleta.")
            size = board[offset]
            offset += 1
            names.append(board[offset:offset + size].decode("ascii", errors="replace"))
            offset += size
        if len(version) < 3:
            raise AppError("Versione firmware incompleta.")
        self.ensure_disarmed()
        blackbox = self.request(BLACKBOX)
        if len(blackbox) < 2 or not blackbox[0] or blackbox[1] not in (1, 2):
            raise AppError("La FC non segnala una Blackbox su FLASH o SDCARD.")
        firmware = ".".join(str(n) for n in version[:3])
        return Identity(names[1] or names[0] or "Betaflight", firmware, "FLASH" if blackbox[1] == 1 else "SDCARD")

    def ensure_disarmed(self):
        status = self.request(STATUS)
        if len(status) < 10 or struct.unpack_from("<I", status, 6)[0] & 1:
            raise AppError("Disarma il drone prima di accedere ai log.")

    def uid(self):
        value = self.request(UID)
        if len(value) != 12 or not any(value):
            raise AppError("Non riesco a verificare l'identità univoca della FC. Svuotamento bloccato.")
        return value.hex().upper()

    def flash_summary(self):
        data = self.request(FLASH_SUMMARY)
        if len(data) < 13:
            raise AppError("Stato della memoria FLASH incompleto.")
        flags, sectors, capacity, used = struct.unpack_from("<BIII", data)
        if not flags & 2 or not sectors or not capacity or used > capacity:
            raise AppError("La FC non segnala una memoria FLASH Blackbox valida.")
        return {"ready": bool(flags & 1), "capacity": capacity, "used": used}

    def erase_flash(self, uid, capacity, confirmed=False, progress=lambda *_: None, timeout=600):
        if not confirmed:
            raise AppError("Conferma lo svuotamento completo della memoria Blackbox.")
        if self.identify().storage != "FLASH":
            raise AppError("Il comando di cancellazione FLASH non è adatto a questa memoria.")
        if self.uid() != uid:
            raise AppError("La FC è cambiata dopo la conferma. Nessun comando di cancellazione inviato.")
        before = self.flash_summary()
        if before["capacity"] != capacity or not before["ready"]:
            raise AppError("La memoria è cambiata o è occupata. Rileggi lo stato prima di svuotarla.")
        self.ensure_disarmed()
        check_cancel(self.cancel)
        # Dopo l'invio non esiste un comando per annullare un erase hardware.
        # L'eventuale richiesta di annullamento non deve troncare il monitoraggio.
        previous_cancel, self.cancel = self.cancel, None
        try:
            progress("Svuoto la memoria FLASH. Mantieni la FC collegata…", -1)
            self._erase_authorized = True
            try:
                self.request(FLASH_ERASE, timeout=5)
            finally:
                self._erase_authorized = False
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                state = self.flash_summary()
                if state["capacity"] != capacity:
                    raise AppError("La capacità della memoria è cambiata durante la verifica.")
                if state["ready"] and state["used"] == 0:
                    progress("Memoria FLASH vuota: spazio Blackbox interamente disponibile.", 100)
                    return state
                progress("Cancellazione FLASH in corso. Attendo la conferma dalla FC…", -1)
                time.sleep(0.5)
            raise TimeoutError("La FC non ha confermato il termine entro 10 minuti.")
        except Exception as error:
            raise AppError("Svuotamento non verificato. La cancellazione potrebbe essere ancora in corso: mantieni la FC alimentata e verifica lo stato prima di riprovare. " + str(error)) from error
        finally:
            self._erase_authorized = False
            self.cancel = previous_cancel

    def reboot_storage(self):
        try:
            response = self.request(REBOOT, b"\x02")
        except (serial.SerialException, OSError, TimeoutError):
            return  # La comparsa di un nuovo volume è comunque obbligatoria.
        if response != b"\x02\x01":
            raise AppError("La memoria Blackbox non è pronta per la modalità disco USB.")
