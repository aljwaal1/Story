import os
import requests


def download_file(url, folder="downloads", name="media.mp4"):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)

    response = requests.get(url, stream=True, timeout=60)
    response.raise_for_status()

    with open(path, "wb") as file:
        for chunk in response.iter_content(8192):
            file.write(chunk)

    return path
