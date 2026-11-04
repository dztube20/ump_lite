# backend/utils.py – This is where rgrx happends
import re
from urllib.parse import urlparse, quote
from curl_cffi import requests as curl_requests

PLATFORM_PATTERNS = {
    'youtube': [r'youtube\.com', r'youtu\.be'],
    'tiktok': [r'tiktok\.com', r'vt\.tiktok\.com', r'vm\.tiktok\.com'],
    'twitter': [r'twitter\.com', r'x\.com'],
    'vimeo': [r'vimeo\.com'],
    'dailymotion': [r'dailymotion\.com', r'dai\.ly'],
    'instagram': [r'instagram\.com'],
    'facebook': [r'facebook\.com', r'fb\.watch'],
    'reddit': [r'reddit\.com', r'redd\.it'],
    'twitch': [r'twitch\.tv'],
    'soundcloud': [r'soundcloud\.com'],
    'rumble': [r'rumble\.com'],
    'bilibili': [r'bilibili\.com'],
    'xiaohongshu': [r'xiaohongshu\.com'],
    'bongacams': [r'bongacams\.com'],
    'bluesky': [r'bsky\.app'],
}

def detect_platform(url):
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    for platform, patterns in PLATFORM_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, domain):
                return platform
    return 'generic'

def normalize_rumble_url(url):
    """
    Convert various Rumble URL formats to a reliable embed URL.
    """
    # 1. Shorts URLs: https://rumble.com/shorts/v7diruq?e9s=...
    #    -> https://rumble.com/embed/v7diruq
    short_match = re.search(r'rumble\.com/shorts/([^/?]+)', url)
    if short_match:
        video_id = short_match.group(1)
        return f'https://rumble.com/embed/{video_id}'

    # 2. Embed URLs: https://rumble.com/embed/v6v9kpg/?pub=4
    #    -> https://rumble.com/embed/v6v9kpg
    embed_match = re.search(r'rumble\.com/embed/([^/?]+)', url)
    if embed_match:
        video_id = embed_match.group(1)
        return f'https://rumble.com/embed/{video_id}'

    # 3. Standard video pages: https://rumble.com/v7ev9l0-how-to-feel...
    #    -> extract video ID and use embed URL
    video_match = re.search(r'rumble\.com/v([a-zA-Z0-9]+)', url)
    if video_match:
        video_id = video_match.group(1)
        return f'https://rumble.com/embed/{video_id}'

    # Return the original URL if no pattern matches
    return url

def normalize_url(url):
    if not url:
        return None
    # Remove invisible characters and trim
    url = re.sub(r'[\u200b-\u200f\u202a-\u202e]', '', url).strip()
    # Extract first URL from text
    match = re.search(r'https?://[^\s<>"{}|\\^`\[\]]+', url)
    if match:
        url = match.group(0)

    # --- Rumble normalisation ---
    if 'rumble.com' in url:
        url = normalize_rumble_url(url)

    # --- Xiaohongshu: clean share text to just the explore URL ---
    if 'xiaohongshu.com' in url:
        match = re.search(r'/explore/([a-f0-9]+)', url)
        if match:
            video_id = match.group(1)
            url = f'https://www.xiaohongshu.com/explore/{video_id}'

    # --- Bilibili: extract BV ID and clean ---
    if 'bilibili.com' in url:
        match = re.search(r'/video/(BV[^/?]+)', url)
        if match:
            bvid = match.group(1)
            url = f'https://www.bilibili.com/video/{bvid}'

    # --- YouTube: allow video ID alone ---
    if re.match(r'^[a-zA-Z0-9_-]{11}$', url):
        return f'https://www.youtube.com/watch?v={url}'
    if re.match(r'^PL[a-zA-Z0-9_-]+$', url):
        return f'https://www.youtube.com/playlist?list={url}'

    # Ensure scheme
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    return url

def extract_youtube_id(url):
    patterns = [
        r'v=([a-zA-Z0-9_-]{11})',
        r'youtu\.be/([a-zA-Z0-9_-]{11})',
        r'embed/([a-zA-Z0-9_-]{11})',
        r'shorts/([a-zA-Z0-9_-]{11})',
        r'^([a-zA-Z0-9_-]{11})$'
    ]
    for p in patterns:
        match = re.search(p, url)
        if match:
            return match.group(1)
    return None

def is_direct_video_url(url):
    patterns = [
        r'\.(mp4|webm|mkv|avi|mov|flv|m4v|mp3|m4a|aac|ogg|wav)($|\?)',
        r'\.(m3u8|mpd)($|\?)',
        r'/video\.php\?',
        r'/get_video\?',
        r'/v\.redd\.it/',
        r'/proxy/',
    ]
    for p in patterns:
        if re.search(p, url, re.IGNORECASE):
            return True
    return False

# ---------- NEW: Rumble embed URL helper ----------
def get_rumble_embed_url(page_url):
    """
    Given a Rumble video page URL, return the embed URL.
    Returns None if not a Rumble page or if it's a short.
    """
    if 'rumble.com' not in page_url:
        return None
    if '/embed/' in page_url:
        return page_url
    if '/shorts/' in page_url:
        return None

    # Try oEmbed first
    try:
        oembed_url = f"https://rumble.com/api/Media/oembed.json?url={quote(page_url)}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'}
        resp = curl_requests.get(oembed_url, impersonate='chrome150', timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if 'html' in data:
                match = re.search(r'src=["\']([^"\']+)["\']', data['html'])
                if match:
                    embed_src = match.group(1)
                    embed_match = re.search(r'/embed/([^/?#]+)', embed_src)
                    if embed_match:
                        embed_id = embed_match.group(1)
                        if not embed_id.startswith('v'):
                            embed_id = 'v' + embed_id
                        return f'https://rumble.com/embed/{embed_id}/'
    except:
        pass

    # Try regex from URL
    match = re.search(r'rumble\.com/v([a-zA-Z0-9]+)', page_url)
    if match:
        video_id = match.group(1)
        if not video_id.startswith('v'):
            video_id = 'v' + video_id
        return f'https://rumble.com/embed/{video_id}/'

    # Try to fetch the page and extract embed ID from HTML
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'}
        resp = curl_requests.get(page_url, impersonate='chrome150', timeout=20)
        if resp.status_code == 200:
            html = resp.text
            match = re.search(r'"embedUrl"\s*:\s*"([^"]+)"', html)
            if match:
                embed_url = match.group(1).replace('\\/', '/')
                if 'rumble.com/embed/' in embed_url:
                    return embed_url
            match = re.search(r'videoId\s*:\s*"([^"]+)"', html)
            if match:
                video_id = match.group(1)
                if not video_id.startswith('v'):
                    video_id = 'v' + video_id
                return f'https://rumble.com/embed/{video_id}/'
    except:
        pass
    return None
