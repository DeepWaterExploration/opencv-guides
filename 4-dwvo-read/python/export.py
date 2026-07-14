#!/usr/bin/env python3
"""Export every frame of a .dwvo recording to JPEG files.

DWVO stores MJPEG, and an MJPEG payload is already a complete JPEG file, so
exporting is a byte copy -- no decode/re-encode, no quality loss.

Output layout (one directory per camera, KITTI-style numbering):

    out/
      image_0/000000.jpg, 000001.jpg, ...
      image_1/000000.jpg, 000001.jpg, ...
      times.txt

`dwvo_to_kitti.py` produces the same layout and can additionally write PNGs
(via Pillow); this script is the dependency-free JPEG path.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from dwvo import DWVOReader

# fourcc stored in the header as a little-endian uint32
MJPG = int.from_bytes(b"MJPG", "little")


def fourcc_to_str(pixel_format: int) -> str:
    return pixel_format.to_bytes(4, "little").decode("ascii", errors="replace")


def export_jpegs(dwvo_path: Path, output_dir: Path, step: int = 1, start_frame: int = 0):
    with DWVOReader(dwvo_path) as reader:
        header = reader.header

        if header.pixel_format != MJPG:
            raise SystemExit(
                f"Only MJPG recordings can be exported byte-for-byte, got "
                f"{fourcc_to_str(header.pixel_format)}"
            )

        fps = header.fps or 30

        # image_0, image_1, ... one per camera
        cam_dirs = []
        for cam_idx in range(header.n_cameras):
            d = output_dir / f"image_{cam_idx}"
            d.mkdir(parents=True, exist_ok=True)
            cam_dirs.append(d)

        times = []
        written = 0
        block_idx = 0

        try:
            for block_idx, block in enumerate(reader.iter_blocks()):
                # --step 5 keeps every 5th frame
                if block_idx % step:
                    continue

                frame_idx = start_frame + written

                for cam_idx, frame in enumerate(block.video_frames):
                    out_path = cam_dirs[cam_idx] / f"{frame_idx:06d}.jpg"
                    out_path.write_bytes(frame.data)

                # KITTI times.txt: seconds since the start of the sequence
                times.append(block_idx / float(fps))
                written += 1
        except EOFError:
            # A recording stopped mid-write ends with a partial block; drop it.
            print(f"Recording ends with an incomplete block at index {block_idx}, ignoring it")

        (output_dir / "times.txt").write_text(
            "".join(f"{t:.6f}\n" for t in times)
        )

        print(
            f"Wrote {written} frames x {header.n_cameras} camera(s) "
            f"= {written * header.n_cameras} JPEGs to {output_dir}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export DWVO frames as JPEGs")
    parser.add_argument("dwvo", nargs="?", type=Path, default=Path("test.dwvo"),
                        help="Input DWVO file (default: test.dwvo)")
    parser.add_argument("output", nargs="?", type=Path, default=Path("out"),
                        help="Output directory (default: out)")
    parser.add_argument("--step", type=int, default=1,
                        help="Keep every Nth frame (default: 1, keep all)")
    parser.add_argument("--start-frame", type=int, default=0,
                        help="First output index, for stitching sequences together")

    args = parser.parse_args()
    export_jpegs(args.dwvo, args.output, step=args.step, start_frame=args.start_frame)
