# Reading DWVO Recordings

`.dwvo` is DWE's multi-camera recording container. The payload is MJPEG, so every frame in
the file is already a complete JPEG: playback is `cv2.imdecode`, and export is a byte copy.

```
DWE.ai | header: nCameras, width, height, pixelFormat, fps | ext data
block:   uint32 timestamp | per camera: busID\0, uint32 length, JPEG bytes
block:   ...
```

## Setup

```bash
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Playback dwvo file

All cameras side by side in one OpenCV window.

```bash
python main.py test.dwvo
python main.py test.dwvo --fps 60 --loop
```

| argument | |
|---|---|
| `--fps N` | Playback rate. Defaults to the header's fps. |
| `--loop` | Restart at the end of the file. |
| `space` | Pause / resume. |
| `q` / `esc` | Quit. |

## Export DWVO to JPEGs

```bash
python export.py file.dwvo output-folder

# only keeps every fifth frame
python export.py file.dwvo output-folder --step 5
```

| | |
|---|---|
| `--step N` | Keep every Nth frame. |
| `--start-frame N` | First output index, to continue numbering from an earlier sequence. |

Output is one directory per camera, numbered KITTI-style:

```
out/
  image_0/000000.jpg, 000001.jpg, ...
  image_1/000000.jpg, 000001.jpg, ...
  times.txt
```

## Output to Kitti Dataset

Same layout, but decodes through Pillow so it can emit lossless PNG. Use it when a
downstream tool won't take JPEG; otherwise `export.py` is faster.

```bash
python dwvo_to_kitti.py test.dwvo out          # PNG
python dwvo_to_kitti.py test.dwvo out --jpeg   # same JPEG copy as export.py
```

## DWVO Structure

In `dwvo.py`, the `DWVOReader` iterates timestamp blocks, `DWVOWriter` writes them, and `combine_dwvos()`
concatenates recordings that share a header.

```python
from dwvo import DWVOReader

with DWVOReader(Path("test.dwvo")) as reader:
    print(reader.header.n_cameras, reader.header.width, reader.header.height)
    for block in reader.iter_blocks():
        for frame in block.video_frames:   # one per camera
            frame.bus_id, frame.data       # "0" / "1", raw JPEG bytes
```

## FAQ

### Why is the video slower than what I recorded?

In Discovery for Desktop, some cameras require setting the FPS manually. If it was set to 30FPS, when the video was streamed at 60FPS, the DWVO File will contain 30FPS in the metadata, and tell applications to read at 30FPS.
