#!/usr/bin/env python3
"""Bracket exposure or gain, and report which value exposed the scene best.

Point the camera at the scene you actually have to shoot, run this, then read
the table and look at the frames it writes to out/. This is how you pick values
for a light regime nobody has published numbers for.

    sudo python sweep.py         # step exposure, hold gain
    sudo python sweep.py iso     # step gain, hold exposure
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

from stellarhd_exposure import (
    ISO_MAX,
    StellarHD,
    exposure_to_ms,
    find_stellarhd,
    max_exposure_for_fps,
)

# --- edit these ------------------------------------------------------------

DEVICE = None       # "/dev/video0", or None to auto-detect
FPS = 30
STEPS = 10          # how many values to try
HELD_EXPOSURE = 2000  # used while sweeping iso
HELD_ISO = 400        # used while sweeping exposure
OUTDIR = Path("out")

# ---------------------------------------------------------------------------

# A pixel at or above CLIPPED is blown out; at or below CRUSHED it holds no
# detail that gain can bring back. The percentages of each are the fastest read
# on whether an exposure is right.
CLIPPED = 250
CRUSHED = 10


def measure(frame) -> tuple[float, float, float]:
    """Return (mean luma, % clipped, % crushed) for one frame."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    total = gray.size
    return (
        float(gray.mean()),
        100.0 * int(np.count_nonzero(gray >= CLIPPED)) / total,
        100.0 * int(np.count_nonzero(gray <= CRUSHED)) / total,
    )


def main() -> int:
    control = sys.argv[1] if len(sys.argv) > 1 else "exposure"
    if control not in ("exposure", "iso"):
        print(f"usage: {sys.argv[0]} [exposure|iso]", file=sys.stderr)
        return 1

    path = DEVICE
    if path is None:
        found = find_stellarhd()
        if not found:
            print("no stellarHD found — set DEVICE at the top of this file",
                  file=sys.stderr)
            return 1
        path = found[0].path

    top = max_exposure_for_fps(FPS) if control == "exposure" else ISO_MAX
    values = [int(v) for v in np.linspace(top // STEPS, top, STEPS)]

    cap = cv2.VideoCapture(path, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    cap.set(cv2.CAP_PROP_FPS, FPS)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if not cap.isOpened():
        print(f"could not open {path} for capture", file=sys.stderr)
        return 1

    OUTDIR.mkdir(exist_ok=True)

    try:
        camera = StellarHD(path)
    except OSError as e:
        print(f"could not open {path} for control: {e} — try sudo", file=sys.stderr)
        cap.release()
        return 1

    held = HELD_ISO if control == "exposure" else HELD_EXPOSURE
    print(f"sweeping {control} over {values}")
    print(f"holding {'iso' if control == 'exposure' else 'exposure'} at {held}, "
          f"{FPS} fps, ~{STEPS * 3} seconds\n")
    print(f"{control:>9} {'ms':>7} {'mean':>7} {'clip%':>7} {'crush%':>7}  file")

    results = []
    with camera:
        # AE off and the held control applied once, up front.
        camera.apply_manual(
            exposure=None if control == "exposure" else HELD_EXPOSURE,
            iso=None if control == "iso" else HELD_ISO,
        )

        for value in values:
            if control == "exposure":
                camera.set_exposure(value)
            else:
                camera.set_iso(value)

            # A write blocks for over a second with nothing draining the queue,
            # so throw away everything waiting for us before measuring.
            for _ in range(12):
                cap.grab()
            ok, frame = cap.read()
            if not ok:
                print("frame read failed, stopping", file=sys.stderr)
                break

            mean, clipped, crushed = measure(frame)
            results.append((value, mean, clipped))

            name = f"sweep_{control}_{value:05d}.jpg"
            cv2.imwrite(str(OUTDIR / name), frame)
            ms = exposure_to_ms(value if control == "exposure" else HELD_EXPOSURE)
            print(f"{value:>9} {ms:>7.2f} {mean:>7.1f} {clipped:>7.1f} "
                  f"{crushed:>7.1f}  {name}")

    cap.release()

    if results:
        # The brightest setting that has not started blowing highlights is
        # usually what you want on a fixed-exposure rig.
        usable = [r for r in results if r[2] < 1.0]
        if usable:
            best = max(usable, key=lambda r: r[1])
            print(f"\nbrightest setting under 1% clipping: {control} = {best[0]}")
        else:
            print("\neverything clipped — the scene is brighter than this range, "
                  f"lower {'iso' if control == 'exposure' else 'exposure'} and rerun")
        print(f"frames written to {OUTDIR}/ — look at them, not just the numbers")

    return 0


if __name__ == "__main__":
    sys.exit(main())
