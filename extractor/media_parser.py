from __future__ import annotations

import re
from urllib.parse import urlparse


def _clean_extension(value: str | None, media_type: str) -> str:
    extension = re.sub(r"[^a-zA-Z0-9]", "", value or "").lower()
    if extension:
        return extension
    return "mp4" if media_type == "video" else "jpg"


def normalize_items(items: list[dict]) -> list[dict]:
    result: list[dict] = []
    for index, item in enumerate(items, start=1):
        media_url = str(item.get("url") or "").strip()
        if not media_url:
            continue
        media_type = "video" if item.get("type") == "video" else "image"
        extension = _clean_extension(item.get("extension"), media_type)
        result.append({
            "id": f"item-{index:02d}", "order": index, "type": media_type, "url": media_url,
            "source_url": item.get("source_url"),
            "title": str(item.get("title") or f"عنصر القصة {index}")[:200],
            "extension": extension, "filename": f"story_{index:02d}.{extension}",
            "thumbnail": item.get("thumbnail"), "duration": item.get("duration"),
            "http_headers": item.get("http_headers") or {}, "host": urlparse(media_url).hostname,
        })
    return result
