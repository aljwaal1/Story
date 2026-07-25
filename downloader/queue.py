from .media_downloader import download_file


def download_queue(items, folder="downloads"):
    results = []
    for index, item in enumerate(items, start=1):
        if not item.get("url"):
            continue
        name = f"story_{index:02d}.mp4"
        results.append(download_file(item["url"], folder, name))
    return results
