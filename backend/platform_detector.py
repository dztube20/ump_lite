import re
from urllib.parse import urlparse
# this file is for detect the platform to show a bubble of the platform

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
