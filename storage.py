from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


class JobNotFoundError(RuntimeError):
    pass


class JobStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.jobs_dir = self.root / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _validate_job_id(job_id: str) -> str:
        if not re.fullmatch(r"[a-f0-9]{12}", job_id or ""):
            raise JobNotFoundError("معرّف العملية غير صالح.")
        return job_id

    def _path(self, job_id: str) -> Path:
        return self.jobs_dir / f"{self._validate_job_id(job_id)}.json"

    def _write(self, path: Path, data: dict) -> None:
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temp_path.replace(path)

    def create_job(
        self,
        source_url: str,
        items: list[dict],
        extraction_method: str,
        title: str,
    ) -> dict:
        with self._lock:
            job_id = uuid.uuid4().hex[:12]
            created_at = self._now()
            job = {
                "id": job_id,
                "title": title,
                "source_url": source_url,
                "extraction_method": extraction_method,
                "created_at": created_at,
                "updated_at": created_at,
                "item_count": len(items),
                "video_count": sum(item.get("type") == "video" for item in items),
                "audio_count": sum(item.get("type") == "audio" for item in items),
                "image_count": sum(item.get("type") == "image" for item in items),
                "items": items,
                "events": [
                    {
                        "type": "analyze",
                        "message": f"تم اكتشاف {len(items)} عنصرًا",
                        "at": created_at,
                    }
                ],
            }
            self._write(self._path(job_id), job)
            return job

    def get_job(self, job_id: str) -> dict:
        path = self._path(job_id)
        if not path.is_file():
            raise JobNotFoundError("عملية التحليل المطلوبة غير موجودة.")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise JobNotFoundError("تعذر قراءة بيانات العملية.") from exc

    def replace_item(self, job_id: str, replacement: dict) -> dict:
        with self._lock:
            job = self.get_job(job_id)
            for index, item in enumerate(job["items"]):
                if item["order"] == replacement["order"]:
                    job["items"][index] = replacement
                    break
            else:
                raise JobNotFoundError("ملف الوسائط المطلوب غير موجود.")
            job["updated_at"] = self._now()
            self._write(self._path(job_id), job)
            return job

    def add_event(self, job_id: str, event_type: str, message: str) -> dict:
        with self._lock:
            job = self.get_job(job_id)
            now = self._now()
            job.setdefault("events", []).append(
                {"type": event_type, "message": message, "at": now}
            )
            job["updated_at"] = now
            self._write(self._path(job_id), job)
            return job

    def list_jobs(self, limit: int = 20) -> list[dict]:
        jobs: list[dict] = []
        for path in self.jobs_dir.glob("*.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            jobs.append(
                {
                    "id": job.get("id"),
                    "title": job.get("title"),
                    "source_url": job.get("source_url"),
                    "created_at": job.get("created_at"),
                    "updated_at": job.get("updated_at"),
                    "item_count": job.get("item_count", len(job.get("items", []))),
                    "video_count": job.get("video_count", 0),
                    "audio_count": job.get("audio_count", 0),
                    "image_count": job.get("image_count", 0),
                    "events": job.get("events", [])[-3:],
                }
            )
        jobs.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
        return jobs[: max(1, min(limit, 100))]

    def delete_job(self, job_id: str) -> None:
        with self._lock:
            path = self._path(job_id)
            if not path.is_file():
                raise JobNotFoundError("عملية التحليل المطلوبة غير موجودة.")
            path.unlink()
