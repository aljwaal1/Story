from __future__ import annotations

import mimetypes
import os
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse

import requests


class DownloadError(RuntimeError):
    pass


_MAX_FILE_SIZE = int(os.getenv("MEDIA_MAX_FILE_SIZE", str(750 * 1024 * 1024)))


def _safe_name(value: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", value or "media")
    return name[:120] or "media"


def _extension_from_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    content_type = content_type.split(";", 1)[0].strip().lower()
    custom = {
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "audio/mp4": ".m4a",
        "audio/mpeg": ".mp3",
        "audio/webm": ".webm",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }
    return custom.get(content_type) or mimetypes.guess_extension(content_type)


def _download_with_ytdlp(item: dict, target_folder: Path) -> Path:
    try:
        import yt_dlp
    except ImportError as exc:
        raise DownloadError("مكتبة yt-dlp غير مثبتة.") from exc

    filename = _safe_name(item.get("filename") or "media.bin")
    stem = Path(filename).stem
    output_template = str(target_folder / f"{stem}.%(ext)s")
    before = set(target_folder.glob(f"{stem}.*"))

    format_selector = item.get("format_selector") or "best"
    if (
        item.get("type") == "video"
        and "+" in format_selector
        and not shutil.which("ffmpeg")
    ):
        format_selector = item.get("fallback_format_selector") or "best"

    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": format_selector,
        "merge_output_format": "mp4",
        "outtmpl": output_template,
        "overwrites": True,
        "http_headers": item.get("http_headers") or {},
        "socket_timeout": 30,
        "max_filesize": _MAX_FILE_SIZE,
    }

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([str(item.get("source_url") or item.get("url"))])
    except Exception as exc:
        message = str(exc).lower()
        if any(token in message for token in ("login", "sign in", "private", "cookies")):
            raise DownloadError(
                "لا يمكن تنزيل هذا المحتوى بدون تسجيل دخول لأنه خاص أو مقيّد."
            ) from exc
        raise DownloadError("تعذر تنزيل الملف بواسطة yt-dlp.") from exc

    candidates = [
        path
        for path in target_folder.glob(f"{stem}.*")
        if path.is_file() and path.suffix != ".part" and path not in before
    ]
    if not candidates:
        candidates = [
            path
            for path in target_folder.glob(f"{stem}.*")
            if path.is_file() and path.suffix != ".part"
        ]
    if not candidates:
        raise DownloadError("اكتمل أمر التنزيل لكن لم يتم العثور على الملف الناتج.")

    return max(candidates, key=lambda path: path.stat().st_mtime)


def _download_direct(item: dict, target_folder: Path) -> Path:
    url = str(item.get("url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise DownloadError("رابط الوسائط غير صالح.")

    filename = _safe_name(item.get("filename") or "media")
    target = target_folder / filename
    partial = target.with_suffix(target.suffix + ".part")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        )
    }
    headers.update(item.get("http_headers") or {})

    try:
        with requests.get(
            url,
            headers=headers,
            stream=True,
            timeout=(15, 90),
            allow_redirects=True,
        ) as response:
            response.raise_for_status()
            announced_size = int(response.headers.get("Content-Length") or 0)
            if announced_size > _MAX_FILE_SIZE:
                raise DownloadError("حجم الملف أكبر من الحد المسموح.")

            content_type = response.headers.get("Content-Type")
            if not target.suffix:
                extension = _extension_from_content_type(content_type)
                if extension:
                    target = target.with_suffix(extension)
                    partial = target.with_suffix(target.suffix + ".part")

            total = 0
            with partial.open("wb") as file:
                for chunk in response.iter_content(chunk_size=128 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > _MAX_FILE_SIZE:
                        raise DownloadError("تجاوز الملف الحد الأقصى أثناء التحميل.")
                    file.write(chunk)
    except requests.RequestException as exc:
        partial.unlink(missing_ok=True)
        raise DownloadError("تعذر تنزيل ملف الوسائط من المصدر.") from exc
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise DownloadError("تعذر حفظ الملف على الجهاز.") from exc

    partial.replace(target)
    item["mime_type"] = response.headers.get("Content-Type", "").split(";", 1)[0]
    return target


def download_item(item: dict, folder: Path | str) -> Path:
    target_folder = Path(folder)
    target_folder.mkdir(parents=True, exist_ok=True)

    if item.get("download_via") == "yt-dlp":
        return _download_with_ytdlp(item, target_folder)
    return _download_direct(item, target_folder)
