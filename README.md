# showroom-fetcher

A simple desktop GUI for fetching [SHOWROOM](https://www.showroom-live.com) live stream URLs and launching them in VLC.

## Features

- Fetch all available streams (HLS, WebRTC) by room URL or key
- Expands HLS adaptive streams into individual quality options with bitrate, resolution, frame rate, and codec info
- One-click copy URL or open in VLC per stream

## Requirements

- Python 3
- [VLC](https://www.videolan.org/vlc/)

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install requests m3u8 PyQt5
```

## Usage

```bash
python fetcher.py
```

Enter a room URL or key, e.g.:

- `https://www.showroom-live.com/r/ROOM_KEY`
- `ROOM_KEY`

Click **Fetch**, then use the **VLC** button on any stream row to start playback, or **Copy URL** to use with another player.
