# Youcube server Fork
I have it currently working, over the next few days(14-feb-2026) ill update the git repo (this one) to a working version.

Update (20 feb): Ill have a full getting started on here soon, server seems stable so later this weekend i will push those changes. 

## Getting started

After installing the requirements, just run src/ycf-server.py and the server will boot. 

## Requirements

- [yt-dlp/FFmpeg] / [FFmpeg 5.1+]
- [yt-dlp-ejs] `(For current YT api there are JS challenge to solve, you also gonna need Node.js as resolver)`
- Node.js
- [Python 3.7+]
  - [sanic]
  - [yt-dlp]
  - [spotipy]

If you have `pip` installed you can install the requirements with the following command: 

```shell
pip install -r src/requirements.txt
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



