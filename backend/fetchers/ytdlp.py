# backend/fetchers/ytdlp.py
import json
import subprocess
from .base import BaseFetcher

class YtDlpFetcher(BaseFetcher):
    def fetch_formats(self, url):
        cmd = [
            'yt-dlp',
            '--impersonate', 'chrome-131',
            '--no-warnings',
            '--quiet',
            '--dump-json',
        ]

        if 'youtube.com' in url or 'youtu.be' in url:
            cmd.extend([
                '--extractor-args', 
                'youtube:player_client=web,android,ios,web_embedded;include_dash_manifest=true;include_duplicate_formats=true'
            ])

        if 'bilibili.com' in url and 'bilibili.tv' not in url:
            cmd.extend([
                '--extractor-args', 'bilibili:try_look=1',
                '--add-header', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                '--add-header', 'Referer: https://www.bilibili.com/',
                '--add-header', 'Origin: https://www.bilibili.com',
                '--add-header', 'Accept: */*',
                '--add-header', 'Accept-Language: en-US,en;q=0.9',
            ])

        cmd.append(url)

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                print(f"yt-dlp stderr: {result.stderr}")
                return []

            data = json.loads(result.stdout)
            formats = []
            for f in data.get('formats', []):
                # Safe handling of format_note
                note = f.get('format_note')
                if note is None:
                    note = ''
                note = note.lower()

                format_id = f.get('format_id', '')
                if 'storyboard' in note or 'storyboard' in format_id:
                    continue

                height = f.get('height')
                if height is not None and height < 100:
                    continue

                has_video = f.get('vcodec', 'none') != 'none'
                has_audio = f.get('acodec', 'none') != 'none'
                res = f.get('format_note') or f.get('resolution')
                if not res and height:
                    res = f"{height}p"
                elif not res:
                    res = f.get('format_id', 'unknown')

                formats.append({
                    'format_id': format_id,
                    'url': f.get('url'),
                    'ext': f.get('ext', 'unknown'),
                    'quality': res,
                    'has_video': has_video,
                    'has_audio': has_audio,
                    'size': f.get('filesize') or f.get('filesize_approx'),
                    'height': height,
                    'width': f.get('width'),
                    'fps': f.get('fps'),
                    'note': note or '',
                })
            return formats
        except Exception as e:
            print(f"YtDlpFetcher error: {e}")
            return []