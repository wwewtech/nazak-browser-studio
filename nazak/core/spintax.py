"""
Spintax Parser & SEO Title/Description Template Engine for YouTube Shorts.
Supports nested spintax like {Лучший|Топ|Рабочий {впн|vpn}} and placeholders {tg}, {promo}, {year}.
"""
import re
import random
from typing import Dict, Any, Optional

def parse_spintax(text: str) -> str:
    """
    Recursively resolves Spintax notation {option1|option2|option3}.
    Preserves non-spintax placeholders like {tg}, {promo}, {year}.
    """
    pattern = re.compile(r"\{([^{}]+)\}")
    iterations = 0
    while iterations < 50:
        iterations += 1
        matches = list(pattern.finditer(text))
        replaced = False
        for match in reversed(matches):
            content = match.group(1)
            if "|" in content:
                options = content.split("|")
                chosen = random.choice(options)
                text = text[:match.start()] + chosen + text[match.end():]
                replaced = True
        if not replaced:
            break
    return text

def format_video_metadata(
    title_template: str,
    description_template: str,
    profile_name: str,
    profile_id: str,
    tg_channel: str = "@your_vpn_bot",
    promo_code: Optional[str] = None
) -> Dict[str, str]:
    """
    Generates unique, spun title and description with dynamic placeholders.
    """
    ctx = {
        "tg": tg_channel,
        "promo": promo_code or f"PROMO{random.randint(100, 999)}",
        "profile": profile_name,
        "year": "2026",
    }

    # 1. Resolve spintax
    spun_title = parse_spintax(title_template)
    spun_desc = parse_spintax(description_template)

    # 2. Replace placeholders
    for k, v in ctx.items():
        spun_title = spun_title.replace(f"{{{k}}}", v)
        spun_desc = spun_desc.replace(f"{{{k}}}", v)

    # YouTube Shorts titles should typically be under 100 characters
    if len(spun_title) > 95:
        spun_title = spun_title[:92] + "..."

    return {
        "title": spun_title.strip(),
        "description": spun_desc.strip(),
        "tags": ["#shorts", "#vpn", "#впн", "#ютуб", "#shortsyoutube", "#tech"]
    }
