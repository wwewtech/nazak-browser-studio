"""
History & Organic Profile Seeder.
Generates authentic Chromium History SQLite database with realistic dwell time and visits.
Eliminates 'empty bot profile' detection by Google, Cloudflare, and antifraud engines.
"""

from __future__ import annotations

import logging
import random
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

WEBKIT_EPOCH_DELTA_SEC = 11644473600


# Chromium PageTransition enum constants (ui/base/page_transition_types.h)
# Base types (lower 8 bits):
#   LINK   = 0 (followed a link)
#   TYPED  = 1 (typed into omnibox)
#   RELOAD = 8 (reloaded the page)
# Qualifiers (upper bits) can be combined:
#   CHAIN_START = 0x10000000 (268435456)
#   CHAIN_END   = 0x20000000 (536870912)
# Real typed visits typically have CHAIN_START | CHAIN_END | TYPED = 0x30000001 (805306369)
# Real link visits: 0 (LINK) or CHAIN_START | CHAIN_END | LINK = 0x30000000 (805306368)
PAGE_TRANSITION_LINK = 0
PAGE_TRANSITION_TYPED = 1
PAGE_TRANSITION_RELOAD = 8
PAGE_TRANSITION_CHAIN_TYPED = 805306369  # 0x30000001: CHAIN_START | CHAIN_END | TYPED
PAGE_TRANSITION_CHAIN_LINK = 805306368  # 0x30000000: CHAIN_START | CHAIN_END | LINK

TRANSITION_POOL = [
    PAGE_TRANSITION_CHAIN_LINK,
    PAGE_TRANSITION_LINK,
    PAGE_TRANSITION_CHAIN_TYPED,
    PAGE_TRANSITION_TYPED,
    PAGE_TRANSITION_RELOAD,
]

HIGH_TRUST_SITES = [
    ("https://www.google.com/", "Google", "search"),
    (
        "https://www.google.com/search?q=weather+forecast+this+week",
        "weather forecast this week - Google Search",
        "search",
    ),
    ("https://www.google.com/search?q=best+laptops+2026", "best laptops 2026 - Google Search", "search"),
    ("https://www.google.com/search?q=wikipedia+world+history", "wikipedia world history - Google Search", "search"),
    ("https://en.wikipedia.org/wiki/Main_Page", "Wikipedia, the free encyclopedia", "organic"),
    ("https://en.wikipedia.org/wiki/Computer_science", "Computer science - Wikipedia", "organic"),
    ("https://en.wikipedia.org/wiki/Artificial_intelligence", "Artificial intelligence - Wikipedia", "organic"),
    ("https://github.com/", "GitHub: Let’s build from here", "tech"),
    ("https://github.com/trending", "Trending repositories on GitHub today", "tech"),
    ("https://stackoverflow.com/", "Stack Overflow - Where Developers Learn, Share, & Build Careers", "tech"),
    ("https://developer.mozilla.org/en-US/", "MDN Web Docs", "tech"),
    ("https://www.reddit.com/", "Reddit - Dive into anything", "social"),
    ("https://www.reddit.com/r/technology/", "Technology - Reddit", "social"),
    ("https://www.reddit.com/r/news/", "Real-Time News - Reddit", "social"),
    ("https://www.youtube.com/", "YouTube", "video"),
    ("https://www.youtube.com/feed/trending", "Trending - YouTube", "video"),
    ("https://news.ycombinator.com/", "Hacker News", "tech"),
    ("https://www.bbc.com/news", "BBC News - World", "news"),
    ("https://www.cnn.com/", "CNN - Breaking News, Latest News and Videos", "news"),
    ("https://www.amazon.com/", "Amazon.com. Spend less. Smile more.", "ecommerce"),
    ("https://www.cloudflare.com/", "Cloudflare - The Web Performance & Security Company", "tech"),
    ("https://medium.com/", "Medium – Where good ideas find you.", "reading"),
    ("https://www.quora.com/", "Quora - A place to share knowledge", "social"),
    ("https://twitter.com/", "X", "social"),
    ("https://www.linkedin.com/", "LinkedIn: Log In or Sign Up", "business"),
]


def datetime_to_webkit_microsec(dt: datetime) -> int:
    """Converts a timezone-aware datetime to Chromium's WebKit timestamp (microseconds since 1601-01-01 UTC)."""
    epoch_sec = dt.timestamp()
    return int((epoch_sec + WEBKIT_EPOCH_DELTA_SEC) * 1_000_000)


def seed_chrome_history(
    user_data_dir: Path,
    entries_count: int = 30,
    niche: str | None = None,
) -> int:
    """
    Creates or populates an authentic Chromium History SQLite database inside <user_data_dir>/Default/History.
    Spreads realistic visits across the previous 14 days.
    """
    default_dir = user_data_dir / "Default"
    default_dir.mkdir(parents=True, exist_ok=True)
    history_db_path = default_dir / "History"

    conn = sqlite3.connect(str(history_db_path))
    cursor = conn.cursor()

    try:
        # Create core Chromium History tables if they do not exist
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS meta(
                key LONGVARCHAR NOT NULL UNIQUE PRIMARY KEY,
                value LONGVARCHAR
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS urls(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url LONGVARCHAR NOT NULL,
                title LONGVARCHAR,
                visit_count INTEGER DEFAULT 0 NOT NULL,
                typed_count INTEGER DEFAULT 0 NOT NULL,
                last_visit_time INTEGER NOT NULL,
                hidden INTEGER DEFAULT 0 NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS visits(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url INTEGER NOT NULL,
                visit_time INTEGER NOT NULL,
                from_visit INTEGER,
                transition INTEGER DEFAULT 0 NOT NULL,
                segment_id INTEGER,
                visit_duration INTEGER DEFAULT 0 NOT NULL,
                incremented_omnibox_typed_score BOOLEAN DEFAULT FALSE NOT NULL
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS urls_url_index ON urls (url)")
        cursor.execute("CREATE INDEX IF NOT EXISTS visits_url_index ON visits (url)")

        # Ensure schema version metadata
        cursor.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('version', '65')")
        cursor.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('last_compatible_version', '65')")

        # Select sites to insert
        sample_size = min(max(5, entries_count), len(HIGH_TRUST_SITES))
        chosen_sites = random.sample(HIGH_TRUST_SITES, sample_size)

        now_sec = time.time()
        inserted = 0

        for site_url, site_title, _category in chosen_sites:
            # Randomize visit time within past 1 to 14 days
            days_ago = random.uniform(0.5, 14.0)
            visit_sec = now_sec - (days_ago * 86400)
            dt_visit = datetime.fromtimestamp(visit_sec, tz=timezone.utc)
            webkit_time = datetime_to_webkit_microsec(dt_visit)

            visit_count = random.randint(1, 4)
            typed_count = random.choice([0, 1])

            # Check if URL exists
            cursor.execute("SELECT id, visit_count FROM urls WHERE url = ?", (site_url,))
            row = cursor.fetchone()
            if row:
                url_id = row[0]
                new_vc = row[1] + visit_count
                cursor.execute(
                    "UPDATE urls SET visit_count = ?, last_visit_time = ? WHERE id = ?",
                    (new_vc, webkit_time, url_id),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO urls (url, title, visit_count, typed_count, last_visit_time, hidden)
                    VALUES (?, ?, ?, ?, ?, 0)
                    """,
                    (site_url, site_title, visit_count, typed_count, webkit_time),
                )
                url_id = cursor.lastrowid

            # Insert visit events with UNIQUE timestamps and realistic from_visit chaining
            # Audit fix P1-7 (A4):
            # (a) Previous code gave ALL visits to the same URL an IDENTICAL visit_time
            # (b) transition used random.choice([805306368, 0, 1]) with comments claiming
            #     "TYPED, LINK, RELOAD" — but RELOAD is 8 and 805306368 is CHAIN_LINK
            # (c) from_visit was always hardcoded to 0 instead of chaining page visits
            last_visit_id = 0
            current_visit_sec = visit_sec
            for visit_idx in range(visit_count):
                visit_duration_sec = random.randint(15, 240)
                visit_duration_microsec = visit_duration_sec * 1_000_000

                # Spread multiple visits apart in time (between 2 hours and 3 days)
                if visit_idx > 0:
                    current_visit_sec += random.uniform(7200, 259200)
                    dt_v = datetime.fromtimestamp(current_visit_sec, tz=timezone.utc)
                    v_webkit_time = datetime_to_webkit_microsec(dt_v)
                    from_visit_id = last_visit_id if random.random() < 0.6 else 0
                    transition = random.choice(
                        [PAGE_TRANSITION_LINK, PAGE_TRANSITION_CHAIN_LINK, PAGE_TRANSITION_RELOAD]
                    )
                else:
                    v_webkit_time = webkit_time
                    from_visit_id = 0
                    transition = (
                        PAGE_TRANSITION_CHAIN_TYPED
                        if typed_count
                        else random.choice([PAGE_TRANSITION_LINK, PAGE_TRANSITION_CHAIN_LINK])
                    )

                cursor.execute(
                    """
                    INSERT INTO visits (url, visit_time, from_visit, transition, visit_duration)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (url_id, v_webkit_time, from_visit_id, transition, visit_duration_microsec),
                )
                last_visit_id = cursor.lastrowid
            inserted += 1

        conn.commit()
        logger.info("Successfully seeded %d history records into %s", inserted, history_db_path)
        return inserted
    except Exception as e:
        logger.exception("Failed to seed Chrome history for %s: %s", user_data_dir, e)
        conn.rollback()
        return 0
    finally:
        conn.close()
