"""
Raylogic GO Protocol - multi-device driver (H81 8-channel dimmer panels).

Original single-device driver (192.168.120.100:5550, Living Room panel) ab
generalize kar diya gaya hai taaki MULTIPLE H81 panels ek saath configure ho
saken. Har panel ke liye configuration.yaml mein sirf 4 cheezein deni hoti
hain: ip, port, start_address, aur (optional) area/device_id/name. Baaki sab
- jaise 8 channel numbers - is file mein khud calculate ho jaata hai.

============================================================
START ADDRESS KYA HAI AUR YE NETWORK SE AUTO-DISCOVER KYU NAHI HO SAKTA
============================================================
Har H81 panel apna "Start address" khud store karta hai (Raylogic GO app mein
Device Info screen pe dikhta hai, jaise "Start address: 0x0101"). Isi address
se panel ke 8 channels ka number range decide hota hai (0x0101 = 257 se
0x0108 = 264 tak, jaisa aapke Living Room panel mein hai).

Official Raylogic GO Protocol v0.4 PDF ke "QUERY DEVICE" section ke mutabik,
kisi bhi device se uska status query karne ke liye command khud bhi start
address maangta hai as INPUT (?AR40=<start address>) - matlab address pehle
se pata hona zaroori hai, koi "scan/discover" command protocol mein exist
nahi karta. Isliye ye value ek baar Raylogic GO app ke Device Info screen se
(ya Docklight capture se) leke config mein daalni padegi - us ke baad har
cheez (8 channel numbers, unke hex address bytes) khud-ba-khud calculate ho
jayegi, dobara kabhi manually nahi likhni padegi.

============================================================
Command format (Docklight capture se confirmed, is TCP-HUB/gateway ka apna
wrapper hai - official PDF mein sirf "*AR=..." hota hai, ye "<ID>,<SeqNo>,"
prefix isी hub/gateway software ka hai):

    <ID>,<SeqNo>,*AR=<AddrHigh><Cmd:1A><Area><Level><AddrLow><CR>

Example (Living Room panel, Docklight se confirmed):
    002,005,*AR=011A020101\r   -> Channel 0x0101 (257 / "D1") ko ON  (level 01)
    002,006,*AR=011A02FF01\r   -> Channel 0x0101 (257 / "D1") ko OFF (level FF)

Dimming scale (official PDF se confirmed + real calibration table):
    Level 0x01        = 100% (maximum brightness)
    Level 0x02..0xFE   = beech ki brightness, ULTA scale (bada number = dim)
    Level 0xFF        = OFF (alag command hai, "0% dim" nahi)
"""

from __future__ import annotations

import json
import logging
import re
import socket
import threading
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

# ============================================================
# Protocol-level constants (saare H81 panels ke liye common)
# ============================================================
CMD_CHANNEL_DIRECT = "1A"
LEVEL_ON = "01"            # full/max brightness (PDF confirms 0x01 = max)
LEVEL_OFF = "FF"           # OFF (alag command hai, dimmest level nahi)

CHANNELS_PER_DEVICE = 8    # H81 = 8-channel dimmer panel

TIMEOUT = 3
KEEPALIVE_CMD = b"*KA=1\r"
KEEPALIVE_INTERVAL = 5     # seconds - Docklight se confirmed idle-timeout avoid karne ke liye

SEQ_MIN = 1
SEQ_MAX = 999              # device sirf 3-digit sequence field accept karta hai

# Har device ka apna sequence-number aur listener state - HA restart ke
# baad bhi yaad rahe, isliye per-device file mein persist karte hain.
_STATE_DIR = Path(__file__).parent / "device_state"
_STATE_DIR.mkdir(exist_ok=True)


# ============================================================
# START ADDRESS -> 8 CHANNEL NUMBERS (yehi cheez khud calculate hoti hai)
# ============================================================
def parse_start_address(value: int | str) -> int:
    """
    Raylogic GO app ke "Start address" field ko decimal channel-base number
    mein convert karo. Ye teeno formats accept karta hai (jo bhi aap app ke
    screen se copy karke config mein daalo):

        0x0101   -> 257   (app jaisa dikhata hai)
        "0101"   -> 257   (bina "0x" prefix ke hex)
        257      -> 257   (seedha decimal, agar aapne pehle se convert kar
                            liya ho - jaise online hex-to-decimal tool se)
    """
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text.lower().startswith("0x"):
        return int(text, 16)
    # Agar sirf digits hain aur 3+ digit ka number hai (jaise "257"), to
    # decimal maano - warna (jaise "0101", "101") hex maano, kyunki app ka
    # start address hamesha hex hi dikhata hai.
    if re.fullmatch(r"[0-9]+", text) and int(text) > 255:
        return int(text)
    return int(text, 16)


def channels_for_start_address(value: int | str) -> list[int]:
    """
    Start address se panel ke saare 8 channel numbers nikaalo, sequentially
    +1 karte hue (jaise Living Room panel: 257, 258, ... 264).
    """
    base = parse_start_address(value)
    return [base + i for i in range(CHANNELS_PER_DEVICE)]


def _channel_to_hex(channel: int) -> tuple[str, str]:
    """
    Channel number (decimal, jaise 257) ko address high/low byte mein todo.
    257 -> 0x0101 -> high="01", low="01"
    264 -> 0x0108 -> high="01", low="08"
    """
    addr = channel & 0xFFFF
    high = (addr >> 8) & 0xFF
    low = addr & 0xFF
    return f"{high:02X}", f"{low:02X}"


# ============================================================
# CALIBRATION TABLE - real Docklight capture se banaya gaya (NOT a linear
# guess). Mobile app ke slider ko continuously 0% se 100% tak drag karke
# capture kiya gaya tha. Ye saare H81 panels ke liye same firmware curve
# maani ja rahi hai (agar koi panel alag behave kare to iski calibration
# alag se karni padegi).
#
# Key = percent (0-100), Value = device level byte (int, 1-255)
_LEVEL_CALIBRATION: dict[int, int] = {
    0: 0xFF,
    1: 0xFC, 2: 0xFA, 3: 0xFA, 4: 0xFA, 5: 0xF7, 6: 0xEB, 7: 0xEB, 8: 0xE8,
    9: 0xE6, 10: 0xE3, 11: 0xE3, 12: 0xE2, 13: 0xE0, 14: 0xDF, 15: 0xDD,
    16: 0xDC, 17: 0xDA, 18: 0xD8, 19: 0xD6, 20: 0xD4, 21: 0xD2, 22: 0xD0,
    23: 0xCF, 24: 0xCC, 25: 0xCC, 26: 0xCB, 27: 0xCA, 28: 0xCA, 29: 0xC7,
    30: 0xC5, 31: 0xC5, 32: 0xC5, 33: 0xC5, 34: 0xC5, 35: 0xC5, 36: 0xC2,
    37: 0xC2, 38: 0xC0, 39: 0xBC, 40: 0xB9, 41: 0xB5, 42: 0xB1, 43: 0xAE,
    44: 0xAA, 45: 0xA8, 46: 0xA4, 47: 0xA1, 48: 0x9D, 49: 0x99, 50: 0x96,
    51: 0x92, 52: 0x8C, 53: 0x85, 54: 0x85, 55: 0x85, 56: 0x85, 57: 0x78,
    58: 0x78, 59: 0x76, 60: 0x73, 61: 0x62, 62: 0x5F, 63: 0x5F, 64: 0x52,
    65: 0x52, 66: 0x52, 67: 0x52, 68: 0x52, 69: 0x50, 70: 0x50, 71: 0x4B,
    72: 0x48, 73: 0x41, 74: 0x3E, 75: 0x3E, 76: 0x3E, 77: 0x39, 78: 0x39,
    79: 0x39, 80: 0x39, 81: 0x31, 82: 0x2C, 83: 0x2A, 84: 0x2A, 85: 0x2A,
    86: 0x26, 87: 0x22, 88: 0x20, 89: 0x1D, 90: 0x1A, 91: 0x15, 92: 0x14,
    93: 0x10, 94: 0x0F, 95: 0x0B, 96: 0x0B, 97: 0x0A, 98: 0x09, 99: 0x01,
    100: 0x01,
}

_LEVEL_TO_PERCENT_SORTED: list[tuple[int, int]] = sorted(
    ((lvl, pct) for pct, lvl in _LEVEL_CALIBRATION.items()), reverse=True
)


def _level_hex(level_percent: int) -> str:
    """0-100% ko device ki level byte mein convert karo (calibration table se)."""
    if level_percent <= 0:
        return LEVEL_OFF
    if level_percent >= 100:
        return LEVEL_ON
    level_percent = max(1, min(99, round(level_percent)))
    scaled = _LEVEL_CALIBRATION[level_percent]
    return f"{scaled:02X}"


def _level_hex_to_percent(level_hex: str) -> int:
    """Device se aayi level byte ko wapas 0-100% mein convert karo (reverse lookup)."""
    try:
        value = int(level_hex, 16)
    except ValueError:
        return 0
    if value >= 0xFF:
        return 0
    if value <= 1:
        return 100
    best_pct = 1
    best_diff = None
    for lvl, pct in _LEVEL_TO_PERCENT_SORTED:
        diff = abs(lvl - value)
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best_pct = pct
    return max(1, min(99, best_pct))


def _parse_incoming(frame_text: str) -> tuple[int, int] | None:
    """Ek raw incoming line parse karo - "*AR=..." ya "+AR=..." dono handle karta hai."""
    frame_text = frame_text.strip()
    if not frame_text:
        return None

    hex_part = None
    for prefix in ("*AR=", "+AR="):
        idx = frame_text.find(prefix)
        if idx == -1:
            continue
        candidate = frame_text[idx + len(prefix):].strip()
        if len(candidate) >= 10:
            hex_part = candidate[:10]
            break
    if hex_part is None:
        return None

    high, cmd, area, level, low = (
        hex_part[0:2],
        hex_part[2:4],
        hex_part[4:6],
        hex_part[6:8],
        hex_part[8:10],
    )
    if cmd.upper() != CMD_CHANNEL_DIRECT:
        return None
    try:
        channel = (int(high, 16) << 8) | int(low, 16)
    except ValueError:
        return None
    level_percent = _level_hex_to_percent(level)
    return channel, level_percent


# ============================================================
# RaylogicDevice - ek physical H81 panel = ek TCP connection, apna sequence
# counter, apne listeners. Multiple panels ke liye ye class multiple baar
# instantiate hoti hai (ek-ek IP:port ke liye).
# ============================================================
class RaylogicDevice:
    def __init__(
        self,
        ip: str,
        port: int,
        area: str = "02",
        device_id: int = 2,
        name: str = "",
    ) -> None:
        self.ip = ip
        self.port = port
        self.area = area
        self.device_id = device_id
        self.name = name or f"Raylogic H81 {ip}"
        self.key = f"{ip.replace('.', '_')}_{port}"

        self._sock: socket.socket | None = None
        self._conn_lock = threading.Lock()
        self._keepalive_started = False
        self._receiver_started = False
        self._recv_buf = b""

        self._seq_lock = threading.Lock()
        self._seq_file = _STATE_DIR / f"{self.key}_seq.json"

        self._listener_lock = threading.Lock()
        self._listeners: dict[int, list] = {}

    # -------------------- sequence number (per-device) --------------------
    def _load_seq(self) -> int:
        try:
            data = json.loads(self._seq_file.read_text())
            seq = int(data.get("seq", SEQ_MIN))
            if seq < SEQ_MIN or seq > SEQ_MAX:
                seq = SEQ_MIN
            return seq
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            return SEQ_MIN

    def _save_seq(self, seq: int) -> None:
        try:
            self._seq_file.write_text(json.dumps({"seq": seq}))
        except OSError as err:
            _LOGGER.warning("Raylogic H81 [%s]: sequence save fail: %s", self.name, err)

    def _next_seq(self) -> int:
        with self._seq_lock:
            seq = self._load_seq()
            next_seq = seq + 1 if seq < SEQ_MAX else SEQ_MIN
            self._save_seq(next_seq)
            return seq

    # -------------------- connection --------------------
    def _connect_locked(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = socket.create_connection((self.ip, self.port), timeout=TIMEOUT)
        self._sock.settimeout(TIMEOUT)
        self._recv_buf = b""
        _LOGGER.debug("Raylogic H81 [%s]: TCP connection (re)established to %s:%s", self.name, self.ip, self.port)

    def _ensure_background_threads(self) -> None:
        if not self._keepalive_started:
            self._keepalive_started = True
            threading.Thread(target=self._keepalive_loop, daemon=True).start()
        if not self._receiver_started:
            self._receiver_started = True
            threading.Thread(target=self._receiver_loop, daemon=True).start()

    def ensure_started(self) -> None:
        """Connection + background threads ready karo (idempotent, safe to call multiple times)."""
        with self._conn_lock:
            if self._sock is None:
                try:
                    self._connect_locked()
                except OSError as err:
                    _LOGGER.warning("Raylogic H81 [%s]: initial connect fail (retry hoga): %s", self.name, err)
            self._ensure_background_threads()

    def _keepalive_loop(self) -> None:
        while True:
            threading.Event().wait(KEEPALIVE_INTERVAL)
            try:
                self.send(KEEPALIVE_CMD, is_keepalive=True)
            except OSError as err:
                _LOGGER.debug("Raylogic H81 [%s]: keep-alive failed: %s", self.name, err)

    def send(self, payload: bytes, is_keepalive: bool = False) -> None:
        with self._conn_lock:
            if self._sock is None:
                self._connect_locked()
                self._ensure_background_threads()
            try:
                self._sock.sendall(payload)
            except OSError as err:
                if not is_keepalive:
                    _LOGGER.warning("Raylogic H81 [%s]: send fail (%s), reconnecting", self.name, err)
                self._connect_locked()
                self._sock.sendall(payload)

    def _receiver_loop(self) -> None:
        while True:
            with self._conn_lock:
                if self._sock is None:
                    try:
                        self._connect_locked()
                    except OSError:
                        sock = None
                    else:
                        sock = self._sock
                else:
                    sock = self._sock

            if sock is None:
                threading.Event().wait(2)
                continue

            try:
                data = sock.recv(4096)
            except socket.timeout:
                continue
            except OSError as err:
                _LOGGER.debug("Raylogic H81 [%s]: receive error, reconnect: %s", self.name, err)
                with self._conn_lock:
                    if self._sock is sock:
                        try:
                            self._connect_locked()
                        except OSError:
                            pass
                threading.Event().wait(1)
                continue

            if not data:
                _LOGGER.debug("Raylogic H81 [%s]: connection closed (peer), reconnect", self.name)
                with self._conn_lock:
                    if self._sock is sock:
                        try:
                            self._connect_locked()
                        except OSError:
                            pass
                threading.Event().wait(1)
                continue

            self._recv_buf += data
            while b"\r" in self._recv_buf:
                frame, self._recv_buf = self._recv_buf.split(b"\r", 1)
                self._handle_incoming(frame)

    def _handle_incoming(self, frame_bytes: bytes) -> None:
        try:
            text = frame_bytes.decode("ascii", errors="ignore")
        except Exception:  # noqa: BLE001
            return
        parsed = _parse_incoming(text)
        if parsed is None:
            return
        channel, level_percent = parsed
        _LOGGER.debug("Raylogic H81 [%s] <- channel %s level %s%%", self.name, channel, level_percent)
        self._dispatch(channel, level_percent)

    # -------------------- commands --------------------
    def _build_command(self, channel: int, level_percent: int) -> tuple[str, bytes]:
        high, low = _channel_to_hex(channel)
        level = _level_hex(level_percent)
        seq = self._next_seq()
        cmd = f"{self.device_id:03d},{seq:03d},*AR={high}{CMD_CHANNEL_DIRECT}{self.area}{level}{low}"
        return cmd, (cmd.encode("ascii") + b"\r")

    def set_channel_level(self, channel: int, level_percent: int) -> None:
        """light.py yeh function call karega har ON/OFF/brightness change pe."""
        cmd_str, payload = self._build_command(channel, level_percent)
        _LOGGER.debug("Raylogic H81 [%s] -> %s", self.name, cmd_str)
        self.send(payload)

    # -------------------- listeners (mobile-app feedback sync) --------------------
    def register_listener(self, channel: int, callback) -> None:
        with self._listener_lock:
            self._listeners.setdefault(channel, []).append(callback)

    def unregister_listener(self, channel: int, callback) -> None:
        with self._listener_lock:
            callbacks = self._listeners.get(channel)
            if callbacks and callback in callbacks:
                callbacks.remove(callback)
                if not callbacks:
                    self._listeners.pop(channel, None)

    def _dispatch(self, channel: int, level_percent: int) -> None:
        with self._listener_lock:
            callbacks = list(self._listeners.get(channel, ()))
        for cb in callbacks:
            try:
                cb(level_percent)
            except Exception as err:  # noqa: BLE001
                _LOGGER.exception(
                    "Raylogic H81 [%s]: listener callback fail channel %s: %s", self.name, channel, err
                )


# ============================================================
# Device registry - IP:port ke hisaab se ek hi RaylogicDevice reuse hota hai
# (agar same panel ke multiple channels/entities hon, sab isi ek connection
# ko share karte hain - alag-alag socket nahi kholte).
# ============================================================
_devices: dict[str, RaylogicDevice] = {}
_devices_lock = threading.Lock()


def get_device(ip: str, port: int, area: str = "02", device_id: int = 2, name: str = "") -> RaylogicDevice:
    """Is ip:port ke liye RaylogicDevice do - pehli baar call hone par naya banta hai."""
    key = f"{ip.replace('.', '_')}_{port}"
    with _devices_lock:
        dev = _devices.get(key)
        if dev is None:
            dev = RaylogicDevice(ip, port, area=area, device_id=device_id, name=name)
            _devices[key] = dev
        return dev
