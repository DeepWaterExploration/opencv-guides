# Fine Exposure Control on stellarHD

Fixed exposure time with a capped analog gain, set directly on the sensor.

The stellarHD's real exposure controls do not live in V4L2. They live behind a UVC
extension unit that bridges to the image sensor's own registers, which is why
`v4l2-ctl` gets you nowhere and why this guide exists. Everything here is lifted from
the dweOS driver (`backend_py/src/services/cameras/drivers/shd/`) and reduced to two
files with no dependency on dweOS itself.

| file | |
|---|---|
| `python/sweep.py` | Finds good values for a scene by bracketing. |
| `python/stellarhd_exposure.py` | The control layer everything else calls. |

## Quick Start

```bash
cd python
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

venv/bin/python main.py
```

### Framerate is a hard ceiling on exposure

The exposure has to fit inside one frame, so your framerate caps it long before the
register's nominal max of 8000 does. These are dweOS's own limits:

| fps | max exposure (rows) |
|---|---|
| 60 | 1462 |
| 50 | 1756 |
| 40 | 2119 |
| 30 | 2942 |
| ≤ 15 | 5884 |

### Gain

The ISO control writes the sensor's **analog gain**. The register accepts up to 4095, but that is a
register limit, not a usable one.

## Recommended Starting Parameters

Run `sweep.py` and pick from your own numbers.

### On the maximum analog gain

There is no single number the sensor enforces, so pick the cap from what the footage is
for:

The order of operations that gets the most out of a fixed-exposure rig:

1. Set the framerate you actually need, not the highest one available. This sets your
   exposure ceiling and it is free light.
2. Push exposure as high as motion blur allows.
3. Only then raise gain, up to your cap.
4. If you are still dark at the cap, you need more light or a lower framerate. Nothing
   in software fixes it from here.


## As a CLI:

```bash
sudo python stellarhd_exposure.py --list
sudo python stellarhd_exposure.py /dev/video0 --exposure 2000 --iso 400 --fps 30
sudo python stellarhd_exposure.py /dev/video0 --auto
sudo python stellarhd_exposure.py /dev/video0 --exposure 2000 --iso 400 --strobe 100 --fps 30 # strobe
```

**NOTE**: The maximum strobe should be set to the current exposure, values higher will not have any added effect.

## Finding Values for Your Scene

`sweep.py` is the answer to "what numbers should I use in *my* water". Point the camera
at the scene you actually have to shoot and run:

```bash
sudo python sweep.py         # step exposure, hold gain (recommended)
sudo python sweep.py iso     # step gain, hold exposure
```

It walks one control across its usable range, saves a frame per step to `out/`, and
prints a table:

```
 exposure      ms    mean   clip%  crush%  file
      294    3.33    31.4     0.0    41.2  sweep_exposure_00294.jpg
      588    6.66    58.9     0.0    12.8  sweep_exposure_00588.jpg
      882   10.00    84.1     0.2     3.1  sweep_exposure_00882.jpg
     ...

brightest setting under 1% clipping: exposure = 2059
```

Three numbers tell you whether an exposure is right:

| | |
|---|---|
| `mean` | Overall level. Roughly 90 – 130 on a scene with a normal spread. |
| `clip%` | Pixels at 250+, blown out. Under 1 % is fine; sand, silt and lights go first. |
| `crush%` | Pixels at 10 or below. That detail is gone and gain will not bring it back. |

Look at the frames too, not just the table — it cannot tell you about motion blur, or
whether the thing that is clipping is the thing you care about. Run it once per light
regime you expect to work in, keep the values, and switch between them in flight.

## Using the Control Layer Directly

If you have your own capture pipeline, this is all you need from here:

```python
from stellarhd_exposure import StellarHD, find_stellarhd

device = find_stellarhd()[0]

with StellarHD(device.path) as cam:
    cam.apply_manual(exposure=2000, iso=400)   # AE off, then both values
    cam.set_strobe_width(100)
```

`apply_manual()` is the whole recipe: AE off, brief settle, then the writes. Call it
again after any stream restart.


## FAQ

### My values get overwritten a second after I set them.

ASIC auto exposure is still on. Turn it off before writing, not after —
`apply_manual()` and the CLI both do this. Note this is *not* the same control as the
V4L2 `auto_exposure`; turning that one off does not stop the ASIC AE loop.

### My values reset when I start streaming with dweOS.

Expected. Starting a stream resets sensor state. Apply after opening capture, and
re-apply after every restart. dweOS does this in `reapply_sensor_config()`. Use the API if you have dweOS active. Please contact support for information on the dweOS API.

### I have a leader/follower pair and only one camera changed.

Each camera in a PrecisionSync™ pair is a separate USB device with its own sensor
registers. Sync applies to frame timing, not to exposure settings. Run
`stellarhd_exposure.py --list`, then set both nodes to the same values — otherwise your
stereo pair is photometrically mismatched, which will hurt disparity and stitching.

### Which `/dev/videoN`?

The camera presents several nodes; only the lowest-numbered one per USB device is the
capture node, and that is also the node that answers extension-unit queries. Use `--list` to automatically find the correct camera devices.

### dweOS is running and fighting me for control.

It will. dweOS re-applies its own saved values on stream start. Either stop the dweOS
service before using these scripts, or set your values through the dweOS UI/API and let
it own the camera. Do not run both against the same camera.

### `ioctl failed: [Errno 1] Operation not permitted`

Not root, or not the right node. Check with `--list`.

### Can I change exposure per frame?

No. A write takes over half a second because of the ASIC bridge settle time. Treat these
as per-scene settings, not a per-frame control loop. If you need frame-rate adaptation,
ASIC AE is the only thing fast enough — the trade is that you give up determinism.

## Troubleshooting

For issues with the code here, open an [issue](https://github.com/DeepwaterExploration/OpenCV-Quickstart/issues).
