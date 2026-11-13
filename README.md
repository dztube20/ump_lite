<h1 align="center">UMP<sub>lite</sub> — Universal Media Downloader</h1>

UMP is a web app that uses **yt-dlp** to inspect media URLs, show available formats, queue downloads, report progress, and let a browser save the result.

> **Use it responsibly.** Download only content you own, have permission to download, or are legally allowed to save. Respect copyright, site terms, privacy, and regional law. Do not use this service to bypass DRM, paywalls, access controls, or private content.

## 1. What is included?

- `backend/app.py` — Flask API, job queue, progress stream, file delivery and cleanup.
- `backend/fetchers/` — original site-specific fetcher modules retained for reference/future integrations.
- `frontend/` — browser interface.
- `backend/requirements.txt` — Python dependencies.
- `Dockerfile` and `docker-compose.yml` — container deployment.

The API now uses yt-dlp's maintained extractor catalogue for metadata and downloads. That usually gives broader site coverage than maintaining a separate scraper for every website. A site's availability can still change at any time; private, age-restricted, geo-restricted, login-only or DRM-protected content may not work.
 
## 2. Requirements

For a manual install:

- 64-bit Linux, macOS, or Windows (Linux is recommended for a server).
- Python **3.10 or newer**.
- `pip` and `venv`.
- `ffmpeg` and `ffprobe` on `PATH` (recommended; required for many audio/video merges and conversions).
- Internet access from the server.
- Enough disk space for the files being downloaded.

Check the tools:

```bash
python --version
pip --version
yt-dlp --version
ffmpeg -version
```

## 3. Run on one computer (beginner/try setup)

### Linux / macOS

Clone this repo

```bash
git clone https://github.com/zaynkhan100110/ump-lite.git
cd ump-lite
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
```

Install ffmpeg using your operating system package manager, for example:

```bash
# Arch
sudo pacman -S ffmpeg

# Ubuntu / Debian
sudo apt update
sudo apt install -y ffmpeg
```

Start the server:

```bash
cd backend
python app.py
```

Open **http://127.0.0.1:5000** in your browser.

### Windows (PowerShell)

```powershell
cd ump
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
```

Install FFmpeg and add its `bin` directory to your Windows `PATH`. Then:

```powershell
cd backend
python app.py
```

Open **http://127.0.0.1:5000**.

To stop the server, press `Ctrl+C` in the terminal.

## 4. Serve it to your local network

This lets other devices on the same trusted Wi-Fi/LAN use the app.

1. Find the computer's LAN IP address (for example `192.168.1.25`).
2. Start UMP so it listens on all network interfaces:

   ```bash
   # from ump/backend
   HOST=0.0.0.0 PORT=5000 python app.py
   ```

   On PowerShell:

   ```powershell
   $env:HOST="0.0.0.0"
   $env:PORT="5000"
   python app.py
   ```

3. Allow inbound TCP port `5000` through the computer firewall **only on your private network**.
4. On another device open `http://192.168.1.25:5000` (replace the example IP).

Do not expose this development server directly to the public internet. Use the production setup below for internet-facing hosting.

## 5. Test on a single computer

1. Start the backend using the steps above.
2. Visit `http://127.0.0.1:5000`.
3. Paste a URL to a publicly accessible video you are allowed to download.
4. Press **Fetch Formats** and wait for the list.
5. Select a format and add it to the queue.
6. Watch the progress panel. When it completes, use the file link/button to save it.
7. Check the terminal output if a source fails. Updating yt-dlp often fixes newly changed site extractors:

   ```bash
   pip install --upgrade yt-dlp
   ```

Health check: visit `http://127.0.0.1:5000/api/health`. A successful response contains `"status":"ok"`.

## 6. Production deployment (Docker)

Docker is the easiest repeatable server deployment. Install Docker Engine and the Docker Compose plugin first.

From the project root:

```bash
docker compose up -d --build
docker compose logs -f
```

Open `http://YOUR_SERVER_IP:5000`. Stop it with:

```bash
docker compose down
```

Downloaded files are stored in the persistent `ump-downloads` Docker volume. To remove that volume (this permanently deletes downloaded files):

```bash
docker compose down -v
```

### Configure capacity

Edit `docker-compose.yml` environment values before starting:

- `UMP_MAX_CONCURRENT=4` — number of simultaneous yt-dlp downloads.
- `UMP_MAX_QUEUED_JOBS=100` — maximum pending + running jobs accepted at once.
- `UMP_JOB_TTL_SECONDS=3600` — how long finished/failed job records and files are retained (default one hour).
- `UMP_DOWNLOAD_DIR=/data` — download storage path inside the container.
- `LOG_LEVEL=INFO` — use `DEBUG` only while troubleshooting.

Start conservatively. Downloads consume CPU, memory, bandwidth and disk. More concurrent downloads do not always mean higher throughput.

## 7. Production hosting for around 100 users

A hundred registered/occasional users is not the same as a hundred simultaneous large downloads. Capacity depends heavily on media size, source throttling, network bandwidth, storage throughput and how many downloads run at once.

Recommended starting point for a small group:

- 4 vCPU and 8 GB RAM.
- 100 GB or more persistent storage, sized for your expected downloads.
- 1 Gbps network interface where available.
- `UMP_MAX_CONCURRENT=3` or `4`, then load-test and tune.
- Reverse proxy (Caddy or Nginx) with HTTPS.
- Authentication in front of the app (VPN, identity-aware proxy, or reverse-proxy login).
- Firewall: expose only HTTPS; do not expose the Flask/Gunicorn port publicly.
- Monitor disk usage and CPU, memory, network and application logs.

### Important architecture limits

This project intentionally keeps job metadata and its queue **in process memory**. Therefore:

- Run exactly **one Gunicorn worker** (`--workers 1`). Multiple workers would each have separate job dictionaries and progress state.
- Do not run multiple replicas/containers against the same app expecting a shared queue.
- A server restart loses job status; in-progress subprocesses may stop.
- For a larger/multi-instance deployment, replace the in-memory job registry with Redis + Celery/RQ (or another durable queue), store job state centrally, and store output in shared object storage such as S3-compatible storage.
- Put a hard quota and retention policy on storage. This app's TTL cleanup is not a substitute for an operational disk quota.

### Run Gunicorn directly (Linux)

Install dependencies, then from `ump/backend`:

```bash
gunicorn --workers 1 --threads 16 --timeout 180 --bind 127.0.0.1:8000 app:app
```

Use Nginx/Caddy to proxy HTTPS traffic to `127.0.0.1:8000`. Configure the proxy to allow long-running requests and disable response buffering for `/api/progress/` (SSE). Example Nginx location:

```nginx
location /api/progress/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 1h;
}
```

The regular application location should also proxy to the same upstream. Add HTTPS and authentication at the proxy; do not treat an obscure URL as security.

## 8. Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `HOST` | `127.0.0.1` | Bind address for `python app.py`; use `0.0.0.0` only behind a firewall/proxy or on a trusted LAN. |
| `PORT` | `5000` | Development server port. |
| `UMP_MAX_CONCURRENT` | `3` | Concurrent downloads in this process. |\n| `UMP_MAX_QUEUED_JOBS` | `100` | Maximum number of pending and running jobs accepted. |
| `UMP_DOWNLOAD_DIR` | `backend/downloads` | Persistent directory for downloaded media. |
| `UMP_JOB_TTL_SECONDS` | `3600` | Retention time for finished jobs/files. |
| `UMP_MAX_REQUEST_BYTES` | `16384` | Maximum JSON request body size. |
| `YTDLP_PATH` | auto-detected | Optional explicit path to the yt-dlp executable. |
| `CORS_ORIGINS` | empty | Comma-separated allowed browser origins; leave empty for same-origin hosting. |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR`. |

## 9. Updating

Back up your downloads first. Then:

```bash
# in the activated virtual environment
pip install --upgrade -r backend/requirements.txt
```

For Docker:

```bash
docker compose pull
docker compose up -d --build
```

yt-dlp changes frequently because media websites change frequently. Keep it updated, but test updates before deploying to a group.

## 10. Troubleshooting

- **`yt-dlp` not found:** activate the virtual environment, reinstall requirements, or set `YTDLP_PATH`.
- **No formats / extractor error:** update yt-dlp; check that the URL opens without a login; try again later. Some sites block datacenter IPs.
- **Merge or audio problems:** install FFmpeg and confirm `ffmpeg -version` works in the same environment/container.
- **A download starts but fails:** the selected format may have expired or been removed. Fetch formats again and select another one.
- **Browser cannot connect:** check the server process, IP address, port and firewall.
- **LAN works but public hosting fails:** configure HTTPS, reverse proxy, authentication and proxy SSE settings.
- **Disk full:** remove old files from the configured download directory and increase storage/retention controls.
- **SSE/progress freezes behind Nginx:** disable proxy buffering for `/api/progress/` as shown above.

## 11. API overview

- `GET /api/health` — health status.
- `POST /api/info` — JSON body `{"url":"https://..."}`; returns title, platform and available formats.
- `POST /api/download` — JSON body `{"url":"https://...","format_id":"..."}`; returns a job ID.
- `GET /api/progress/<job_id>` — Server-Sent Events progress stream.
- `GET /api/file/<job_id>` — download completed output.
- `DELETE /api/delete/<job_id>` — cancel/remove a job and its files.

## 12. Security and privacy notes

- Keep the service private or put authentication in front of it. Anyone who can access an unauthenticated instance can request downloads and consume its resources.
- Use HTTPS whenever credentials or user traffic cross an untrusted network.
- Keep the host patched and restrict firewall access.
- Do not mount sensitive host directories into the container.
- Treat submitted URLs as untrusted. Run this service in an isolated, low-privilege environment with outbound network policy appropriate to your deployment.
- Downloads may contain copyrighted or unsafe material. The operator is responsible for access control, retention, moderation and legal compliance.
- This app is not a DRM remover and should not be used to bypass access restrictions.

## 13. License

Do not attempt to sell !!!
