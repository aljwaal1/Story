"""Video merge placeholder.

Will be connected to ffmpeg in next stage.
"""


def merge_videos(files, output="story_final.mp4"):
    return {
        "output": output,
        "files": files,
        "status": "ready_for_ffmpeg"
    }
