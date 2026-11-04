"""Flask API for UMP. Run one process per data directory; jobs are in-memory."""
from __future__ import annotations
import json, logging, os, re, shutil, subprocess, tempfile, threading, time, uuid
from pathlib import Path
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, Response, jsonify, request, send_from_directory, abort, stream_with_context
from flask_cors import CORS

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent / "frontend"
DOWNLOAD_DIR = Path(os.getenv("UMP_DOWNLOAD_DIR", BASE_DIR / "downloads")).resolve()
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_WORKERS = max(1, int(os.getenv("UMP_MAX_CONCURRENT", "3")))
MAX_QUEUED_JOBS = max(MAX_WORKERS, int(os.getenv("UMP_MAX_QUEUED_JOBS", "100")))
JOB_TTL = max(60, int(os.getenv("UMP_JOB_TTL_SECONDS", "3600")))
MAX_CONTENT_LENGTH = int(os.getenv("UMP_MAX_REQUEST_BYTES", "16384"))
YTDLP = os.getenv("YTDLP_PATH") or shutil.which("yt-dlp") or "yt-dlp"

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("ump")
app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
# Same-origin is the recommended production setup. Configure CORS_ORIGINS only if needed.
origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "").split(",") if x.strip()]
if origins:
    CORS(app, origins=origins)

lock = threading.RLock()
jobs: dict[str, dict] = {}
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="ump-download")
cache: dict[str, tuple[float, dict]] = {}
CACHE_TTL = 300

def validate_url(value):
    """Accept only absolute HTTP(S) URLs; never pass arbitrary schemes to yt-dlp."""
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError("Please provide a valid URL (maximum 4096 characters).")
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Only complete http:// or https:// URLs are supported.")
    if parsed.username or parsed.password:
        raise ValueError("URLs containing embedded credentials are not supported.")
    return value

def run_ytdlp_json(url):
    cmd = [YTDLP, "--no-warnings", "--no-playlist", "--dump-single-json",
           "--skip-download", "--socket-timeout", "20", url]
    # Use the same current yt-dlp extractor implementation across supported sites.
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    if result.returncode:
        detail = (result.stderr or result.stdout or "Extractor failed").strip()[-1200:]
        raise RuntimeError(detail)
    return json.loads(result.stdout)
 
def simplify_formats(info):
    formats = []
    for item in info.get("formats") or []:
        fid = str(item.get("format_id") or "")
        if not fid or "storyboard" in fid.lower():
            continue
        h = item.get("height")
        if h is not None and h < 100:
            continue
        vc, ac = item.get("vcodec", "none"), item.get("acodec", "none")
        formats.append({
            "format_id": fid, "url": item.get("url"), "ext": item.get("ext") or "unknown",
            "quality": item.get("format_note") or item.get("resolution") or (f"{h}p" if h else fid),
            "has_video": vc not in (None, "none"), "has_audio": ac not in (None, "none"),
            "size": item.get("filesize") or item.get("filesize_approx"),
            "height": h, "width": item.get("width"), "fps": item.get("fps"),
            "note": item.get("format_note") or ""
        })
    return formats

@app.get("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")

@app.get("/api/health")
def health():
    return jsonify(status="ok", workers=MAX_WORKERS, queue=sum(j["status"] == "pending" for j in jobs.values()))

@app.post("/api/info")
def get_info():
    data = request.get_json(silent=True) or {}
    try:
        url = validate_url(data.get("url"))
        now = time.time()
        cached = cache.get(url)
        if cached and now - cached[0] < CACHE_TTL:
            return jsonify(cached[1])
        info = run_ytdlp_json(url)
        formats = simplify_formats(info)
        if not formats:
            return jsonify(error="No downloadable formats were returned by the source."), 404
        result = {"url": url, "platform": (urlparse(url).hostname or "unknown").lower(),
                  "title": info.get("title") or "Untitled media", "formats": formats}
        cache[url] = (now, result)
        return jsonify(result)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except subprocess.TimeoutExpired:
        return jsonify(error="The source took too long to respond. Try again later."), 504
    except Exception as exc:
        log.warning("Metadata extraction failed: %s", exc)
        return jsonify(error=f"Could not read this media. {str(exc)[:500]}"), 502

def worker(job_id):
    with lock:
        job = jobs.get(job_id)
        if not job or job["status"] == "cancelled":
            return
        job["status"] = "downloading"
    outtmpl = str(DOWNLOAD_DIR / f"{job_id}.%(ext)s")
    cmd = [YTDLP, "--newline", "--no-warnings", "--no-playlist", "--no-part",
           "--progress", "--socket-timeout", "30", "--retries", "5",
           "--fragment-retries", "5", "--file-access-retries", "3",
           "-f", job["format_id"], "-o", outtmpl, job["url"]]
    # Don't force MP4: many sources provide better/native formats; yt-dlp merges when needed.(ffmpeg required)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1)
        with lock:
            if job_id in jobs:
                jobs[job_id]["process"] = proc
        for line in proc.stdout:
            match = re.search(r"\[download\]\s+(\d+(?:\.\d+)?)%", line)
            if match:
                with lock:
                    if job_id in jobs:
                        jobs[job_id]["progress"] = min(99.9, float(match.group(1)))
            if "Destination:" in line:
                with lock:
                    if job_id in jobs:
                        jobs[job_id]["filename"] = Path(line.split("Destination:",1)[1].strip()).name
        code = proc.wait()
        candidates = list(DOWNLOAD_DIR.glob(f"{job_id}.*"))
        candidates = [p for p in candidates if p.is_file() and not p.name.endswith((".part", ".ytdl"))]
        if code != 0 or not candidates or candidates[0].stat().st_size == 0:
            raise RuntimeError(f"yt-dlp failed (exit code {code}). Check that the URL is public and the selected format is still available.")
        path = max(candidates, key=lambda p: p.stat().st_mtime)
        with lock:
            if job_id in jobs:
                jobs[job_id].update(status="completed", progress=100, filename=path.name,
                                    file_path=str(path), process=None)
    except Exception as exc:
        log.exception("Download job %s failed", job_id)
        with lock:
            if job_id in jobs:
                jobs[job_id].update(status="error", error=str(exc)[:1000], process=None)
    finally:
        with lock:
            if job_id in jobs and jobs[job_id]["status"] == "downloading":
                jobs[job_id]["status"] = "error"
                jobs[job_id]["error"] = "Download stopped unexpectedly."

@app.post("/api/download")
def start_download():
    data = request.get_json(silent=True) or {}
    try:
        url = validate_url(data.get("url"))
        format_id = str(data.get("format_id") or "").strip()
        if not format_id or len(format_id) > 100 or not re.fullmatch(r"[A-Za-z0-9_.+-]+", format_id):
            return jsonify(error="A valid format_id is required."), 400
        with lock:
            # Avoid duplicate pending/running work for the same URL and format.
            for existing in jobs.values():
                if existing["url"] == url and existing["format_id"] == format_id and existing["status"] in ("pending", "downloading"):
                    return jsonify(error="This format is already queued or downloading."), 409
            active_count = sum(j["status"] in ("pending", "downloading") for j in jobs.values())
            if active_count >= MAX_QUEUED_JOBS:
                return jsonify(error="The download queue is full. Please try again later."), 503
            job_id = uuid.uuid4().hex
            jobs[job_id] = {"id": job_id, "url": url, "format_id": format_id,
                            "status": "pending", "progress": 0, "error": None,
                            "filename": None, "file_path": None, "process": None,
                            "created": time.time()}
            executor.submit(worker, job_id)
        return jsonify(job_id=job_id), 202
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

@app.get("/api/progress/<job_id>")
def progress_stream(job_id):
    def events():
        while True:
            with lock:
                job = jobs.get(job_id)
                if not job:
                    payload = {"error": "Job not found"}
                    done = True
                else:
                    payload = {"progress": job["progress"], "status": job["status"], "error": job["error"]}
                    if job["status"] == "completed":
                        payload.update(complete=True, file_url=f"/api/file/{job_id}")
                    done = job["status"] in ("completed", "error", "cancelled")
            yield f"data: {json.dumps(payload)}\\n\\n"
            if done:
                break
            time.sleep(1)
    return Response(stream_with_context(events()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.get("/api/file/<job_id>")
def download_file(job_id):
    with lock:
        job = jobs.get(job_id)
        if not job or job["status"] != "completed" or not job["file_path"]:
            return jsonify(error="The file is not ready or has expired."), 404
        path = Path(job["file_path"])
        filename = path.name
    if not path.is_file():
        return jsonify(error="The downloaded file no longer exists."), 404
    # Flask streams the file efficiently; keep it until explicit expiry/cleanup.
    return send_from_directory(path.parent, path.name, as_attachment=True,
                              download_name=filename, conditional=True)

@app.delete("/api/delete/<job_id>")
def delete_job(job_id):
    with lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify(error="Job not found"), 404
        proc = job.get("process")
        job["status"] = "cancelled"
        jobs.pop(job_id, None)
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    for path in DOWNLOAD_DIR.glob(f"{job_id}.*"):
        try: path.unlink(missing_ok=True)
        except OSError: log.warning("Could not remove %s", path)
    return jsonify(success=True)

def cleanup_loop():
    """Remove expired job records and their files without blocking requests."""
    while True:
        time.sleep(300)
        cutoff = time.time() - JOB_TTL
        with lock:
            expired = [jid for jid, job in jobs.items()
                       if job["created"] < cutoff and job["status"] in ("completed", "error", "cancelled")]
            for jid in expired:
                jobs.pop(jid, None)
        for jid in expired:
            for path in DOWNLOAD_DIR.glob(f"{jid}.*"):
                try: path.unlink(missing_ok=True)
                except OSError: log.warning("Cleanup failed for %s", path)

threading.Thread(target=cleanup_loop, daemon=True, name="ump-cleanup").start()

if __name__ == "__main__":
    # Development only. Use gunicorn (one worker) behind a reverse proxy in production.
    app.run(host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "5000")),
            debug=False, threaded=True)
