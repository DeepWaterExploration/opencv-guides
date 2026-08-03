import argparse
import ctypes
import fcntl
import os
import struct
import time

DWE_DEVICE_TAG = 0x9A


class Unit:
    """
    SYS_ID: used for camera controls that are asic level

    USR_ID: used for camera controls that are more user facing
    """

    SYS_ID = 0x03  # Internal controls for the camera's ASIC
    USR_ID = 0x04  # User controls for the camera


class Selector:
    """
    Selectors for the camera extension unit controls
    """

    SYS_ASIC_RW = 0x01
    SYS_FLASH_CTRL = 0x03
    SYS_FRAME_INFO = 0x06
    SYS_H264_CTRL = 0x07
    SYS_MJPG_CTRL = 0x08
    SYS_OSD_CTRL = 0x09
    SYS_MOTION_DETECTION = 0x0A
    SYS_IMG_SETTING = 0x0B
    USR_FRAME_INFO = 0x01
    USR_H264_CTRL = 0x02
    USR_MJPG_CTRL = 0x03
    USR_OSD_CTRL = 0x04
    USR_MOTION_DETECTION = 0x05
    USR_IMG_SETTING = 0x06
    USR_MULTI_STREAM_CTRL = 0x07
    USR_GPIO_CTRL = 0x08
    USR_DYNAMIC_FPS_CTRL = 0x09


class Command:
    """
    Commands for the exploreHD extension unit controls
    """

    H264_BITRATE_CTRL = 0x02
    GOP_CTRL = 0x03
    H264_MODE_CTRL = 0x06


class StellarRegisterMap:
    """
    Map of stellar registers for the ASIC,
    which can be accessed through the SYS_ASIC_RW selector
    """

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
    """
    Map of sensor registers for stellar devices, which can be accessed through the ASIC
    """

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

# If you are having issues with reliability, increase this value
SENSOR_WRITE_DELAY_S = 0.3


def ms_to_row_period(expo_ms: float, vts: int, fps: int):
    rows = round(expo_ms * fps * vts / 1000)
    return max(1, min(rows, vts - 12))


class SHDCamera:
    def __init__(self, path: str):
        self._fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)

        self.update()

    def update(self):
        """Update internal parameters if they have been updated externally"""
        self.fps = self.get_fps()
        self.vts = self.get_vts()
        self.hts = self.get_hts()
        self.exposure = self.get_exposure()

    def close(self):
        os.close(self._fd)

    def get_fps(self) -> float:
        """Current frame rate as reported by the driver (VIDIOC_G_PARM)."""
        parm = v4l2_streamparm(type=V4L2_BUF_TYPE_VIDEO_CAPTURE)
        fcntl.ioctl(self._fd, VIDIOC_G_PARM, parm)
        tpf = parm.parm.capture.timeperframe
        if tpf.numerator == 0:
            raise RuntimeError("driver did not report a frame interval")
        return tpf.denominator / tpf.numerator

    def _xu_query(self, query: int, payload: bytes) -> bytes:
        buf = (ctypes.c_uint8 * len(payload)).from_buffer_copy(payload)
        q = uvc_xu_control_query(
            unit=Unit.SYS_ID,
            selector=Selector.SYS_ASIC_RW,
            query=query,
            size=len(payload),
            data=ctypes.cast(buf, ctypes.POINTER(ctypes.c_uint8)),
        )
        fcntl.ioctl(self._fd, UVCIOC_CTRL_QUERY, q)  # raises OSError on failure
        return bytes(buf)

    def asic_write(self, addr: int, data: int, dummy: bool = False) -> None:
        payload = struct.pack("<HBB", addr, data & 0xFF, 0xFF if dummy else 0x00)
        self._xu_query(UVC_SET_CUR, payload)

    def asic_read(self, addr: int) -> int:
        self.asic_write(addr, 0, dummy=True)
        payload = struct.pack("<HBB", addr, 0, 0)
        result = self._xu_query(UVC_GET_CUR, payload)
        return result[2]

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

        # wait for 0xAA in REG_TRIG
        time.sleep(SENSOR_WRITE_DELAY_S)

        return self.asic_read(StellarRegisterMap.REG_DATA)

    def sensor_write_u16(
        self,
        reg_high: int,
        reg_low: int,
        value: int,
        delay_s: float = SENSOR_WRITE_DELAY_S,
    ) -> None:
        self.sensor_write(reg_high, (value >> 8) & 0xFF)
        time.sleep(delay_s)  # ASIC bridge needs settling time between writes
        self.sensor_write(reg_low, value & 0xFF)

    def sensor_read_u16(self, reg_high: int, reg_low: int) -> int:
        high = self.sensor_read(reg_high)
        low = self.sensor_read(reg_low)
        return (high << 8) | (low & 0xFF)

    def set_auto_exposure(self, enabled: bool) -> None:
        self.asic_write(StellarRegisterMap.REG_AE, 1 if enabled else 0)

    def get_auto_exposure(self) -> bool:
        return bool(self.asic_read(StellarRegisterMap.REG_AE))

    def set_exposure(self, value: int) -> None:
        """Exposure time"""
        exposure_max = self.vts - 12
        exposure_min = 1

        if value < exposure_min:
            print(
                f"Exposure value less than the minimum {exposure_min}, clamping value."
            )
            value = exposure_min
        elif value > exposure_max:
            print(
                f"Exposure value greater than the maximum {exposure_max}, clamping value."
            )
            value = exposure_max

        self.exposure = value

        self.sensor_write_u16(
            StellarSensorMap.SHUTTER_HIGH, StellarSensorMap.SHUTTER_LOW, value
        )

    def get_exposure(self):
        return self.sensor_read_u16(
            StellarSensorMap.SHUTTER_HIGH, StellarSensorMap.SHUTTER_LOW
        )

    def set_strobe_width(self, value: int):
        strobe_max = int(self.exposure * (self.hts / 904))
        strobe_min = 0

        print(f"Strobe max: {strobe_max}")

        if value < strobe_min:
            print(f"Strobe value less than the minimum {strobe_min}, clamping value.")
            value = strobe_min
        elif value > strobe_max:
            print(
                f"Strobe value greater than the maximum {strobe_max}, clamping value."
            )
            value = strobe_max

        self.sensor_write_u16(
            StellarSensorMap.STROBE_WIDTH_HIGH, StellarSensorMap.STROBE_WIDTH_LOW, value
        )

    def get_vts(self):
        return self.sensor_read_u16(StellarSensorMap.VTS_HIGH, StellarSensorMap.VTS_LOW)

    def get_hts(self):
        return self.sensor_read_u16(StellarSensorMap.HTS_HIGH, StellarSensorMap.HTS_LOW)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="stellarHD Sensor Control",
        description="Interface with the stellarHD sensor controls",
    )
    parser.add_argument("device", nargs="?", default="/dev/video6")
    parser.add_argument("--auto-exposure", action="store_true", default=False)
    parser.add_argument("--manual-exposure", action="store_true", default=True)
    parser.add_argument("--get-exposure", action="store_true")
    parser.add_argument("--set-exposure", type=int)
    parser.add_argument("--set-strobe-width", type=int)
    args = parser.parse_args()

    stellar = SHDCamera(args.device)

    if args.auto_exposure:
        stellar.set_auto_exposure(True)
    if args.manual_exposure:
        stellar.set_auto_exposure(False)

    if args.get_exposure:
        print(stellar.get_exposure())
    if args.set_exposure is not None:
        stellar.set_exposure(args.set_exposure)
        print(f"exposure set to {args.set_exposure}")

    if args.set_strobe_width is not None:
        stellar.set_strobe_width(args.set_strobe_width)
        print(f"strobe width set to {args.set_strobe_width}")
