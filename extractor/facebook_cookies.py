from __future__ import annotations

import os
from http.cookiejar import MozillaCookieJar
from pathlib import Path


def find_cookie_file() -> Path | None:
    configured = os.getenv("FACEBOOK_COOKIES_FILE", "").strip()
    candidates = [Path(configured)] if configured else []
    candidates.extend(
        [
            Path("cookies.txt"),
            Path(__file__).resolve().parents[1] / "cookies.txt",
        ]
    )
    for path in candidates:
        if path.is_file():
            return path.resolve()
    return None


def load_cookie_jar() -> MozillaCookieJar | None:
    path = find_cookie_file()
    if not path:
        return None

    jar = MozillaCookieJar(str(path))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except (OSError, ValueError):
        return None
    return jar


def playwright_cookies() -> list[dict]:
    jar = load_cookie_jar()
    if not jar:
        return []

    result: list[dict] = []
    for cookie in jar:
        item: dict = {
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain,
            "path": cookie.path or "/",
            "secure": bool(cookie.secure),
            "httpOnly": bool(cookie.has_nonstandard_attr("HttpOnly")),
        }
        if cookie.expires:
            item["expires"] = float(cookie.expires)
        result.append(item)
    return result
