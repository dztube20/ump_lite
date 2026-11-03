# backend/fetchers/bilibili.py
import re
import json
import subprocess
import os
import logging
import uuid
from curl_cffi import requests as curl_requests
from .base import BaseFetcher

logger = logging.getLogger(__name__)

# Try to import bilibili-api-python
try:
    from bilibili_api import video, sync
    BILIBILI_API_AVAILABLE = True
except ImportError:
    BILIBILI_API_AVAILABLE = False
    logger.warning("bilibili-api-python not installed. Install with: pip install bilibili-api-python")

class BilibiliFetcher(BaseFetcher):
    def fetch_formats(self, url):
        if 'bilibili.com' not in url or 'bilibili.tv' in url:
            return []

        bv_match = re.search(r'/video/(BV[^/?]+)', url)
        if not bv_match:
            return []

        bvid = bv_match.group(1)
        video_url = f'https://www.bilibili.com/video/{bvid}'

        # ---- 1. Try using bilibili-api-python (most reliable) ----
        if BILIBILI_API_AVAILABLE:
            try:
                logger.info(f"Bilibili: trying bilibili-api-python for {bvid}")
                v = video.Video(bvid=bvid)
                info = sync(v.get_info())
                pages = info.get('pages', [])
                # We'll get the first page
                if pages:
                    page = pages[0]
                    cid = page.get('cid')
                    if cid:
                        # Get playurl for this page
                        playurl = sync(v.get_playurl(cid=cid, quality=80, fnval=4048))
                        dash = playurl.get('dash', {})
                        if dash:
                            formats = self._extract_formats_from_dash(dash)
                            if formats:
                                logger.info(f"Bilibili: API returned {len(formats)} formats")
                                return formats
            except Exception as e:
                logger.warning(f"bilibili-api-python error: {e}")

        # ---- 2. Try yt-dlp with workarounds ----
        cmd = [
            'yt-dlp',
            '--impersonate', 'chrome-131',
            '--legacy-server-connect',
            '--no-warnings', '--quiet',
            '--dump-json',
            '--extractor-args', 'bilibili:try_look=1',
            '--add-header', 'Origin: https://www.bilibili.com',
            '--add-header', 'Referer: https://www.bilibili.com/',
            '--add-header', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            '--add-header', 'Accept: */*',
            '--add-header', 'Accept-Language: en-US,en;q=0.9',
            '--cookies-from-browser', 'chrome',  # try to get cookies
            video_url
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                formats = []
                for f in data.get('formats', []):
                    if not f.get('url'):
                        continue
                    formats.append({
                        'format_id': f['format_id'],
                        'url': f['url'],
                        'ext': f.get('ext', 'unknown'),
                        'quality': f.get('format_note') or f.get('resolution') or f['format_id'],
                        'has_video': f.get('vcodec') != 'none',
                        'has_audio': f.get('acodec') != 'none',
                        'size': f.get('filesize'),
                        'height': f.get('height'),
                        'note': f.get('format_note', ''),
                    })
                if formats:
                    logger.info(f"Bilibili: yt-dlp returned {len(formats)} formats")
                    return formats
        except Exception as e:
            logger.warning(f"yt-dlp attempt failed: {e}")

        # ---- 3. Try bilibili-cli via module ----
        try:
            logger.info("Bilibili: trying bilibili-cli via module")
            cmd = ['python', '-m', 'bilibili_cli', 'download', '--json', '--without-download', video_url]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                formats = []
                for item in data.get('videos', []):
                    for quality in ['high', 'medium', 'low']:
                        if quality in item:
                            url = item[quality]
                            if url:
                                formats.append({
                                    'format_id': quality,
                                    'url': url,
                                    'ext': 'mp4',
                                    'quality': quality,
                                    'has_video': True,
                                    'has_audio': True,
                                    'size': None,
                                    'note': f'bilibili-cli {quality}',
                                })
                if formats:
                    logger.info(f"Bilibili: bilibili-cli returned {len(formats)} formats")
                    return formats
        except Exception as e:
            logger.warning(f"bilibili-cli failed: {e}")

        return []

    def _extract_formats_from_dash(self, dash):
        formats = []
        for video in dash.get('video', []):
            url = video.get('base_url') or video.get('baseUrl')
            if url:
                formats.append({
                    'format_id': f"bilibili_video_{video.get('id')}",
                    'url': url,
                    'ext': 'mp4',
                    'quality': f"{video.get('height')}p",
                    'has_video': True,
                    'has_audio': False,
                    'size': None,
                    'height': video.get('height'),
                    'note': f"Bilibili video {video.get('codecs', '')}",
                })
        for audio in dash.get('audio', []):
            url = audio.get('base_url') or audio.get('baseUrl')
            if url:
                formats.append({
                    'format_id': f"bilibili_audio_{audio.get('id')}",
                    'url': url,
                    'ext': 'm4a',
                    'quality': f"{audio.get('bandwidth', 0)//1000}kbps",
                    'has_video': False,
                    'has_audio': True,
                    'size': None,
                    'height': None,
                    'note': f"Bilibili audio {audio.get('codecs', '')}",
                })
        return formats