#!/usr/bin/env python3
from __future__ import annotations

import io
from pathlib import Path
from typing import List

from PIL import Image

from dwvo import DWVOReader


def export_dwvo_to_kitti(
    dwvo_path: Path,
    output_dir: Path,
    start_frame_index: int = 0,
    use_jpeg: bool = False,
):
    dwvo_path = Path(dwvo_path)
    output_dir = Path(output_dir)

    with DWVOReader(dwvo_path) as reader:
        header = reader.header
        if header is None:
            raise ValueError("Failed to read DWVO header")

        n_cams = header.n_cameras
        fps = header.fps or 1

        img_ext = ".jpg" if use_jpeg else ".png"

        # image_0, image_1, ...
        img_dirs = []
        for cam_idx in range(n_cams):
            d = output_dir / f"image_{cam_idx}"
            d.mkdir(parents=True, exist_ok=True)
            img_dirs.append(d)

        times: List[float] = []
        frame_idx = start_frame_index

        try:
            for block in reader.iter_blocks():
                if len(block.video_frames) != n_cams:
                    raise ValueError(
                        f"Timestamp block has {len(block.video_frames)} frames, "
                        f"expected {n_cams}"
                    )

                for cam_idx, frame in enumerate(block.video_frames):
                    out_path = img_dirs[cam_idx] / f"{frame_idx:06d}{img_ext}"

                    if use_jpeg:
                        # Zero-copy: write original MJPEG bytes
                        out_path.write_bytes(frame.data)
                    else:
                        # Decode + re-encode PNG
                        img = Image.open(io.BytesIO(frame.data))
                        img = img.convert("RGB")
                        img.save(out_path)

                # KITTI times.txt: seconds since sequence start
                times.append(frame_idx / float(fps))
                frame_idx += 1
        except EOFError:
            # A recording stopped mid-write ends with a partial block; drop it.
            print(f"Recording ends with an incomplete block at index {frame_idx}, ignoring it")

        # Write times.txt
        # times_path = output_dir / "times.txt"
        # with times_path.open("w") as tf:
        #     for t in times:
        #         tf.write(f"{t:.6f}\n")

        fmt = "JPEG" if use_jpeg else "PNG"
        print(
            f"Export complete ({fmt}): "
            f"{frame_idx - start_frame_index} frames, "
            f"{(frame_idx - start_frame_index) * n_cams} images"
        )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Export DWVO to KITTI-style images + times.txt"
    )
    parser.add_argument("dwvo", type=Path, help="Input DWVO file")
    parser.add_argument("output", type=Path, help="Output directory")
    parser.add_argument(
        "--jpeg",
        action="store_true",
        help="Export JPEG instead of PNG (zero-copy from DWVO MJPEG)",
    )
    parser.add_argument(
        "--start-frame",
        type=int,
        default=0,
        help="Starting frame index (for stitching sequences)",
    )

    args = parser.parse_args()
    export_dwvo_to_kitti(
        args.dwvo,
        args.output,
        start_frame_index=args.start_frame,
        use_jpeg=args.jpeg,
    )
