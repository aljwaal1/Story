from __future__ import annotations

import re
from urllib.parse import urlparse


def _clean_extension(value: str | None, media_type: str) -> str:
    extension = re.sub(r"[^a-zA-Z0-9]", "", value or "").lower()
    if extension:
        return extension
    return {"video": "mp4", "audio": "m4a", "image": "jpg"}.get(media_type, "bin")


def normalize_items(items: list[dict]) -> list[dict]:
    result: list[dict] = []
    for index, item in enumerate(items, start=1):
        media_url = str(item.get("url") or "").strip()
        if not media_url:
            continue

        media_type = str(item.get("type") or "image").lower()
        if media_type not in {"video", "audio", "image"}:
            media_type = "image"

        extension = _clean_extension(item.get("extension"), media_type)
        prefix = {"video": "video", "audio": "audio", "image": "image"}[media_type]
        normalized = {
            "id": f"item-{index:02d}",
            "order": index,
            "type": media_type,
            "url": media_url,
            "source_url": item.get("source_url"),
            "title": str(item.get("title") or f"ملف وسائط {index}")[:200],
            "extension": extension,
            "filename": f"{prefix}_{index:02d}.{extension}",
            "thumbnail": item.get("thumbnail"),
            "duration": item.get("duration"),
            "http_headers": item.get("http_headers") or {},
            "host": urlparse(media_url).hostname,
            "platform": item.get("platform"),
            "download_via": item.get("download_via"),
            "format_selector": item.get("format_selector"),
            "fallback_format_selector": item.get("fallback_format_selector"),
        }
        result.append(normalized)
    return result
