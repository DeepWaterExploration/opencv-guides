# Python RTP H.264 to OpenCV Decoder

A lightweight, cross-platform starter project to receive H.264-encoded video via raw RTP/UDP packets and decode them into OpenCV-compatible frames.

## Features
- **Raw RTP/UDP**: No GStreamer or external dependencies required.
- **High Resolution**: Optimized for 1080p 30fps+ streams.
- **10-bit Support**: Handles 10-bit YUV 4:4:4 (yuv444p10le) and standard 8-bit formats.
- **Low Latency**: Uses a background receiver thread and multi-threaded decoding.
- **Modular Design**: Separates network handling, decoding, and display logic.

## Prerequisites
- Python 3.8+
- [FFmpeg](https://ffmpeg.org/) libraries (usually installed automatically via PyAV)

## Installation
1. Create a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage
1. Start your H.264 RTP stream (defaulting to `127.0.0.1:5600`).
2. Run the receiver:
   ```bash
   python main.py
   ```

## Project Structure
- `rtp_receiver.py`: Handles raw UDP packet reception and H.264 NAL reassembly (including FU-A and STAP-A).
- `h264_decoder.py`: Wraps PyAV for high-performance H.264 decoding.
- `main.py`: The main entry point that connects the receiver and decoder to an OpenCV window.
