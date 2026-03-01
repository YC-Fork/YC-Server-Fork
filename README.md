# Youcube server Fork
This is a fork of the original Youcube server. This is an continuation of the original project since i really liked being able to play music, videos etc in minecraft.
This fork has lots of new features and is a lot more stable.

### Features that were in the original project
- Music playing from multiple sources but not live. 
- Video+Audio playing from multiple sources. 

### Additional Features
- Radio stations support, live streams support from youtube, twitch, etc. 
- Server-sided command system for more control.
- Lots and lots of bug fixes.

## Requirements

- FFmpeg / FFmpeg 5.1+
- Node.js
- sanjuuni (Optional for video output)
- Python 3.7+
  - sanic
  - yt-dlp
  - spotipy
  - yt-dlp-ejs

If you have `pip` installed the python requirements are installed by following the instructions below. 
Ffmpeg and node.js are required, so install them first. There is a script for Debian/Ubuntu in `scripts/install_sanjuuni_debian.sh`.

## Getting started

1. Clone the project into a folder you want:

   ```shell
   git clone https://github.com/YC-Fork/YC-Server-Fork
   ```

2. Install Python requirements:

   ```shell
   pip install -r src/requirements.txt
   ```

3. Install Node.js (required for some yt-dlp JS challenges if you use YouTube).
4. Adjust values in `config.json` in the project root.
5. Run the server:

   ```shell
   python src/youcube/ycf-server.py
   ```

## Configuration

The server reads optional settings from `config.json` in the project root.

- `cookie_file`: Optional path to a `cookies.txt` file for yt-dlp.
- `js_runtimes.node.path`: Optional path to a Node.js binary for yt-dlp JS challenges.
- `spotify.client_id`: Optional Spotify client ID. If `null` or empty, falls back to env variable `SPOTIPY_CLIENT_ID`.
- `spotify.client_secret`: Optional Spotify client secret. If `null` or empty, falls back to env variable `SPOTIPY_CLIENT_SECRET`.
- `spotify.market`: Optional market/region for Spotify lookups. Default is `NL`.

## Debian: Install Sanjuuni (32vid)

Sanjuuni is required for video output. On Debian/Ubuntu it needs to be built from source.

Run this script on your Debian box:

```bash
bash scripts/install_sanjuuni_debian.sh
```

If `sanjuuni` is not on your `PATH`, set:

```bash
export SANJUUNI_PATH=/opt/sanjuuni/sanjuuni
```



