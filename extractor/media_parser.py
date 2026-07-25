import json


def normalize_items(items):
    """Normalize discovered story media items.

    Each item format:
    {type: video/image, url: media_url, order: number}
    """
    result = []
    for index, item in enumerate(items, start=1):
        result.append({
            "order": index,
            "type": item.get("type", "unknown"),
            "url": item.get("url")
        })
    return result


def export_manifest(items, path="story_manifest.json"):
    with open(path, "w", encoding="utf-8") as file:
        json.dump(items, file, ensure_ascii=False, indent=2)
    return path
