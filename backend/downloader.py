"""
Standalone downloader using yt-dlp (with impersonation and merge).
"""
import subprocess
import tempfile
import os
 
class MediaDownloader:
    user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'

    @staticmethod
    def download(url, format_id='bestvideo+bestaudio/best', output_path=None):
        if output_path is None:
            fd, output_path = tempfile.mkstemp(suffix='.mp4')
            os.close(fd)

        cmd = [
            'yt-dlp',
            '-f', format_id,
            '-o', output_path,
            '--no-check-certificate',
            '--ignore-errors',
            '--quiet',
            '--no-warnings',
            '--add-header', f'User-Agent:{MediaDownloader.user_agent}',
            '--merge-output-format', 'mp4',
            url
        ]
        if 'youtube.com' in url or 'youtu.be' in url:
            cmd += ['--extractor-args', 'youtube:player_client=android,ios']
        elif 'bilibili.com' in url:
            cmd += [
                '--extractor-args', 'bilibili:try_look=1',
                '--add-header', 'Referer: https://www.bilibili.com',
                '--add-header', 'Origin: https://www.bilibili.com',
            ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                return output_path
            else:
                raise Exception(f"Download failed: {result.stderr[:200]}")
        except Exception as e:
            raise Exception(f"Download error: {e}")
