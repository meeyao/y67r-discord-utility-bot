import re
import aiohttp
from dataclasses import dataclass
from typing import List, Optional

INSTAGRAM_RE = re.compile(r"(?i)https?://(?:www\.)?instagram\.com/(?P<type>reels?|p)(?P<data>/[^?\s)\]`|]+)")
REDDIT_RE = re.compile(r"(?i)https?://(?P<subdomain>(?:www\.|old\.)?)reddit\.com/(?P<subreddit>r/[^/]+)(?P<data>/[^?\s)\]`|]*)?")

TIKTOK_RE = re.compile(r"(?i)https?://(?P<subdomain>(?:\w{1,3}\.)?)(?P<domain>tiktok\.com)(?P<data>/[^?\s)\]`|]*)")
TWITCH_RE = re.compile(r"(?i)https?://(?:www\.)?(?:twitch\.tv/(?P<username>\w+)/clip/|clips\.twitch\.tv/)(?P<data>[^?\s)\]`|]+)")
TWITTER_RE = re.compile(r"(?i)https?://(?:www\.)?(?:twitter|x)\.com/(?P<username>\w+)(?P<data>/status/[^?\s)\]`|]*)")

@dataclass(frozen=True)
class SanitizePlatforms:
    instagram: bool = True
    reddit: bool = True
    tiktok: bool = True
    twitch: bool = True
    twitter: bool = True
    detect_dupes: bool = True

def _is_spoiler(content: str, match_start: int, match_end: int) -> bool:
    pre_url = content[:match_start]
    post_url = content[match_end:]
    pipes_before = pre_url.count("||")
    pipes_after = "||" in post_url
    return pipes_before % 2 == 1 and pipes_after

async def _get_tiktok_username(url: str, session: aiohttp.ClientSession) -> Optional[str]:
    """Attempts to resolve a TikTok username by following redirects for short links."""
    try:
        # Use a mobile-like or Discord-like User-Agent to ensure we get a clean redirect
        headers = {"User-Agent": "Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com/)"}
        async with session.get(url, allow_redirects=False, timeout=5, headers=headers) as resp:
            if resp.status in (301, 302):
                location = resp.headers.get("Location", "")
                # Location format: https://www.tiktok.com/@username/video/123456789...
                match = re.search(r"/@([^/]+)/video/", location)
                if match:
                    return match.group(1)
    except Exception:
        pass
    return None

async def _get_twitch_username(url: str, session: aiohttp.ClientSession) -> Optional[str]:
    """Attempts to get Twitch username from og:title if not in URL."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com/)"}
        async with session.get(url, timeout=5, headers=headers) as resp:
            if resp.status == 200:
                html = await resp.text()
                # Twitch og:title usually looks like "Username - Clip Title"
                match = re.search(r'<meta property="og:title" content="([^"-]+) - [^"]+"', html)
                if match:
                    return match.group(1).strip()
    except Exception:
        pass
    return None

def _format_output(
    content: str, 
    match: re.Match[str], 
    clean_url: str, 
    platform_name: str, 
    label: Optional[str] = None, 
    is_at: bool = False
) -> str:
    """Formats the final output string, respecting spoilers."""
    if label:
        prefix = f"@{label}" if is_at else label
        display = f"[{prefix} via {platform_name}]({clean_url})"
    else:
        display = f"[Post via {platform_name}]({clean_url})"
        
    if _is_spoiler(content, match.start(), match.end()):
        return f"|| {display} ||"
    return display

async def extract_and_sanitize(
    content: str, 
    session: aiohttp.ClientSession,
    platforms: Optional[SanitizePlatforms] = None
) -> List[str]:
    platforms = platforms or SanitizePlatforms()
    results = []
    
    # Instagram
    if platforms.instagram:
        for match in INSTAGRAM_RE.finditer(content):
            ptype = match.group("type")
            data = match.group("data")
            clean_url = f"https://www.vxinstagram.com/{ptype}{data}"
            
            label = "Reel" if ptype.lower().startswith("reel") else "Post"
            results.append(_format_output(content, match, clean_url, "Instagram", label))
        
    # Reddit
    if platforms.reddit:
        for match in REDDIT_RE.finditer(content):
            subreddit = match.group("subreddit")
            data = match.group("data") or ""

            # vxreddit does not use reddit subdomains
            clean_url = f"https://rxddit.com/{subreddit}{data}"

            results.append(
                _format_output(content, match, clean_url, "Reddit", subreddit)
            )
        
    # TikTok
    if platforms.tiktok:
        for match in TIKTOK_RE.finditer(content):
            subdomain = match.group("subdomain") or ""
            data = match.group("data")
            clean_url = f"https://{subdomain}kktiktok.com{data}"
            
            username = None
            # If it's a short link or missing username in data, try to fetch it
            if "/video/" not in data:
                original_url = match.group(0)
                username = await _get_tiktok_username(original_url, session)
            elif "/@" in data:
                u_match = re.search(r"/@([^/]+)/", data)
                if u_match:
                    username = u_match.group(1)
            
            results.append(_format_output(content, match, clean_url, "TikTok", username, is_at=True))
        
    # Twitch
    if platforms.twitch:
        for match in TWITCH_RE.finditer(content):
            username = match.group("username")
            data = match.group("data")
            if username:
                clean_url = f"https://fxtwitch.seria.moe/{username}/clip/{data}"
            else:
                clean_url = f"https://fxtwitch.seria.moe/clip/{data}"
                # Try to fetch username for clips.twitch.tv style links
                username = await _get_twitch_username(match.group(0), session)
                
            results.append(_format_output(content, match, clean_url, "Twitch", username, is_at=True))
            
    # Twitter
    if platforms.twitter:
        for match in TWITTER_RE.finditer(content):
            username = match.group("username")
            data = match.group("data")
            clean_url = f"https://fxtwitter.com/{username}{data}"
            
            results.append(_format_output(content, match, clean_url, "Twitter", username, is_at=True))
        
    return results

def contains_url(content: str, platforms: Optional[SanitizePlatforms] = None) -> bool:
    platforms = platforms or SanitizePlatforms()
    lower_content = content.lower()
    domains = []
    if platforms.instagram:
        domains.append("instagram.com")
    if platforms.reddit:
        domains.append("reddit.com")
    if platforms.tiktok:
        domains.append("tiktok.com")
    if platforms.twitch:
        domains.append("twitch.tv")
    if platforms.twitter:
        domains.extend(["twitter.com", "x.com"])
    return any(domain in lower_content for domain in domains)
