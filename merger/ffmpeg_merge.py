from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


class MergeError(RuntimeError):
    pass


def _concat_line(path: Path) -> str:
    escaped = str(path.resolve()).replace("'", "'\\''")
    return f"file '{escaped}'\n"


def _run(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace")


def merge_with_ffmpeg(files: list[Path | str], output: Path | str) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise MergeError("برنامج FFmpeg غير مثبت أو غير مضاف إلى PATH.")
    inputs = [Path(file) for file in files]
    if len(inputs) < 2:
        raise MergeError("الدمج يحتاج إلى مقطعين على الأقل.")
    if any(not path.is_file() for path in inputs):
        raise MergeError("بعض ملفات الدمج غير موجودة على الجهاز.")
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False, dir=output_path.parent) as list_file:
        for path in inputs:
            list_file.write(_concat_line(path))
        list_path = Path(list_file.name)
    copy_command = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_path), "-c", "copy", "-movflags", "+faststart", str(output_path)]
    result = _run(copy_command)
    if result.returncode != 0:
        transcode_command = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_path), "-c:v", "libx264", "-preset", "medium", "-crf", "22", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(output_path)]
        result = _run(transcode_command)
    list_path.unlink(missing_ok=True)
    if result.returncode != 0 or not output_path.is_file():
        details = (result.stderr or "").strip()[-500:]
        raise MergeError(f"فشل FFmpeg في دمج المقاطع. {details}")
    return output_path
