# Youcube server Fork
This is a fork of the original Youcube server. This is an continuation of the original project since i really liked being able to play music, videos etc in minecraft.
This fork has lots of new features and is a lot more stable.

### Features that were in the original project
- Music playing from multiple sources but not live. 
- Video+Audio playing from multiple sources. 

### Additional Features
- Radio stations support, live streams support from youtube, twitch, etc. 
- Server-sided command system for more control.
- Server-sided admin dashboard
- Lots and lots of bug fixes.

## Requirements

- Git (for cloning only)
- FFmpeg / FFmpeg 5.1+
- Node.js
- sanjuuni (Optional for video output)
- Python 3.7+
  - sanic
  - sanic-ext
  - Jinja2
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

The server reads settings from `config.json` in the project root. The settings are grouped under logical categories:

### Server Settings (`server_settings`)
- `host`: The host address to bind the server to. Default is `"0.0.0.0"`. (Can also be set via the `HOST` environment variable).
- `port`: The port to run the server on. Default is `5000`. (Can also be set via the `PORT` environment variable).
- `admin_panel_web`: Configuration for the optional web-based admin panel.
  - `enabled`: Set to `true` to enable the admin panel. Default is `false`.
  - `password`: The password required to log in to the admin panel. **Change this from the default!**
  - `url_prefix`: The path prefix to access the admin site. Default is `"/admin"`.

### Path Settings (`path_settings`)
- `cookie_file`: Optional path to a `cookies.txt` file for yt-dlp.
- `js_runtimes.node.path`: Optional path to a Node.js binary for yt-dlp JS challenges.

### Debug Settings (`debug_settings`)
- `debug_logging_default`: Optional boolean to enable debug logs by default. Default is `false`.

### Spotify Settings (`spotify`)
- `client_id`: Optional Spotify client ID. If `null` or empty, falls back to env variable `SPOTIPY_CLIENT_ID`.
- `client_secret`: Optional Spotify client secret. If `null` or empty, falls back to env variable `SPOTIPY_CLIENT_SECRET`.
- `market`: Optional market/region for Spotify lookups. Default is `NL`.

## Admin Panel Web (Optional)

The server includes an optional web-based admin panel to view active clients and kick them.

**To enable it:**
1. Open `config.json`.
2. Set `"enabled": true` under the `server_settings.admin_panel_web` block.
3. Change `"password": "change_me"` to a secure password.
4. Optionally customize the access path by editing `"url_prefix"`.
5. Restart the server.

Access the panel at `http://<your-server-ip>:<port><url_prefix>` (e.g., `http://localhost:5000/admin`).

*Note: The required dependencies (`sanic-ext`, `Jinja2`) are automatically installed if you followed the "Getting started" guide.*

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
