#!/usr/bin/env python3
"""Show a stellarHD stream with exposure time and analog gain locked.

Set the four values below, run it, look at the picture. That is the whole
program — all the register work lives in stellarhd_exposure.py.

    sudo python main.py

Root is required: these controls are ioctls on the video node, not V4L2
properties. See the README for how to pick values, and sweep.py for a tool that
finds them for you.
"""

from __future__ import annotations

import sys

import cv2

from stellarhd_exposure import (
    StellarHD,
    exposure_to_ms,
    find_stellarhd,
    max_exposure_for_fps,
)

# --- edit these ------------------------------------------------------------

DEVICE = None     # "/dev/video0", or None to auto-detect
FPS = 30          # also caps EXPOSURE: 2942 at 30 fps, 1462 at 60. See README.
EXPOSURE = 2000   # sensor rows, ~11.33 us each, so 2000 is ~22.7 ms
ISO = 400         # analog gain. 400 is the dweOS default, 1600 a sane ceiling.

# ---------------------------------------------------------------------------

WINDOW = "stellarHD"


def open_stream(path: str) -> cv2.VideoCapture:
    """Open the MJPEG stream. FOURCC has to be set before the frame size."""
    cap = cv2.VideoCapture(path, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    cap.set(cv2.CAP_PROP_FPS, FPS)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


def label_frame(frame, text: str) -> None:
    """Draw text with a black underlay so it survives a bright scene."""
    for color, thickness in ((0, 0, 0), 5), ((255, 255, 255), 2):
        cv2.putText(frame, text, (16, 44), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                    color, thickness, cv2.LINE_AA)


def main() -> int:
    path = DEVICE
    if path is None:
        found = find_stellarhd()
        if not found:
            print("no stellarHD found — set DEVICE at the top of this file",
                  file=sys.stderr)
            return 1
        path = found[0].path
        print(f"using {path} ({found[0].name})")

    # Exposure has to fit inside one frame, so the framerate caps it.
    exposure = min(EXPOSURE, max_exposure_for_fps(FPS))
    if exposure < EXPOSURE:
        print(f"EXPOSURE {EXPOSURE} does not fit in a frame at {FPS} fps, "
              f"using {exposure}")

    cap = open_stream(path)
    if not cap.isOpened():
        print(f"could not open {path} for capture", file=sys.stderr)
        return 1

    try:
        camera = StellarHD(path)
    except OSError as e:
        print(f"could not open {path} for control: {e} — try sudo", file=sys.stderr)
        cap.release()
        return 1

    text = f"exposure {exposure} = {exposure_to_ms(exposure):.1f} ms   iso {ISO}"

    with camera:
        # Order matters: the stream is open first. Starting a stream resets
        # sensor state, so exposure and gain go on afterwards, never before.
        print(f"applying {text} — takes a couple of seconds")
        camera.apply_manual(exposure=exposure, iso=ISO)

        for _ in range(10):
            cap.grab()  # drop frames captured while the write was in flight

        print("press q to quit")
        while True:
            ok, frame = cap.read()
            if not ok:
                print("frame read failed — camera unplugged?", file=sys.stderr)
                break

            label_frame(frame, text)
            cv2.imshow(WINDOW, cv2.resize(frame, (1280, 720)))

            if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                break

    cap.release()
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
