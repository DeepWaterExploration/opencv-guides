# stellarHD Sensor Control

A command-line tool / library to set the exposure and the strobe width on a stellarHD camera.

## What it does

The camera exposes the image sensor through a UVC video device. This tool
opens that device and reads or writes four sensor values:

- exposure
- strobe width
- VTS (frame length)
- HTS (row length)

The tool reads the frame rate, VTS, HTS, and the current exposure when it starts.
It uses those values to calculate the limits for any value that you set.

## Requirements

- Linux
- Python 3
- Read and write permission on the video device

No external Python packages are necessary.

## Use

```
python3 stellar.py [device] [options]
```

The device defaults to `/dev/video6`. Give a different path as the first argument
if the camera is on another node.

### Options

| Option                 | Effect                                       |
| ---------------------- | -------------------------------------------- |
| `--auto-exposure`      | Turn on auto exposure.                       |
| `--manual-exposure`    | Turn off auto exposure. This is the default. |
| `--get-exposure`       | Print the current exposure in row periods.   |
| `--set-exposure N`     | Set the exposure to N row periods.           |
| `--set-strobe-width N` | Set the strobe width to N steps.             |

### Examples

Read the current exposure:

```
python3 stellar.py /dev/video6 --get-exposure
```

Set the exposure and then the strobe width:

```
python3 stellar.py /dev/video6 --set-exposure 500
python3 stellar.py /dev/video6 --set-strobe-width 500
```

## The values

### Exposure

The exposure is a count of row periods, not milliseconds. One row period is the
time the sensor needs to read one row. That time changes with the video mode.

The limits are:

- minimum: 1
- maximum: VTS minus 12

VTS changes with the video mode. At VTS 1474 the maximum exposure is 1462.

The tool clamps any value outside these limits and prints a message.

The `ms_to_row_period` function converts milliseconds to row periods. It needs
the exposure in milliseconds, the VTS, and the frame rate. The command line does
not call this function. Import it if you want to work in milliseconds.

### Strobe width

The strobe width sets how long the strobe output stays on. The strobe fires
inside the exposure window, so a longer exposure allows a longer strobe.

The maximum is:

```
exposure * (HTS / 904)
```

The 904 is the HTS of the fastest video mode. The strobe counter measures in
steps of that fixed length. Slower modes have a longer HTS, so each row of
exposure covers more strobe steps. The ratio corrects for the difference.

The tool clamps any value above the maximum and prints the maximum.

A value below the maximum is valid. Use a shorter strobe to limit the heat or
the duty cycle of the light.

## Order of operations

Set the exposure before you set the strobe width. The tool calculates the strobe
maximum from the exposure value that it holds in memory. A separate run of the
tool reads the exposure again from the sensor, so a two-command sequence is safe.

## Known behavior

- `--manual-exposure` defaults to true. It runs after `--auto-exposure` and turns
  auto exposure off again. Edit the argument defaults if you want auto exposure
  to stay on.
- The tool waits 0.3 seconds between sensor writes. Increase
  `SENSOR_WRITE_DELAY_S` if writes fail or reads return the wrong value.
