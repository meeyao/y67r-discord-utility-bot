import re
from dataclasses import dataclass
from typing import List

INSTAGRAM_RE = re.compile(r"(?i)https?://(?:www\.)?instagram\.com/(?P<type>reels?|p)(?P<data>/[^/\s?)\]`|]+)")
REDDIT_RE = re.compile(r"(?i)https?://(?P<subdomain>(?:www\.|old\.)?)reddit\.com/(?P<subreddit>r/[^/]+)(?P<data>/[^?\s)\]`|]*)?")
TIKTOK_RE = re.compile(r"(?i)https?://(?P<subdomain>(?:\w{1,3}\.)?)tiktok\.com(?P<data>/[^?\s)\]`|]*)")
TWITCH_RE = re.compile(r"(?i)https?://(?:www\.)?(?:twitch\.tv/(?P<username>\w+)/clip/|clips\.twitch\.tv/)(?P<data>[^?\s)\]`|]+)")
TWITTER_RE = re.compile(r"(?i)https?://(?:www\.)?(?:twitter|x)\.com/(?P<username>\w+)(?P<data>/status/[^?\s)\]`|]*)")


@dataclass(frozen=True)
class SanitizePlatforms:
    instagram: bool = True
    reddit: bool = True
    tiktok: bool = True
    twitch: bool = True
    twitter: bool = True


def _is_spoiler(content: str, match_start: int, match_end: int) -> bool:
    pre_url = content[:match_start]
    post_url = content[match_end:]
    pipes_before = pre_url.count("||")
    pipes_after = "||" in post_url
    return pipes_before % 2 == 1 and pipes_after


def _format_sanitized_url(content: str, match: re.Match[str], clean_url: str) -> str:
    # Discord only unfurls raw URLs, not masked Markdown links.
    if _is_spoiler(content, match.start(), match.end()):
        return f"|| {clean_url} ||"
    return clean_url

def extract_and_sanitize(content: str, platforms: SanitizePlatforms | None = None) -> List[str]:
    platforms = platforms or SanitizePlatforms()
    results = []
    
    # Instagram
    if platforms.instagram:
        for match in INSTAGRAM_RE.finditer(content):
            ptype = match.group("type")
            data = match.group("data")
            clean_url = f"https://www.kkinstagram.com/{ptype}{data}"
            results.append(_format_sanitized_url(content, match, clean_url))
        
    # Reddit
    if platforms.reddit:
        for match in REDDIT_RE.finditer(content):
            subdomain = match.group("subdomain") or "www."
            subreddit = match.group("subreddit")
            data = match.group("data") or ""
            clean_url = f"https://{subdomain}rxddit.com/{subreddit}{data}"
            results.append(_format_sanitized_url(content, match, clean_url))
        
    # TikTok
    if platforms.tiktok:
        for match in TIKTOK_RE.finditer(content):
            subdomain = match.group("subdomain") or ""
            data = match.group("data")
            clean_url = f"https://{subdomain}kktiktok.com{data}"
            results.append(_format_sanitized_url(content, match, clean_url))
        
    # Twitch
    if platforms.twitch:
        for match in TWITCH_RE.finditer(content):
            username = match.group("username")
            data = match.group("data")
            if username:
                clean_url = f"https://fxtwitch.seria.moe/{username}/clip/{data}"
            else:
                clean_url = f"https://fxtwitch.seria.moe/clip/{data}"
            results.append(_format_sanitized_url(content, match, clean_url))
            
    # Twitter
    if platforms.twitter:
        for match in TWITTER_RE.finditer(content):
            username = match.group("username")
            data = match.group("data")
            clean_url = f"https://fxtwitter.com/{username}{data}"
            results.append(_format_sanitized_url(content, match, clean_url))
        
    return results

def contains_url(content: str, platforms: SanitizePlatforms | None = None) -> bool:
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
