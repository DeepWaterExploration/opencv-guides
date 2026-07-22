#!/usr/bin/env python3
"""stellarhd_exposure.py

Minimal standalone control of stellarHD exposure time (shutter) and ISO (analog
gain), extracted from dweOS (backend_py/src/services/cameras/drivers/shd/).

No dependencies beyond the Python stdlib. Replaces dweOS's camera_helper.c with
a direct ctypes ioctl(UVCIOC_CTRL_QUERY).

Usage:
    sudo ./stellarhd_exposure.py --list                        # find cameras
    sudo ./stellarhd_exposure.py /dev/video0 --exposure 800 --iso 400
    sudo ./stellarhd_exposure.py /dev/video0 --exposure-ms 9.0 # same, in ms
    sudo ./stellarhd_exposure.py /dev/video0 --auto            # re-enable AE
    sudo ./stellarhd_exposure.py /dev/video0 --read            # read back values

Notes (mirrors dweOS behavior):
  - Auto exposure (ASIC reg 0x1673) is disabled automatically before any
    manual exposure/ISO write, otherwise AE overwrites your values.
  - Sensor 16-bit values are written high byte first, then low byte, with a
    delay between them (dweOS uses 0.6s — the ASIC's sensor-write bridge is
    slow and the trigger-done register is unreliable). A write therefore takes
    well over half a second; this is not a per-frame control.
  - dweOS reapplies these after every stream start (reapply_sensor_config),
    because restarting the stream resets sensor state. Do the same if you
    stop/start capture.
"""

from __future__ import annotations

import argparse
import ctypes
import fcntl
import struct
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# UVC extension-unit plumbing (replaces camera_helper.c)
# ---------------------------------------------------------------------------

UVC_SET_CUR = 0x01
UVC_GET_CUR = 0x81


class uvc_xu_control_query(ctypes.Structure):
    # From <linux/uvcvideo.h>
    _fields_ = [
        ("unit", ctypes.c_uint8),
        ("selector", ctypes.c_uint8),
        ("query", ctypes.c_uint8),
        ("size", ctypes.c_uint16),
        ("data", ctypes.POINTER(ctypes.c_uint8)),
    ]


# UVCIOC_CTRL_QUERY = _IOWR('u', 0x21, struct uvc_xu_control_query)
def _IOWR(type_char: str, nr: int, size: int) -> int:
    return (3 << 30) | (size << 16) | (ord(type_char) << 8) | nr


UVCIOC_CTRL_QUERY = _IOWR("u", 0x21, ctypes.sizeof(uvc_xu_control_query))

# dweOS: drivers/xu.py
UNIT_SYS_ID = 0x03          # ASIC-level extension unit
SEL_SYS_ASIC_RW = 0x01      # ASIC register read/write selector


class StellarRegisterMap:
    """ASIC registers (dweOS drivers/xu.py)."""
    REG_AE = 0x1673       # auto exposure enable (1) / disable (0)
    REG_ADDR_H = 0x1674   # sensor register address, high byte
    REG_ADDR_L = 0x1675   # sensor register address, low byte
    REG_DATA = 0x1676     # sensor register data
    REG_MODE = 0x1677     # 'W' (0x57) = write, 'R' (0x52) = read
    REG_TRIG = 0x1678     # write 0x55 to execute the queued command


class StellarSensorMap:
    """Sensor registers, accessed through the ASIC bridge (dweOS drivers/xu.py)."""
    SHUTTER_HIGH = 0x3501
    SHUTTER_LOW = 0x3502
    ISO_HIGH = 0x3508
    ISO_LOW = 0x3509


# ---------------------------------------------------------------------------
# Ranges and unit conversion
# ---------------------------------------------------------------------------

# dweOS defaults/ranges (drivers/shd/options.py)
EXPOSURE_MIN, EXPOSURE_MAX, EXPOSURE_DEFAULT = 1, 8000, 100
ISO_MIN, ISO_MAX, ISO_DEFAULT = 0, 4095, 400
SENSOR_WRITE_DELAY_S = 0.6  # delay between high/low byte sensor writes

# One exposure unit is one sensor row. Derived from the fps -> max-exposure
# table dweOS ships in its UI (frontend/.../sensor-controls.ts): 2942 units
# fills a 30 fps frame and 5884 fills a 15 fps frame, i.e. 88254 rows/second.
ROWS_PER_SECOND = 88254
ROW_TIME_US = 1_000_000 / ROWS_PER_SECOND  # ~11.33 us

# Exposure cannot outlast the frame, so framerate sets the real ceiling — far
# below the register's 8000. These are dweOS's own per-framerate limits; the
# 5884 floor at <=15 fps is a sensor limit, not a rounding artifact.
MAX_EXPOSURE_BY_FPS = {
    60: 1462,
    50: 1756,
    40: 2119,
    30: 2942,
    15: 5884,
    10: 5884,
    5: 5884,
}
MAX_EXPOSURE_ABSOLUTE = 5884


def max_exposure_for_fps(fps: float) -> int:
    """Largest exposure value that still fits inside one frame at `fps`."""
    if int(fps) in MAX_EXPOSURE_BY_FPS:
        return MAX_EXPOSURE_BY_FPS[int(fps)]
    return max(EXPOSURE_MIN, min(MAX_EXPOSURE_ABSOLUTE, int(ROWS_PER_SECOND / fps)))


def exposure_to_ms(value: int) -> float:
    """Exposure value (sensor rows) -> milliseconds."""
    return value * ROW_TIME_US / 1000.0


def ms_to_exposure(milliseconds: float) -> int:
    """Milliseconds -> exposure value (sensor rows)."""
    return int(round(milliseconds * 1000.0 / ROW_TIME_US))


# ---------------------------------------------------------------------------
# Device discovery
# ---------------------------------------------------------------------------

# stellarHD entries from dweOS drivers/registry.py
STELLARHD_IDS = {
    (0x0C45, 0x6367): "stellarHD: Leader (legacy VID)",
    (0x0C45, 0x6368): "stellarHD: Follower (legacy VID)",
    (0x3961, 0x1211): "stellarHD Elite (AQ-L)",
    (0x3961, 0x1212): "stellarHD Elite (AQ-F)",
    (0x3961, 0x1201): "stellarHD Elite (L)",
    (0x3961, 0x1202): "stellarHD Elite (F)",
    (0x3961, 0x1111): "stellarHD (AQ-L)",
    (0x3961, 0x1112): "stellarHD (AQ-F)",
    (0x3961, 0x1101): "stellarHD (L)",
    (0x3961, 0x1102): "stellarHD (F)",
    (0x3961, 0x3112): "explore3D (Left)",
    (0x3961, 0x3111): "explore3D (Right)",
}


@dataclass(frozen=True)
class FoundDevice:
    path: str      # /dev/videoN — the capture node, which is also the XU node
    name: str      # human-readable model from the dweOS registry
    vid: int
    pid: int


def _usb_device_dir(node: Path) -> Path | None:
    """Walk up from a video4linux node to the USB device that owns it."""
    candidate = (node / "device").resolve()
    for _ in range(5):
        if (candidate / "idVendor").exists():
            return candidate
        candidate = candidate.parent
    return None


def find_stellarhd() -> list[FoundDevice]:
    """Enumerate every attached stellarHD.

    A stellarHD presents several /dev/video nodes per USB device; only the
    lowest-numbered one is the capture node, and that is the node dweOS talks
    to for extension-unit controls (ASICInterface(self.cameras[0])).
    """
    sysfs = Path("/sys/class/video4linux")
    if not sysfs.is_dir():
        return []

    nodes = sorted(sysfs.glob("video*"), key=lambda p: int(p.name[len("video"):]))

    found: dict[Path, FoundDevice] = {}
    for node in nodes:
        usb_dir = _usb_device_dir(node)
        if usb_dir is None or usb_dir in found:
            continue  # already took this device's first (capture) node

        try:
            vid = int((usb_dir / "idVendor").read_text().strip(), 16)
            pid = int((usb_dir / "idProduct").read_text().strip(), 16)
        except (OSError, ValueError):
            continue

        name = STELLARHD_IDS.get((vid, pid))
        if name is None:
            continue

        found[usb_dir] = FoundDevice(f"/dev/{node.name}", name, vid, pid)

    return list(found.values())


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------


class StellarHD:
    """Condensed ASICInterface (dweOS drivers/shd/asic_interface.py)."""

    def __init__(self, device_path: str) -> None:
        self._file = open(device_path)  # noqa: SIM115 — dweOS opens it the same way
        self._fd = self._file.fileno()

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> StellarHD:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- raw XU query -------------------------------------------------------

    def _xu_query(self, query: int, payload: bytes) -> bytes:
        buf = (ctypes.c_uint8 * len(payload)).from_buffer_copy(payload)
        q = uvc_xu_control_query(
            unit=UNIT_SYS_ID,
            selector=SEL_SYS_ASIC_RW,
            query=query,
            size=len(payload),
            data=ctypes.cast(buf, ctypes.POINTER(ctypes.c_uint8)),
        )
        fcntl.ioctl(self._fd, UVCIOC_CTRL_QUERY, q)  # raises OSError on failure
        return bytes(buf)

    # -- ASIC register access ----------------------------------------------

    def asic_write(self, addr: int, data: int, dummy: bool = False) -> None:
        # payload: u16 asic addr, u8 data, u8 mode (0 = write, 0xFF = dummy
        # write used to latch the address before a read) — little endian
        payload = struct.pack("<HBB", addr, data & 0xFF, 0xFF if dummy else 0x00)
        self._xu_query(UVC_SET_CUR, payload)

    def asic_read(self, addr: int) -> int:
        # dummy write selects the address, then GET_CUR returns the value
        self.asic_write(addr, 0, dummy=True)
        payload = struct.pack("<HBB", addr, 0, 0)
        result = self._xu_query(UVC_GET_CUR, payload)
        return result[2]

    # -- sensor register access (bridged through ASIC regs) -----------------

    def sensor_write(self, reg: int, val: int) -> None:
        self.asic_write(StellarRegisterMap.REG_ADDR_H, (reg >> 8) & 0xFF)
        self.asic_write(StellarRegisterMap.REG_ADDR_L, reg & 0xFF)
        self.asic_write(StellarRegisterMap.REG_DATA, val & 0xFF)
        self.asic_write(StellarRegisterMap.REG_MODE, 0x57)  # 'W'
        self.asic_write(StellarRegisterMap.REG_TRIG, 0x55)  # execute

    def sensor_read(self, reg: int) -> int:
        self.asic_write(StellarRegisterMap.REG_ADDR_H, (reg >> 8) & 0xFF)
        self.asic_write(StellarRegisterMap.REG_ADDR_L, reg & 0xFF)
        self.asic_write(StellarRegisterMap.REG_MODE, 0x52)  # 'R'
        self.asic_write(StellarRegisterMap.REG_TRIG, 0x55)  # execute
        return self.asic_read(StellarRegisterMap.REG_DATA)

    def sensor_write_u16(self, reg_high: int, reg_low: int, value: int,
                         delay_s: float = SENSOR_WRITE_DELAY_S) -> None:
        self.sensor_write(reg_high, (value >> 8) & 0xFF)
        time.sleep(delay_s)  # ASIC bridge needs settling time between writes
        self.sensor_write(reg_low, value & 0xFF)

    def sensor_read_u16(self, reg_high: int, reg_low: int) -> int:
        high = self.sensor_read(reg_high)
        low = self.sensor_read(reg_low)
        return (high << 8) | (low & 0xFF)

    # -- high-level controls (dweOS drivers/shd/options.py) -----------------

    def set_auto_exposure(self, enabled: bool) -> None:
        self.asic_write(StellarRegisterMap.REG_AE, 1 if enabled else 0)

    def get_auto_exposure(self) -> bool:
        return bool(self.asic_read(StellarRegisterMap.REG_AE))

    def set_exposure(self, value: int) -> None:
        """Exposure time in sensor rows (1 row ~ 11.33 us), not milliseconds."""
        value = max(EXPOSURE_MIN, min(EXPOSURE_MAX, int(value)))
        self.sensor_write_u16(
            StellarSensorMap.SHUTTER_HIGH, StellarSensorMap.SHUTTER_LOW, value
        )

    def get_exposure(self) -> int:
        return self.sensor_read_u16(
            StellarSensorMap.SHUTTER_HIGH, StellarSensorMap.SHUTTER_LOW
        )

    def set_iso(self, value: int) -> None:
        """Analog gain, 0-4095. Linear: doubling the value doubles brightness."""
        value = max(ISO_MIN, min(ISO_MAX, int(value)))
        self.sensor_write_u16(
            StellarSensorMap.ISO_HIGH, StellarSensorMap.ISO_LOW, value
        )

    def get_iso(self) -> int:
        return self.sensor_read_u16(
            StellarSensorMap.ISO_HIGH, StellarSensorMap.ISO_LOW
        )

    def apply_manual(self, exposure: int | None = None,
                     iso: int | None = None) -> None:
        """Disable AE, then write exposure and/or ISO.

        This is the whole recipe: AE off first, or the ASIC overwrites your
        values within a frame or two. Call this again after every stream
        restart — dweOS does the same in SHDDevice.reapply_sensor_config().
        """
        self.set_auto_exposure(False)
        time.sleep(0.1)
        if exposure is not None:
            self.set_exposure(exposure)
        if iso is not None:
            self.set_iso(iso)


def main() -> int:
    p = argparse.ArgumentParser(description="stellarHD exposure/ISO control")
    p.add_argument("device", nargs="?", help="/dev/videoN of the stellarHD")
    p.add_argument("--list", action="store_true", help="list attached stellarHD cameras")
    p.add_argument("--exposure", type=int,
                   help=f"exposure time in sensor rows, {EXPOSURE_MIN}-{EXPOSURE_MAX}")
    p.add_argument("--exposure-ms", type=float,
                   help="exposure time in milliseconds (converted to rows)")
    p.add_argument("--iso", type=int, help=f"analog gain, {ISO_MIN}-{ISO_MAX}")
    p.add_argument("--fps", type=float,
                   help="clamp exposure to what fits in a frame at this framerate")
    p.add_argument("--auto", action="store_true", help="re-enable auto exposure")
    p.add_argument("--read", action="store_true", help="read back current values")
    args = p.parse_args()

    if args.list:
        devices = find_stellarhd()
        if not devices:
            print("no stellarHD found", file=sys.stderr)
            return 1
        for dev in devices:
            print(f"{dev.path}  {dev.name}  ({dev.vid:04x}:{dev.pid:04x})")
        return 0

    if not args.device:
        p.error("a device path is required (or use --list)")

    exposure = args.exposure
    if args.exposure_ms is not None:
        exposure = ms_to_exposure(args.exposure_ms)

    if exposure is not None and args.fps:
        ceiling = max_exposure_for_fps(args.fps)
        if exposure > ceiling:
            print(f"clamping exposure {exposure} -> {ceiling} "
                  f"(max at {args.fps:g} fps)", file=sys.stderr)
            exposure = ceiling

    cam = StellarHD(args.device)
    try:
        if args.read:
            value = cam.get_exposure()
            print(f"auto exposure: {cam.get_auto_exposure()}")
            print(f"exposure:      {value} rows ({exposure_to_ms(value):.2f} ms)")
            print(f"iso:           {cam.get_iso()}")
            return 0

        if args.auto:
            cam.set_auto_exposure(True)
            print("auto exposure enabled")
            return 0

        if exposure is None and args.iso is None:
            p.error("nothing to do: pass --exposure/--exposure-ms and/or --iso "
                    "(or --auto / --read / --list)")

        cam.apply_manual(exposure, args.iso)
        if exposure is not None:
            print(f"exposure set to {exposure} rows ({exposure_to_ms(exposure):.2f} ms)")
        if args.iso is not None:
            print(f"iso set to {args.iso}")
        return 0
    except OSError as e:
        print(f"ioctl failed: {e} — is {args.device} the stellarHD, and are you root?",
              file=sys.stderr)
        return 1
    finally:
        cam.close()


if __name__ == "__main__":
    sys.exit(main())
