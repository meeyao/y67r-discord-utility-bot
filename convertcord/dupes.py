import sqlite3
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import parse_qs, urlparse

# Basic URL regex
URL_RE = re.compile(r"https?://[^\s)\]`|]+")

# Common media extensions to ignore for dupe detection
MEDIA_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".webm", ".mov", ".svg",
    ".wav", ".mp3", ".ogg", ".flac"
}

# Domains to ignore for dupe detection (Discord system links, GIF platforms, etc.)
EXCLUDED_DOMAINS = {
    "tenor.com", "giphy.com", 
    "discord.com", "discordapp.com", "discordapp.net",
    "discord.gg"
}

# Twitter/X variants normalization
TWITTER_VARIANTS_RE = re.compile(
    r"(?i)https?://(?:www\.)?(?:twitter|x|fxtwitter|vxtwitter|fixupx)\.com/(?P<username>\w+)(?P<data>/status/\d+)(?P<extra>[^?\s)\]`|]*)"
)

YOUTUBE_HOSTS = {
    "youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "www.youtube.com",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}

INSTAGRAM_HOSTS = {
    "instagram.com",
    "vxinstagram.com",
    "kkinstagram.com",
}

REDDIT_HOSTS = {
    "reddit.com",
    "old.reddit.com",
    "new.reddit.com",
    "np.reddit.com",
    "rxddit.com",
}


class DupeChecker:
    def __init__(self, db_path: str = "data/dupes.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS links (
                    guild_id INTEGER NOT NULL DEFAULT 0,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    normalized_url TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_links_guild_created ON links(guild_id, created_at)")
            
            # Migration: add message_id if missing
            try:
                conn.execute("ALTER TABLE links ADD COLUMN message_id INTEGER NOT NULL DEFAULT 0")
            except sqlite3.OperationalError:
                pass

            try:
                conn.execute("ALTER TABLE links ADD COLUMN guild_id INTEGER NOT NULL DEFAULT 0")
            except sqlite3.OperationalError:
                pass
                
            conn.commit()

    def normalize_url(self, url: str) -> str:
        url = url.rstrip("/")
        
        # Twitter/X normalization
        twitter_match = TWITTER_VARIANTS_RE.match(url)
        if twitter_match:
            # We normalize all twitter variants to twitter.com/user/status/ID
            # and ignore any extra path info or query params
            return f"https://twitter.com/{twitter_match.group('username').lower()}/status/{twitter_match.group('data').split('/')[-1]}"

        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]

        youtube_key = self._normalize_youtube(parsed, domain)
        if youtube_key:
            return youtube_key

        instagram_key = self._normalize_simple_host_variant(
            parsed, domain, INSTAGRAM_HOSTS, "instagram.com"
        )
        if instagram_key:
            return instagram_key

        reddit_key = self._normalize_simple_host_variant(
            parsed, domain, REDDIT_HOSTS, "reddit.com"
        )
        if reddit_key:
            return reddit_key

        # General normalization: lowercase domain, remove common query params
        # Simple: remove everything after ?
        base_url = url.split("?")[0].lower()
        
        # Standardize domains
        base_url = base_url.replace("www.", "")
        base_url = base_url.replace("vxinstagram.com", "instagram.com")
        base_url = base_url.replace("rxddit.com", "reddit.com")
        base_url = base_url.replace("kktiktok.com", "tiktok.com").replace("vxtiktok.com", "tiktok.com")
        
        return base_url

    def _normalize_youtube(self, parsed, domain: str) -> Optional[str]:
        """Normalize YouTube variants by video id, not by the /watch path."""
        path = parsed.path.rstrip("/")
        query = parse_qs(parsed.query)

        if domain == "youtu.be":
            video_id = path.strip("/").split("/", 1)[0]
            return f"https://youtube.com/watch?v={video_id}" if video_id else None

        if domain not in YOUTUBE_HOSTS:
            return None

        video_id = None
        if path == "/watch":
            values = query.get("v") or []
            video_id = values[0] if values else None
        elif path.startswith(("/shorts/", "/embed/", "/live/")):
            video_id = path.split("/", 2)[2].split("/", 1)[0]

        return f"https://youtube.com/watch?v={video_id}" if video_id else None

    def _normalize_simple_host_variant(
        self, parsed, domain: str, hosts: set[str], canonical_domain: str
    ) -> Optional[str]:
        if domain not in hosts:
            return None
        path = parsed.path.rstrip("/").lower()
        return f"https://{canonical_domain}{path}"

    def is_excluded(self, url: str) -> bool:
        """Determines if a URL should be ignored for duplicate detection."""
        lower_url = url.lower()
        
        # 1. Check for media extensions (ignoring query params)
        clean_path = lower_url.split("?")[0].split("#")[0]
        if any(clean_path.endswith(ext) for ext in MEDIA_EXTENSIONS):
            return True
            
        # 2. Check for excluded domains
        try:
            # Extract domain
            domain = lower_url.split("://")[-1].split("/")[0].split(":")[0]
            if domain.startswith("www."):
                domain = domain[4:]
                
            if domain in EXCLUDED_DOMAINS or any(domain.endswith("." + d) for d in EXCLUDED_DOMAINS):
                return True
        except Exception:
            pass
            
        return False

    async def check_and_add(
        self, guild_id: int, channel_id: int, message_id: int, content: str
    ) -> Optional[tuple[int, int]]:
        """
        Extracts links from content, checks if any are dupes in the guild within 24h.
        Adds new links to the DB.
        Returns (original_channel_id, original_message_id) if a dupe was found, else None.
        """
        raw_links = URL_RE.findall(content)
        if not raw_links:
            return None

        # Filter out excluded links (media, discord system, etc.)
        links = [link for link in raw_links if not self.is_excluded(link)]
        if not links:
            return None

        normalized_links = {self.normalize_url(link) for link in links}
        
        original: Optional[tuple[int, int]] = None
        now = datetime.now(timezone.utc)
        day_ago = now - timedelta(hours=24)

        def _db_op():
            nonlocal original
            with sqlite3.connect(self.db_path) as conn:
                # Cleanup old entries first
                conn.execute("DELETE FROM links WHERE created_at < ?", (day_ago.isoformat(),))
                
                for norm_url in normalized_links:
                    # Check if exists
                    cursor = conn.execute(
                        """
                        SELECT channel_id, message_id
                        FROM links
                        WHERE (guild_id = ? OR guild_id = 0)
                          AND normalized_url = ?
                          AND created_at >= ?
                        ORDER BY created_at ASC
                        LIMIT 1
                        """,
                        (guild_id, norm_url, day_ago.isoformat())
                    )
                    row = cursor.fetchone()
                    if row:
                        original = (row[0], row[1])
                    else:
                        # Add new link
                        conn.execute(
                            "INSERT INTO links (guild_id, channel_id, message_id, normalized_url, created_at) VALUES (?, ?, ?, ?, ?)",
                            (guild_id, channel_id, message_id, norm_url, now.isoformat())
                        )
                conn.commit()

        _db_op()
        return original
