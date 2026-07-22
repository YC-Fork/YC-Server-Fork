# YC-Server-Fork (v2.00.001)

The backend server for **Youcube** in Minecraft ComputerCraft. It processes music, videos, live streams, and radio broadcasts and sends audio/video chunks to in-game clients.

Pairs with [YC-Client-Fork](https://github.com/YC-Fork/YC-Client-Fork).

---

## Features

- **Multi-Source Playback**: Supports YouTube, Spotify, Twitch, Radio streams (e.g. Qmusic / Radio 538), and direct media links.
- **Web Admin Dashboard**:
  - View connected clients, IP addresses, current playing track, and mode.
  - **Interactive Progress Bar**: Hover over the progress bar to see exact timestamps (e.g. `2:35`), and click anywhere on the bar to seek.
  - **Quick Action Icons**:
    - 🔗 **Source**: Open media link
    - 📋 **Queue**: View & edit queue
    - 🔄 **Restart**: Replay current song from `0:00`
    - ⏭ **Skip**: Next song
    - ⏹ **Stop**: Stop playback
    - 👤❌ **Kick**: Disconnect client
  - **Volume Slider**: Adjust client volume remotely from `0%` to `100%`.
- **Live Stream Detection**: Displays a `🔴 LIVE STREAM` badge and disables seek bars for live broadcasts.
- **Synced Timers**: Dashboard progress bar and in-game client clock stay in perfect sync.

---

## Requirements

- Python 3.7+
- Node.js (for YouTube challenges)
- FFmpeg (for audio/video encoding)
- Sanjuuni (optional, required only for video rendering)

---

## Quick Start

1. **Clone repository**:
   ```bash
   git clone https://github.com/YC-Fork/YC-Server-Fork
   cd YC-Server-Fork
   ```

2. **Install Python packages**:
   ```bash
   pip install -r src/requirements.txt
   ```

3. **Edit settings**: Open `config.json` to change default settings or enable the admin panel.

4. **Run server**:
   ```bash
   python src/youcube/ycf-server.py
   ```

---

## Configuration (`config.json`)

- `server_settings`:
  - `host`: Host IP (default: `"0.0.0.0"`).
  - `port`: Port number (default: `5000`).
  - `admin_panel_web`:
    - `enabled`: Set to `true` to enable web dashboard.
    - `password`: Change default login password.
    - `url_prefix`: Dashboard path (default: `"/admin"`).
- `spotify`:
  - `client_id` & `client_secret`: Spotify API credentials (optional).

---

## Web Dashboard Access

Once enabled in `config.json`, open `http://<your-server-ip>:5000/admin` in your browser.

---

## Client Setup
For the Minecraft ComputerCraft client installer:
https://github.com/YC-Fork/YC-Client-Fork
