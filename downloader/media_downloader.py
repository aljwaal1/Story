from __future__ import annotations

import mimetypes
import os
import re
from pathlib import Path
from urllib.parse import urlparse

import requests


class DownloadError(RuntimeError):
    pass


_MAX_FILE_SIZE = int(os.getenv("STORY_MAX_FILE_SIZE", str(750 * 1024 * 1024)))


def _safe_name(value: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", value or "media")
    return name[:120] or "media"


def _extension_from_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    content_type = content_type.split(";", 1)[0].strip().lower()
    custom = {"video/mp4": ".mp4", "video/webm": ".webm", "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
    return custom.get(content_type) or mimetypes.guess_extension(content_type)


def download_item(item: dict, folder: Path | str) -> Path:
    url = str(item.get("url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise DownloadError("رابط الوسائط غير صالح.")
    target_folder = Path(folder)
    target_folder.mkdir(parents=True, exist_ok=True)
    filename = _safe_name(item.get("filename") or "media")
    target = target_folder / filename
    partial = target.with_suffix(target.suffix + ".part")
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
    headers.update(item.get("http_headers") or {})
    try:
        with requests.get(url, headers=headers, stream=True, timeout=(15, 90)) as response:
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
