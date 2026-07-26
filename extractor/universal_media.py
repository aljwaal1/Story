from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlparse


class MediaExtractionError(RuntimeError):
    pass


_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
_MAX_ITEMS = max(1, min(int(os.getenv("MEDIA_MAX_ITEMS", "50")), 200))
_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif", "avif"}


def _validate_public_url(url: str) -> str:
    value = (url or "").strip()
    parsed = urlparse(value)
    host = (parsed.hostname or "").strip().lower()

    if parsed.scheme not in {"http", "https"} or not host:
        raise MediaExtractionError("أدخل رابطًا صحيحًا يبدأ بـ http أو https.")

    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise MediaExtractionError("لا يمكن تحليل روابط الجهاز المحلي أو الشبكة الداخلية.")

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None

    if address and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
    ):
        raise MediaExtractionError("لا يمكن تحليل عناوين الشبكات الخاصة أو المحلية.")

    return value


def _flatten_entries(info: dict) -> list[dict]:
    entries = info.get("entries")
    if not entries:
        return [info]

    flattened: list[dict] = []
    for entry in entries:
        if not entry:
            continue
        if entry.get("entries"):
            flattened.extend(_flatten_entries(entry))
        else:
            flattened.append(entry)
        if len(flattened) >= _MAX_ITEMS:
            break
    return flattened[:_MAX_ITEMS]


def _has_video(entry: dict) -> bool:
    if entry.get("vcodec") not in {None, "none"}:
        return True
    return any(
        fmt.get("url") and fmt.get("vcodec") not in {None, "none"}
        for fmt in entry.get("formats", [])
    )


def _image_item(entry: dict, source_url: str, platform: str) -> dict | None:
    extension = str(entry.get("ext") or "").lower()
    media_url = str(entry.get("url") or "").strip()

    if extension not in _IMAGE_EXTENSIONS:
        thumbnails = [thumb for thumb in entry.get("thumbnails", []) if thumb.get("url")]
        if not thumbnails:
            return None
        media_url = str(thumbnails[-1]["url"])
        extension = "jpg"

    return {
        "type": "image",
        "url": media_url,
        "source_url": entry.get("webpage_url") or source_url,
        "title": entry.get("title") or entry.get("description") or "صورة",
        "extension": extension or "jpg",
        "thumbnail": media_url,
        "duration": None,
        "platform": platform,
        "http_headers": entry.get("http_headers")
        or {"User-Agent": _USER_AGENT, "Referer": source_url},
    }


def _quality_selectors(quality: str) -> tuple[str, str]:
    limits = {
        "2160": 2160,
        "1440": 1440,
        "1080": 1080,
        "720": 720,
        "480": 480,
        "360": 360,
    }
    height = limits.get(str(quality))
    if not height:
        return (
            "bestvideo*+bestaudio/best",
            "best[ext=mp4]/best",
        )
    return (
        f"bestvideo*[height<={height}]+bestaudio/best[height<={height}]/best",
        f"best[height<={height}][ext=mp4]/best[height<={height}]/best",
    )


def _downloadable_item(
    entry: dict,
    source_url: str,
    platform: str,
    mode: str,
    quality: str,
) -> dict:
    webpage_url = (
        entry.get("webpage_url")
        or entry.get("original_url")
        or entry.get("url")
        or source_url
    )
    item_type = "audio" if mode == "audio" else "video"
    video_selector, fallback_selector = _quality_selectors(quality)
    return {
        "type": item_type,
        "url": webpage_url,
        "source_url": webpage_url,
        "title": entry.get("title") or entry.get("description") or "ملف وسائط",
        "extension": "m4a" if item_type == "audio" else "mp4",
        "thumbnail": entry.get("thumbnail"),
        "duration": entry.get("duration"),
        "platform": platform,
        "download_via": "yt-dlp",
        "format_selector": (
            "bestaudio[ext=m4a]/bestaudio/best"
            if item_type == "audio"
            else video_selector
        ),
        "fallback_format_selector": (
            None if item_type == "audio" else fallback_selector
        ),
        "http_headers": entry.get("http_headers") or {"User-Agent": _USER_AGENT},
    }


def discover_media(url: str, mode: str = "video", quality: str = "best") -> dict:
    source_url = _validate_public_url(url)
    mode = mode if mode in {"video", "audio", "original"} else "video"

    try:
        import yt_dlp
    except ImportError as exc:
        raise MediaExtractionError(
            "مكتبة yt-dlp غير مثبتة. شغّل start.bat أو نفّذ pip install -r requirements.txt."
        ) from exc

    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
        "noplaylist": False,
        "playlistend": _MAX_ITEMS,
        "http_headers": {"User-Agent": _USER_AGENT},
        "socket_timeout": 30,
    }

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(source_url, download=False)
    except Exception as exc:
        message = str(exc).lower()
        if any(token in message for token in ("login", "sign in", "private", "cookies")):
            raise MediaExtractionError(
                "هذا الرابط غير متاح للزائر بدون تسجيل دخول، أو أن المحتوى خاص. "
                "الأداة لا تتجاوز حماية المنصة."
            ) from exc
        raise MediaExtractionError(
            "تعذر تحليل الرابط. تأكد أن المحتوى عام وأن الرابط يعمل في نافذة خاصة بدون تسجيل دخول."
        ) from exc

    platform = (
        (info or {}).get("extractor_key")
        or (info or {}).get("extractor")
        or (urlparse(source_url).hostname or "موقع")
    )
    entries = _flatten_entries(info or {})
    items: list[dict] = []

    for entry in entries:
        has_video = _has_video(entry)
        if mode == "audio" and not has_video:
            item = None
        elif mode == "original" and not has_video:
            item = _image_item(entry, source_url, str(platform))
        elif not has_video:
            item = _image_item(entry, source_url, str(platform))
        else:
            item = _downloadable_item(
                entry, source_url, str(platform), mode, quality
            )
        if item:
            items.append(item)

    if not items:
        raise MediaExtractionError(
            "لم يتم العثور على وسائط قابلة للتنزيل من هذا الرابط بدون تسجيل دخول."
        )

    return {
        "title": (info or {}).get("title") or f"وسائط من {platform}",
        "method": "yt-dlp-public",
        "platform": str(platform),
        "items": items,
    }
