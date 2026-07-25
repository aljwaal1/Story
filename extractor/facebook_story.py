"""Facebook public story extractor foundation.

This module prepares story URL parsing and media discovery hooks.
"""
import re
from urllib.parse import urlparse


def parse_story_url(url: str):
    """Extract basic identifiers from a Facebook story URL."""
    result = {
        "url": url,
        "profile_id": None,
        "story_id": None,
    }

    match = re.search(r"/stories/(\d+)/([^/?]+)", url)
    if match:
        result["profile_id"] = match.group(1)
        result["story_id"] = match.group(2)

    return result


def discover_media(url: str):
    """Placeholder for media discovery engine.

    Future versions will connect browser session extraction
    to collect all story slides.
    """
    data = parse_story_url(url)
    data["items"] = []
    return data
