import subprocess
import os


def merge_with_ffmpeg(files, output="story_final.mp4"):
    """Merge video files using ffmpeg concat demuxer."""
    list_file = "merge_list.txt"

    with open(list_file, "w", encoding="utf-8") as f:
        for item in files:
            f.write(f"file '{os.path.abspath(item)}'\n")

    command = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", list_file,
        "-c", "copy",
        output
    ]

    subprocess.run(command, check=True)
    return output
