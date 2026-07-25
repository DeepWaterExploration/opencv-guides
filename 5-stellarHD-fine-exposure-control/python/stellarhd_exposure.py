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

class v4l2_fract(ctypes.Structure):
    _fields_ = [("numerator", ctypes.c_uint32), ("denominator", ctypes.c_uint32)]


class v4l2_captureparm(ctypes.Structure):
    _fields_ = [
        ("capability", ctypes.c_uint32),
        ("capturemode", ctypes.c_uint32),
        ("timeperframe", v4l2_fract),
        ("extendedmode", ctypes.c_uint32),
        ("readbuffers", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 4),
    ]

class v4l2_streamparm(ctypes.Structure):
    class _u(ctypes.Union):
        _fields_ = [("capture", v4l2_captureparm), ("raw_data", ctypes.c_uint8 * 200)]

    _fields_ = [("type", ctypes.c_uint32), ("parm", _u)]

# UVCIOC_CTRL_QUERY = _IOWR('u', 0x21, struct uvc_xu_control_query)
def _IOWR(type_char: str, nr: int, size: int) -> int:
    return (3 << 30) | (size << 16) | (ord(type_char) << 8) | nr

V4L2_BUF_TYPE_VIDEO_CAPTURE = 1
VIDIOC_G_PARM = _IOWR("V", 21, ctypes.sizeof(v4l2_streamparm))


class uvc_xu_control_query(ctypes.Structure):
    # From <linux/uvcvideo.h>
    _fields_ = [
        ("unit", ctypes.c_uint8),
        ("selector", ctypes.c_uint8),
        ("query", ctypes.c_uint8),
        ("size", ctypes.c_uint16),
        ("data", ctypes.POINTER(ctypes.c_uint8)),
    ]


UVCIOC_CTRL_QUERY = _IOWR("u", 0x21, ctypes.sizeof(uvc_xu_control_query))

# dweOS: drivers/xu.py
UNIT_SYS_ID = 0x03          # ASIC-level extension unit
SEL_SYS_ASIC_RW = 0x01      # ASIC register read/write selector


class StellarRegisterMap:
    """ASIC registers (dweOS drivers/xu.py)."""
    REG_AE = 0x1673
    REG_ADDR_H = 0x1674
    REG_ADDR_L = 0x1675
    REG_DATA = 0x1676
    REG_MODE = 0x1677
    REG_TRIG = 0x1678
    REG_STROBE_ENABLED = 0x8100
    REG_HW_BITRATE_HIGH = 0x2D6
    REG_HW_BITRATE_LOW = 0x2D7
    REG_HW_BITRATE_TRIG = 0x2DB


class StellarSensorMap:
    """Sensor registers, accessed through the ASIC bridge (dweOS drivers/xu.py)."""
    SHUTTER_HIGH = 0x3501
    SHUTTER_LOW = 0x3502
    ISO_HIGH = 0x3508
    ISO_LOW = 0x3509
    STROBE_WIDTH_HIGH = 0x3927
    STROBE_WIDTH_LOW = 0x3928
    VTS_HIGH = 0x380E
    VTS_LOW = 0x380F
    HTS_HIGH = 0x380C
    HTS_LOW = 0x380D


# ---------------------------------------------------------------------------
# Ranges and unit conversion
# ---------------------------------------------------------------------------

# dweOS defaults/ranges (drivers/shd/options.py)
EXPOSURE_MIN, EXPOSURE_MAX, EXPOSURE_DEFAULT = 1, 8000, 100
ISO_MIN, ISO_MAX, ISO_DEFAULT = 0, 4095, 400
SENSOR_WRITE_DELAY_S = 0.6  # delay between high/low byte sensor writes

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
    return 0


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

        self.fps = self.get_fps()
        print(f"Camera FPS: {self.fps}")
        self.max_exposure = max_exposure_for_fps(self.fps);
        self.min_exposure = 1

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> StellarHD:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def get_fps(self) -> float:
        """Current frame rate as reported by the driver (VIDIOC_G_PARM)."""
        parm = v4l2_streamparm(type=V4L2_BUF_TYPE_VIDEO_CAPTURE)
        fcntl.ioctl(self._fd, VIDIOC_G_PARM, parm)
        tpf = parm.parm.capture.timeperframe
        if tpf.numerator == 0:
            raise RuntimeError("driver did not report a frame interval")
        return tpf.denominator / tpf.numerator

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
        """Exposure time"""
        value = max(self.min_exposure, min(self.max_exposure, int(value)))
        self.sensor_write_u16(
            StellarSensorMap.SHUTTER_HIGH, StellarSensorMap.SHUTTER_LOW, value
        )

    def get_exposure(self) -> int:
        return self.sensor_read_u16(
            StellarSensorMap.SHUTTER_HIGH, StellarSensorMap.SHUTTER_LOW
        )

    def set_strobe_width(self, value: int) -> None:
        """
        Strobe width. Max value should be the current exposure, but reading current exposure can be unreliable,
        so this is up to the user to represent properly.
        """
        if self.get_auto_exposure() and value != 0:
            print("[ERROR] Cannot set strobe width to a nonzero value when auto exposure is enabled!");

        value = max(0, min(EXPOSURE_MAX, int(value)))
        self.sensor_write_u16(
            StellarSensorMap.STROBE_WIDTH_HIGH, StellarSensorMap.STROBE_WIDTH_LOW, value
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
                   help=f"exposure time, {EXPOSURE_MIN}-{EXPOSURE_MAX}")
    p.add_argument("--iso", type=int, help=f"sensor gain, {ISO_MIN}-{ISO_MAX}")
    p.add_argument("--auto", action="store_true", help="re-enable auto exposure")
    p.add_argument("--strobe", type=int, help="set the strobe width")
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

    cam = StellarHD(args.device)
    try:
        if args.auto:
            cam.set_auto_exposure(True)
            cam.set_strobe_width(0)
            print("auto exposure enabled")
            return 0

        if exposure is None and args.iso is None:
            p.error("nothing to do: pass --exposure and/or --iso "
                    "(or --auto / --read / --list)")

        cam.apply_manual(exposure, args.iso)
        if exposure is not None:
            print(f"exposure set to {exposure}")
        if args.iso is not None:
            print(f"iso set to {args.iso}")

        if args.strobe:
            print(f"strobe width set to {args.iso}")
            cam.set_strobe_width(args.strobe)

        return 0
    except OSError as e:
        print(f"ioctl failed: {e} — is {args.device} the stellarHD, and are you root?",
              file=sys.stderr)
        return 1
    finally:
        cam.close()


if __name__ == "__main__":
    sys.exit(main())
