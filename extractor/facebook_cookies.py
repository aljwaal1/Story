from __future__ import annotations

import json
import os
from http.cookiejar import MozillaCookieJar
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_STATE_FILE = BASE_DIR / ".auth" / "facebook_state.json"


def find_storage_state() -> Path | None:
    configured = os.getenv("FACEBOOK_STORAGE_STATE", "").strip()
    candidates = [Path(configured)] if configured else []
    candidates.append(DEFAULT_STATE_FILE)
    for path in candidates:
        if path.is_file():
            return path.resolve()
    return None


def find_cookie_file() -> Path | None:
    configured = os.getenv("FACEBOOK_COOKIES_FILE", "").strip()
    candidates = [Path(configured)] if configured else []
    candidates.extend([Path("cookies.txt"), BASE_DIR / "cookies.txt"])
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


def _storage_state_cookies() -> list[dict]:
    path = find_storage_state()
    if not path:
        return []

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return []

    result: list[dict] = []
    for cookie in payload.get("cookies", []):
        if not isinstance(cookie, dict):
            continue
        name = str(cookie.get("name") or "")
        value = str(cookie.get("value") or "")
        domain = str(cookie.get("domain") or "")
        if not name or not domain:
            continue

        item: dict = {
            "name": name,
            "value": value,
            "domain": domain,
            "path": str(cookie.get("path") or "/"),
            "secure": bool(cookie.get("secure")),
            "httpOnly": bool(cookie.get("httpOnly")),
        }

        expires = cookie.get("expires")
        try:
            expires_value = float(expires)
            if expires_value > 0:
                item["expires"] = expires_value
        except (TypeError, ValueError):
            pass

        same_site = str(cookie.get("sameSite") or "")
        if same_site in {"Strict", "Lax", "None"}:
            item["sameSite"] = same_site

        result.append(item)
    return result


def _netscape_cookies() -> list[dict]:
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


def playwright_cookies() -> list[dict]:
    """Return cookies from the saved Playwright session, then cookies.txt."""
    state_cookies = _storage_state_cookies()
    if state_cookies:
        return state_cookies
    return _netscape_cookies()
