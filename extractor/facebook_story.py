from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


class StoryExtractionError(RuntimeError):
    pass


_ALLOWED_FACEBOOK_HOSTS = {"facebook.com", "www.facebook.com", "m.facebook.com", "mobile.facebook.com", "web.facebook.com", "fb.watch"}
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def parse_story_url(url: str) -> dict:
    value = (url or "").strip()
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in _ALLOWED_FACEBOOK_HOSTS:
        raise StoryExtractionError("الرابط يجب أن يكون رابطًا صحيحًا من Facebook.")
    return {"url": value, "host": host, "path": parsed.path, "is_story_url": "/stories/" in parsed.path or host == "fb.watch"}


def _cookie_file() -> str | None:
    configured = os.getenv("FACEBOOK_COOKIES_FILE", "").strip()
    candidates = [Path(configured)] if configured else []
    candidates.extend([Path("cookies.txt"), Path(__file__).resolve().parents[1] / "cookies.txt"])
    for path in candidates:
        if path.is_file():
            return str(path.resolve())
    return None


def _flatten_entries(info: dict) -> list[dict]:
    entries = info.get("entries")
    if not entries:
        return [info]
    flattened: list[dict] = []
    for entry in entries:
        if entry:
            flattened.extend(_flatten_entries(entry))
    return flattened


def _choose_format(entry: dict) -> dict | None:
    formats = [fmt for fmt in entry.get("formats", []) if fmt.get("url")]
    if not formats:
        return None
    def score(fmt: dict) -> tuple:
        has_video = fmt.get("vcodec") not in {None, "none"}
        has_audio = fmt.get("acodec") not in {None, "none"}
        return (has_video and has_audio, has_video, int(fmt.get("height") or 0), float(fmt.get("tbr") or 0))
    return max(formats, key=score)


def _entry_to_item(entry: dict, source_url: str) -> dict | None:
    ext = str(entry.get("ext") or "").lower()
    selected_format = _choose_format(entry)
    media_url = entry.get("url")
    if selected_format:
        media_url = selected_format.get("url") or media_url
        ext = str(selected_format.get("ext") or ext).lower()
    is_video = entry.get("vcodec") not in {None, "none"} or (selected_format and selected_format.get("vcodec") not in {None, "none"}) or ext in {"mp4", "m4v", "mov", "webm", "mkv"}
    if not media_url and not is_video:
        thumbnails = [thumb for thumb in entry.get("thumbnails", []) if thumb.get("url")]
        if thumbnails:
            media_url = thumbnails[-1]["url"]
            ext = ext if ext in {"jpg", "jpeg", "png", "webp", "gif"} else "jpg"
    if not media_url:
        return None
    return {
        "type": "video" if is_video else "image", "url": media_url,
        "source_url": entry.get("webpage_url") or source_url,
        "title": entry.get("title") or entry.get("description") or "عنصر قصة",
        "extension": ext or ("mp4" if is_video else "jpg"), "thumbnail": entry.get("thumbnail"),
        "duration": entry.get("duration"), "http_headers": entry.get("http_headers") or {"User-Agent": _USER_AGENT},
    }


def _extract_with_ytdlp(url: str) -> dict:
    try:
        import yt_dlp
    except ImportError as exc:
        raise StoryExtractionError("مكتبة yt-dlp غير مثبتة. نفّذ pip install -r requirements.txt ثم أعد التشغيل.") from exc
    options = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": False, "extract_flat": False, "http_headers": {"User-Agent": _USER_AGENT}}
    cookie_file = _cookie_file()
    if cookie_file:
        options["cookiefile"] = cookie_file
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        raise StoryExtractionError("تعذر تحليل القصة بواسطة yt-dlp. تأكد أن القصة عامة ولم تنتهِ، أو أضف cookies.txt عند الحاجة لتسجيل الدخول.") from exc
    items, seen = [], set()
    for entry in _flatten_entries(info or {}):
        item = _entry_to_item(entry, url)
        if item and item["url"] not in seen:
            seen.add(item["url"])
            items.append(item)
    return {"title": (info or {}).get("title") or "قصة فيسبوك", "method": "yt-dlp", "items": items}


def _extract_open_graph(url: str) -> dict:
    try:
        response = requests.get(url, headers={"User-Agent": _USER_AGENT, "Accept-Language": "ar,en;q=0.8"}, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise StoryExtractionError("تعذر فتح رابط القصة من Facebook.") from exc
    soup = BeautifulSoup(response.text, "html.parser")
    title_tag = soup.select_one('meta[property="og:title"]')
    title = title_tag.get("content") if title_tag else "قصة فيسبوك"
    items, seen = [], set()
    for media_type, selector, extension in (("video", 'meta[property="og:video"]', "mp4"), ("video", 'meta[property="og:video:url"]', "mp4"), ("image", 'meta[property="og:image"]', "jpg")):
        for tag in soup.select(selector):
            media_url = tag.get("content")
            if not media_url or media_url in seen:
                continue
            seen.add(media_url)
            items.append({"type": media_type, "url": media_url, "source_url": url, "title": title, "extension": extension, "thumbnail": media_url if media_type == "image" else None, "http_headers": {"User-Agent": _USER_AGENT, "Referer": url}})
    return {"title": title, "method": "open-graph", "items": items}


def discover_media(url: str) -> dict:
    parsed = parse_story_url(url)
    try:
        result = _extract_with_ytdlp(parsed["url"])
        if result.get("items"):
            return result
    except StoryExtractionError as ytdlp_error:
        try:
            fallback = _extract_open_graph(parsed["url"])
            if fallback.get("items"):
                return fallback
        except StoryExtractionError:
            pass
        raise ytdlp_error
    fallback = _extract_open_graph(parsed["url"])
    if fallback.get("items"):
        return fallback
    raise StoryExtractionError("لم يتم العثور على عناصر وسائط في رابط القصة.")
