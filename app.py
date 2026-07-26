from __future__ import annotations

import os
import shutil
import zipfile
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.exceptions import HTTPException

from downloader.media_downloader import DownloadError, download_item
from extractor.media_parser import normalize_items
from extractor.universal_media import MediaExtractionError, discover_media
from merger.ffmpeg_merge import MergeError, merge_with_ffmpeg
from storage import JobNotFoundError, JobStore

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("MEDIA_DATA_DIR", os.getenv("STORY_DATA_DIR", BASE_DIR / "data")))
DOWNLOADS_DIR = Path(
    os.getenv("MEDIA_DOWNLOADS_DIR", os.getenv("STORY_DOWNLOADS_DIR", BASE_DIR / "downloads"))
)

app = Flask(
    __name__,
    template_folder="web",
    static_folder="web",
    static_url_path="/static",
)
app.config.update(
    JSON_AS_ASCII=False,
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
)

store = JobStore(DATA_DIR)
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)


def _payload() -> dict:
    return request.get_json(silent=True) or request.form.to_dict()


def _job_download_dir(job_id: str) -> Path:
    path = (DOWNLOADS_DIR / job_id).resolve()
    if DOWNLOADS_DIR.resolve() not in path.parents:
        raise JobNotFoundError("معرّف العملية غير صالح.")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _download_one(job_id: str, order: int) -> tuple[Path, dict]:
    job = store.get_job(job_id)
    item = next((entry for entry in job["items"] if entry["order"] == order), None)
    if not item:
        raise JobNotFoundError("ملف الوسائط المطلوب غير موجود.")

    folder = _job_download_dir(job_id)
    existing_name = item.get("downloaded_name")
    if existing_name:
        existing = folder / existing_name
        if existing.is_file():
            return existing, item

    path = download_item(item, folder)
    item["downloaded_name"] = path.name
    item["downloaded_size"] = path.stat().st_size
    store.replace_item(job_id, item)
    store.add_event(job_id, "download", f"تم تحميل العنصر رقم {order}")
    return path, item


@app.get("/")
def index():
    return render_template("index.html", history=store.list_jobs(limit=20))


@app.post("/api/analyze")
def analyze_media():
    payload = _payload()
    url = str(payload.get("url", "")).strip()
    mode = str(payload.get("mode", "video")).strip().lower()
    quality = str(payload.get("quality", "best")).strip().lower()

    if not url:
        return jsonify({"ok": False, "error": "أدخل رابط المحتوى أولًا."}), 400

    discovered = discover_media(url, mode=mode, quality=quality)
    items = normalize_items(discovered.get("items", []))
    if not items:
        raise MediaExtractionError(
            "لم يتم العثور على وسائط قابلة للتنزيل بدون تسجيل دخول."
        )

    job = store.create_job(
        source_url=url,
        items=items,
        extraction_method=discovered.get("method", "unknown"),
        title=discovered.get("title") or "تنزيل وسائط",
    )
    job["platform"] = discovered.get("platform")
    return jsonify({"ok": True, "job": job})


@app.get("/api/jobs/<job_id>")
def get_job(job_id: str):
    return jsonify({"ok": True, "job": store.get_job(job_id)})


@app.get("/api/jobs/<job_id>/download/<int:order>")
def download_single(job_id: str, order: int):
    path, item = _download_one(job_id, order)
    return send_file(
        path,
        as_attachment=True,
        download_name=path.name,
        mimetype=item.get("mime_type") or None,
        max_age=0,
    )


@app.get("/api/jobs/<job_id>/download-all")
def download_all(job_id: str):
    job = store.get_job(job_id)
    folder = _job_download_dir(job_id)
    files: list[Path] = []
    failures: list[str] = []

    for item in job["items"]:
        try:
            path, _ = _download_one(job_id, item["order"])
            files.append(path)
        except (DownloadError, OSError) as exc:
            failures.append(f"العنصر {item['order']}: {exc}")

    if not files:
        raise DownloadError("تعذر تحميل أي ملف من الرابط.")

    archive_path = folder / f"media_{job_id}.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, arcname=path.name)
        if failures:
            archive.writestr("download_errors.txt", "\n".join(failures))

    store.add_event(job_id, "download_all", f"تم تجهيز {len(files)} ملفًا")
    return send_file(
        archive_path,
        as_attachment=True,
        download_name=archive_path.name,
        mimetype="application/zip",
        max_age=0,
    )


@app.post("/api/jobs/<job_id>/merge")
def merge_videos(job_id: str):
    job = store.get_job(job_id)
    video_items = [item for item in job["items"] if item.get("type") == "video"]
    if len(video_items) < 2:
        raise MergeError("الدمج يحتاج إلى مقطعين فيديو على الأقل.")

    folder = _job_download_dir(job_id)
    video_paths: list[Path] = []
    for item in video_items:
        path, _ = _download_one(job_id, item["order"])
        video_paths.append(path)

    output = folder / f"media_{job_id}_merged.mp4"
    merged_path = merge_with_ffmpeg(video_paths, output)
    store.add_event(job_id, "merge", f"تم دمج {len(video_paths)} مقاطع")
    return send_file(
        merged_path,
        as_attachment=True,
        download_name=merged_path.name,
        mimetype="video/mp4",
        max_age=0,
    )


@app.get("/api/history")
def history():
    return jsonify({"ok": True, "history": store.list_jobs(limit=50)})


@app.delete("/api/jobs/<job_id>")
def delete_job(job_id: str):
    store.delete_job(job_id)
    shutil.rmtree(DOWNLOADS_DIR / job_id, ignore_errors=True)
    return jsonify({"ok": True})


@app.errorhandler(MediaExtractionError)
@app.errorhandler(DownloadError)
@app.errorhandler(MergeError)
@app.errorhandler(JobNotFoundError)
def handle_app_error(exc: Exception):
    return jsonify({"ok": False, "error": str(exc)}), 422


@app.errorhandler(HTTPException)
def handle_http_error(exc: HTTPException):
    return jsonify({"ok": False, "error": exc.description}), exc.code


@app.errorhandler(Exception)
def handle_unexpected_error(exc: Exception):
    app.logger.exception("Unexpected application error")
    return jsonify({"ok": False, "error": "حدث خطأ غير متوقع داخل التطبيق."}), 500


if __name__ == "__main__":
    app.run(
        host=os.getenv("MEDIA_HOST", os.getenv("STORY_HOST", "127.0.0.1")),
        port=int(os.getenv("MEDIA_PORT", os.getenv("STORY_PORT", "5000"))),
        debug=os.getenv("MEDIA_DEBUG", os.getenv("STORY_DEBUG", "0")) == "1",
    )
