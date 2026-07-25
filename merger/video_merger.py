from __future__ import annotations

from pathlib import Path

from .ffmpeg_merge import merge_with_ffmpeg


def merge_videos(files: list[str], output: str = "story_final.mp4") -> dict:
    merged = merge_with_ffmpeg([Path(file) for file in files], Path(output))
    return {"output": str(merged), "files": files, "status": "completed"}
