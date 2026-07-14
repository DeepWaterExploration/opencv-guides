#!/usr/bin/env python3
"""Play back a .dwvo recording in an OpenCV window.

A DWVO file is a header followed by timestamp blocks. Each block holds one
compressed frame per camera, so playback is: read block -> decode each frame
-> show them side by side.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import cv2
import numpy as np

from dwvo import DWVOReader

# fourcc stored in the header as a little-endian uint32 (e.g. 'MJPG')
MJPG = int.from_bytes(b"MJPG", "little")

# how wide the combined (all cameras) window may get, in pixels
MAX_WINDOW_WIDTH = 1600

# used when the header carries no usable fps
DEFAULT_FPS = 30

WINDOW = "DWVO"


def fourcc_to_str(pixel_format: int) -> str:
    return pixel_format.to_bytes(4, "little").decode("ascii", errors="replace")


def decode_frame(data: bytes) -> np.ndarray | None:
    """MJPEG payloads are complete JPEGs, so OpenCV can decode them as-is."""
    img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    return img


def make_mosaic(images: list[np.ndarray]) -> np.ndarray:
    """Stack every camera horizontally and scale to fit MAX_WINDOW_WIDTH."""
    mosaic = np.hstack(images)

    if mosaic.shape[1] > MAX_WINDOW_WIDTH:
        scale = MAX_WINDOW_WIDTH / mosaic.shape[1]
        mosaic = cv2.resize(mosaic, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    return mosaic


def play(dwvo_path: Path, fps: float | None = None) -> bool:
    """Play the file once. Returns False if the user asked to quit."""
    with DWVOReader(dwvo_path) as reader:
        header = reader.header

        print(
            f"{dwvo_path.name}: {header.n_cameras} camera(s), "
            f"{header.width}x{header.height}, "
            f"{fourcc_to_str(header.pixel_format)} @ {header.fps} fps (header)"
        )

        if header.pixel_format != MJPG:
            raise SystemExit(
                f"Only MJPG recordings are supported, got "
                f"{fourcc_to_str(header.pixel_format)}"
            )

        # The header's fps is set by hand at record time and is not always right,
        # so --fps overrides it.
        fps = fps or header.fps or DEFAULT_FPS
        frame_time = 1.0 / fps
        print(f"Playing at {fps:g} fps ({frame_time * 1000:.1f} ms/frame)")

        cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)

        paused = False
        frame_idx = 0
        dropped = 0

        # Every frame is shown at start + frame_idx * frame_time. Anchoring the
        # schedule to a fixed origin (instead of sleeping a whole frame_time after
        # each decode) keeps decode + display time inside the frame budget rather
        # than adding to it.
        start = time.monotonic()

        try:
            for frame_idx, block in enumerate(reader.iter_blocks()):
                deadline = start + frame_idx * frame_time

                # Behind by a full frame already: skip this one rather than decode
                # it late and fall further behind. Playback stays at wall-clock speed.
                if time.monotonic() > deadline + frame_time and not paused:
                    dropped += 1
                    continue

                images = [decode_frame(frame.data) for frame in block.video_frames]

                # a dropped/corrupt frame in the recording decodes to None
                if any(img is None for img in images):
                    print(f"frame {frame_idx}: failed to decode, skipping")
                    continue

                cv2.imshow(WINDOW, make_mosaic(images))

                # imshow only paints during waitKey, so we always pump it at least
                # once, then spend whatever is left of the frame budget waiting.
                while True:
                    remaining_ms = int((deadline - time.monotonic()) * 1000)
                    key = cv2.waitKey(30 if paused else max(1, remaining_ms)) & 0xFF

                    if key in (ord("q"), 27):  # q / esc
                        return False
                    if key == ord(" "):
                        paused = not paused
                        if not paused:
                            # shift the schedule forward by however long we sat paused
                            start = time.monotonic() - frame_idx * frame_time

                    if not paused and time.monotonic() >= deadline:
                        break

                # a slow first frame (window creation) shouldn't count as being behind
                if frame_idx == 0:
                    start = time.monotonic()
        except EOFError:
            # A recording stopped mid-write ends with a partial block; drop it.
            print("Recording ends with an incomplete block, ignoring it")

        elapsed = time.monotonic() - start
        shown = frame_idx + 1 - dropped
        print(
            f"End of file: {frame_idx + 1} frames in {elapsed:.1f}s "
            f"({shown / elapsed:.1f} fps shown, {dropped} dropped to keep pace)"
        )
        return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Play a DWVO recording with OpenCV")
    parser.add_argument("dwvo", nargs="?", type=Path, default=Path("test.dwvo"),
                        help="Input DWVO file (default: test.dwvo)")
    parser.add_argument("--fps", type=float, default=None,
                        help="Playback frame rate. Overrides the header's fps field, "
                             "which is set by hand at record time and is often wrong.")
    parser.add_argument("--loop", action="store_true", help="Restart at the end of the file")

    args = parser.parse_args()

    try:
        while play(args.dwvo, fps=args.fps) and args.loop:
            pass
    finally:
        cv2.destroyAllWindows()
