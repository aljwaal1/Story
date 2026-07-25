from __future__ import annotations

from pathlib import Path

from .media_downloader import DownloadError, download_item


def download_queue(items: list[dict], folder: Path | str = "downloads") -> dict:
    downloaded: list[str] = []
    errors: list[dict] = []
    for item in items:
        try:
            path = download_item(item, folder)
            downloaded.append(str(path))
        except DownloadError as exc:
            errors.append({"order": item.get("order"), "error": str(exc)})
    return {"downloaded": downloaded, "errors": errors}
