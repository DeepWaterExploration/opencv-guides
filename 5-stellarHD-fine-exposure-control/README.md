# Fine Exposure Control on stellarHD

Fixed exposure time with a capped analog gain, set directly on the sensor.

The stellarHD's real exposure controls do not live in V4L2. They live behind a UVC
extension unit that bridges to the image sensor's own registers, which is why
`v4l2-ctl` gets you nowhere and why this guide exists. Everything here is lifted from
the dweOS driver (`backend_py/src/services/cameras/drivers/shd/`) and reduced to two
files with no dependency on dweOS itself.

| file | |
|---|---|
| `python/main.py` | Capture with exposure and gain locked. Start here. |
| `python/sweep.py` | Finds good values for a scene by bracketing. |
| `python/stellarhd_exposure.py` | The control layer everything else calls. Stdlib only. |

## Quick Start

```bash
cd python
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

sudo venv/bin/python main.py
```

Register access is an `ioctl` on the video node, so it needs root. If you launch
through `sudo python`, make sure it is the venv's interpreter — `sudo` resets `PATH`.

## Why `v4l2-ctl` Did Not Work

This is the most common report we get, and the controls really are not reachable that
way. Three separate reasons stack up:

1. **The standard controls drive the wrong block.** `exposure_time_absolute`,
   `auto_exposure` and `gain` do appear in `v4l2-ctl --list-ctrls`, but on stellarHD
   they are handled by the ASIC's own auto-exposure engine, not by the sensor. dweOS
   labels this entire group **"Legacy Exposure Controls"** in its UI for exactly this
   reason. Writing them gives you a nudge, not a fixed exposure time.

2. **The real controls are extension-unit registers.** Exposure and analog gain are
   sensor registers (`0x3501/0x3502` and `0x3508/0x3509`) reached through an ASIC
   register bridge on UVC extension unit `0x03`, selector `0x01`. `v4l2-ctl` has no
   path to a vendor XU register bridge. You need
   `ioctl(fd, UVCIOC_CTRL_QUERY, ...)`, which is what `stellarhd_exposure.py` does.

3. **Auto exposure overwrites you.** Even once you can write the sensor, the ASIC AE
   loop (register `0x1673`) will overwrite your values within a frame or two. It has to
   be turned off *first*. `apply_manual()` does this for you.

There is a fourth trap that catches people after they get the writes working:
**starting a stream resets sensor state.** dweOS re-applies every sensor option after
each `start_stream()` (`SHDDevice.reapply_sensor_config`). Do the same — open your
capture first, *then* write exposure and gain, and rewrite them any time you stop and
restart capture. `main.py` is ordered this way deliberately.

## The Units — Read This Before Picking Numbers

**Exposure is in sensor rows, not milliseconds and not the 100 µs units that
`v4l2-ctl`'s `exposure_time_absolute` uses.**

One row is **≈ 11.33 µs**. So:

```
exposure_ms  =  value × 0.01133
value        =  exposure_ms × 88.25
```

This is the single most likely cause of an image that looks far too dark. If you came
from `v4l2-ctl` and typed `100` expecting 10 ms, you got **1.13 ms** — nine times
darker than you intended. That is what "exposure time set too low" means when we say
it; it is a unit mismatch, not a broken camera. The fix is to raise exposure, not to
crank gain, because gain cannot recover photons the sensor never collected.

### Framerate is a hard ceiling on exposure

The exposure has to fit inside one frame, so your framerate caps it long before the
register's nominal max of 8000 does. These are dweOS's own limits:

| fps | max exposure (rows) | ≈ ms | frame period |
|---|---|---|---|
| 60 | 1462 | 16.6 | 16.7 ms |
| 50 | 1756 | 19.9 | 20.0 ms |
| 40 | 2119 | 24.0 | 25.0 ms |
| 30 | 2942 | 33.3 | 33.3 ms |
| ≤ 15 | 5884 | 66.7 | — |

Two consequences worth planning around:

- **Dropping from 60 to 30 fps buys you a full stop of light** and costs nothing else.
  If you are light-starved, do this before you touch gain.
- Below 15 fps the ceiling stops moving. 5884 rows / 66.7 ms is the longest exposure
  available; running at 5 fps does not get you a longer one.

`main.py` and `sweep.py` clamp to this for you, and the CLI does when you pass `--fps`.

### Gain

The ISO control writes the sensor's **analog gain** registers (`0x3508/0x3509`). dweOS
does not write digital gain at all, so capping this one value caps the entire gain
chain — which is what you want if you are trying to keep noise bounded.

It is linear: doubling the value doubles brightness and adds ~6 dB. dweOS's shipped
default is **400**, and that is the most useful reference point to reason from — treat
400 as 1×, 800 as 2×, 1600 as 4×. The register accepts up to 4095, but that is a
register limit, not a usable one.

## Recommended Starting Parameters

**These are starting points, not calibrated values.** Water clarity, light placement,
lens port and target range move them around more than anything we can predict from
here. Use them as the middle of a bracket, then run `sweep.py` (below) and pick from
your own numbers. All rows assume 30 fps unless noted.

| Scene | fps | exposure | ≈ ms | ISO |
|---|---|---|---|---|
| Surface, direct sun | 30 | 200 – 600 | 2.3 – 6.8 | 100 – 200 |
| Surface, overcast / shade | 30 | 600 – 1200 | 6.8 – 13.6 | 200 – 400 |
| Clear water < 5 m, ambient only | 30 | 1200 – 2000 | 13.6 – 22.7 | 400 |
| Turbid or 5 – 20 m, ambient + lights | 30 | 2000 – 2942 | 22.7 – 33.3 | 400 – 800 |
| Lights only, close range < 2 m | 30 | 1500 – 2500 | 17 – 28 | 400 – 800 |
| Lights only, mid range | 30 | 2942 (max) | 33.3 | 800 – 1600 |
| No ambient, slow survey | 15 | 4000 – 5884 | 45 – 67 | 1600 – 2400 |

If you want one line to start from and adjust: **30 fps, exposure 2000, ISO 400.**

### On the maximum analog gain

There is no single number the sensor enforces, so pick the cap from what the footage is
for:

| cap | when |
|---|---|
| **800** (2× default) | Photogrammetry, feature tracking, anything where the noise floor becomes false detail. |
| **1600** (4× default) | General inspection and pilot video. Noise is visible on flat surfaces but detail survives. This is a good default ceiling. |
| **2400** (6× default) | Last resort for a scene you would otherwise not see at all. Expect chroma noise and mushy texture. |
| above 2400 | Not recommended. You are amplifying read noise; longer exposure or more light is the only real fix. |

The order of operations that gets the most out of a fixed-exposure rig:

1. Set the framerate you actually need, not the highest one available. This sets your
   exposure ceiling and it is free light.
2. Push exposure as high as motion blur allows (see below).
3. Only then raise gain, up to your cap.
4. If you are still dark at the cap, you need more light or a lower framerate. Nothing
   in software fixes it from here.

### Motion blur — how high can exposure go

Blur in pixels, for a 1920-wide frame:

```
blur_px  ≈  1920 × (relative_speed_m_s × exposure_s) / scene_width_m
```

At 30 fps with exposure at the 33 ms ceiling, a vehicle closing at 0.3 m/s across a
2 m-wide scene smears about **10 px**. Fine for pilot video, too much for feature
matching. Halve the exposure to 1500 rows and it drops to 5 px, but you have given up a
stop and have to find it in gain.

This trade is the whole reason to fix exposure manually instead of leaving AE on: AE
does not know how fast you are moving or what you are going to do with the frames.

## Running the Example

`main.py` opens the camera, locks exposure and gain, and shows the result. There are no
command-line flags — the four values you would change are constants at the top of the
file:

```python
DEVICE = None     # "/dev/video0", or None to auto-detect
FPS = 30          # also caps EXPOSURE: 2942 at 30 fps, 1462 at 60
EXPOSURE = 2000   # sensor rows, ~11.33 us each, so 2000 is ~22.7 ms
ISO = 400         # analog gain
```

Edit those, then:

```bash
sudo python main.py     # q or esc to quit
```

The whole program is about thirty lines of actual work. Everything interesting is in the
one call that locks the camera down:

```python
camera.apply_manual(exposure=2000, iso=400)
```

Give it a couple of seconds to take effect. That is the hardware, not the script: a
16-bit sensor write is two register writes with a 0.6 s settle between them. Expect an
odd-looking frame or two during a change, when the high byte has landed and the low byte
has not. For the same reason this is a per-scene setting, not something to drive from a
control loop.

## Finding Values for Your Scene

`sweep.py` is the answer to "what numbers should I use in *my* water". Point the camera
at the scene you actually have to shoot and run:

```bash
sudo python sweep.py         # step exposure, hold gain
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
    print(cam.get_exposure(), cam.get_iso())
```

`apply_manual()` is the whole recipe: AE off, brief settle, then the writes. Call it
again after any stream restart.

As a CLI:

```bash
sudo python stellarhd_exposure.py --list
sudo python stellarhd_exposure.py /dev/video0 --exposure 2000 --iso 400 --fps 30
sudo python stellarhd_exposure.py /dev/video0 --exposure-ms 22.7 --iso 400
sudo python stellarhd_exposure.py /dev/video0 --read
sudo python stellarhd_exposure.py /dev/video0 --auto
```

## FAQ

### My values get overwritten a second after I set them.

ASIC auto exposure is still on. Turn it off before writing, not after —
`apply_manual()` and the CLI both do this. Note this is *not* the same control as the
V4L2 `auto_exposure`; turning that one off does not stop the ASIC AE loop.

### My values reset when I start streaming.

Expected. Starting a stream resets sensor state. Apply after opening capture, and
re-apply after every restart. dweOS does this in `reapply_sensor_config()`.

### I have a leader/follower pair and only one camera changed.

Each camera in a PrecisionSync™ pair is a separate USB device with its own sensor
registers. Sync applies to frame timing, not to exposure settings. Run
`stellarhd_exposure.py --list`, then set both nodes to the same values — otherwise your
stereo pair is photometrically mismatched, which will hurt disparity and stitching.

### Which `/dev/videoN`?

The camera presents several nodes; only the lowest-numbered one per USB device is the
capture node, and that is also the node that answers extension-unit queries.
`--list` and `main.py`'s auto-detection both already pick it.

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

### Where do these numbers come from?

The register maps and the 0.6 s settle time are from the dweOS driver
(`drivers/xu.py`, `drivers/shd/asic_interface.py`, `drivers/shd/options.py`). The row
time of 11.33 µs is derived from the per-framerate exposure limits dweOS ships in its UI
(`frontend/src/components/dwe/cameras/stream/sensor-controls.ts`), which work out to
88,254 sensor rows per second — consistent to within rounding across every framerate in
that table.

## Troubleshooting

> :warning: ***Our customer service does not provide technical support for this
> repository.***

For issues with the code here, open an [issue](https://github.com/DeepwaterExploration/OpenCV-Quickstart/issues).
