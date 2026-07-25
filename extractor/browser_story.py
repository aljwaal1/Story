from __future__ import annotations

import os
import re
import time
from collections import deque
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .facebook_cookies import playwright_cookies


class BrowserStoryError(RuntimeError):
    pass


_REMOVE_QUERY_KEYS = {
    "view_single",
    "source",
    "mibextid",
    "__tn__",
    "refsrc",
    "ref",
}


def sequence_url(url: str) -> str:
    """Remove query flags that force Facebook to show one story card only."""
    parts = urlsplit(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in _REMOVE_QUERY_KEYS
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def _compact_error(exc: Exception, limit: int = 700) -> str:
    text = re.sub(r"\s+", " ", str(exc)).strip()
    if not text:
        text = exc.__class__.__name__
    return text[:limit]


def _looks_like_direct_media(url: str | None) -> bool:
    if not url:
        return False
    value = url.lower()
    return not value.startswith(("blob:", "data:")) and value.startswith(
        ("http://", "https://")
    )


def _media_extension(url: str, media_type: str, content_type: str = "") -> str:
    content_type = content_type.lower()
    content_extensions = {
        "video/mp4": "mp4",
        "video/webm": "webm",
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "image/gif": "gif",
    }
    for prefix, extension in content_extensions.items():
        if prefix in content_type:
            return extension
    match = re.search(r"\.([a-z0-9]{2,5})$", urlsplit(url).path.lower())
    if match:
        return match.group(1)
    return "mp4" if media_type == "video" else "jpg"


def _latest_network_media(
    responses: deque[dict], media_type: str, already_seen: set[str]
) -> dict | None:
    for response in reversed(responses):
        if response["type"] == media_type and response["url"] not in already_seen:
            return response
    return None


def _visible_media(page) -> dict | None:
    return page.evaluate(
        """
        () => {
          const candidates = [];
          const cx = window.innerWidth / 2;
          const cy = window.innerHeight / 2;

          function add(el, type) {
            const rect = el.getBoundingClientRect();
            const style = getComputedStyle(el);
            if (
              style.display === 'none' || style.visibility === 'hidden' ||
              Number(style.opacity || 1) < 0.05 ||
              rect.width < 220 || rect.height < 220 ||
              rect.bottom <= 0 || rect.right <= 0 ||
              rect.top >= window.innerHeight || rect.left >= window.innerWidth
            ) return;

            const x = rect.left + rect.width / 2;
            const y = rect.top + rect.height / 2;
            const distance = Math.hypot(x - cx, y - cy);
            const src = type === 'video'
              ? (el.currentSrc || el.src || el.querySelector('source')?.src || '')
              : (el.currentSrc || el.src || '');

            candidates.push({
              type,
              src,
              poster: type === 'video' ? (el.poster || '') : '',
              width: Math.round(rect.width),
              height: Math.round(rect.height),
              score: (rect.width * rect.height) / (1 + distance / 1000),
            });
          }

          document.querySelectorAll('video').forEach((el) => add(el, 'video'));
          document.querySelectorAll('img').forEach((el) => add(el, 'image'));
          candidates.sort((a, b) => b.score - a.score);
          return candidates[0] || null;
        }
        """
    )


def _current_snapshot(
    page, responses: deque[dict], seen_urls: set[str]
) -> tuple[str, dict | None]:
    visible = _visible_media(page)
    if not visible:
        return page.url, None

    media_type = visible["type"]
    source = visible.get("src")
    network = None
    if not _looks_like_direct_media(source):
        network = _latest_network_media(responses, media_type, seen_urls)
        source = network["url"] if network else source

    fingerprint = source or (
        f"{page.url}|{media_type}|{visible.get('width')}x{visible.get('height')}"
    )
    return fingerprint, {
        "type": media_type,
        "url": source,
        "thumbnail": visible.get("poster")
        or (source if media_type == "image" else None),
        "content_type": network.get("content_type", "") if network else "",
        "page_url": page.url,
    }


def _click_direction(page, direction: str) -> bool:
    if direction == "next":
        patterns = [
            re.compile(r"^Next$", re.I),
            re.compile(r"Next (card|photo|video|story)", re.I),
            re.compile(r"^(التالي|القصة التالية)$", re.I),
            re.compile(r"^Nästa", re.I),
        ]
        key = "ArrowRight"
    else:
        patterns = [
            re.compile(r"^Previous$", re.I),
            re.compile(r"Previous (card|photo|video|story)", re.I),
            re.compile(r"^(السابق|القصة السابقة)$", re.I),
            re.compile(r"^Föregående", re.I),
        ]
        key = "ArrowLeft"

    for pattern in patterns:
        locator = page.get_by_role("button", name=pattern)
        try:
            count = locator.count()
        except Exception:
            count = 0
        for index in range(count - 1, -1, -1):
            button = locator.nth(index)
            try:
                if button.is_visible() and button.is_enabled():
                    button.click(timeout=1500)
                    return True
            except Exception:
                continue

    try:
        page.keyboard.press(key)
        return True
    except Exception:
        return False


def _wait_for_change(
    page, previous: str, responses: deque[dict], seen_urls: set[str]
) -> bool:
    deadline = time.monotonic() + float(os.getenv("STORY_NEXT_TIMEOUT", "4.5"))
    while time.monotonic() < deadline:
        time.sleep(0.3)
        try:
            current, _ = _current_snapshot(page, responses, seen_urls)
        except Exception:
            continue
        if current and current != previous:
            return True
    return False


def _rewind_to_first(page, responses: deque[dict], max_items: int) -> None:
    empty_seen: set[str] = set()
    unchanged_steps = 0
    for _ in range(max_items):
        fingerprint, _ = _current_snapshot(page, responses, empty_seen)
        if not _click_direction(page, "previous"):
            break
        if _wait_for_change(page, fingerprint, responses, empty_seen):
            unchanged_steps = 0
        else:
            unchanged_steps += 1
            if unchanged_steps >= 2:
                break


def launch_story_browser(playwright, headless: bool = True):
    """Launch bundled Chromium, then fall back to installed Edge or Chrome."""
    preferred = os.getenv("STORY_BROWSER_CHANNEL", "").strip().lower()
    candidates: list[tuple[str, dict]] = []

    if preferred:
        if preferred in {"chromium", "bundled", "default"}:
            candidates.append(("Playwright Chromium", {}))
        else:
            candidates.append((preferred, {"channel": preferred}))

    candidates.extend(
        [
            ("Playwright Chromium", {}),
            ("Microsoft Edge", {"channel": "msedge"}),
            ("Google Chrome", {"channel": "chrome"}),
        ]
    )

    unique: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for label, kwargs in candidates:
        key = str(kwargs)
        if key not in seen:
            seen.add(key)
            unique.append((label, kwargs))

    errors: list[str] = []
    for label, kwargs in unique:
        try:
            browser = playwright.chromium.launch(headless=headless, **kwargs)
            return browser, label
        except Exception as exc:
            errors.append(f"{label}: {_compact_error(exc, 260)}")

    details = " | ".join(errors)
    raise BrowserStoryError(
        "تعذر فتح Chromium أو Microsoft Edge أو Google Chrome. "
        "شغّل repair_browser.bat ثم أعد المحاولة. "
        f"التفاصيل: {details}"
    )


def extract_story_sequence(url: str) -> dict:
    """Open the Facebook viewer and enumerate all visible story cards."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise BrowserStoryError(
            "مكتبة Playwright غير مثبتة. شغّل repair_browser.bat ثم أعد المحاولة."
        ) from exc

    headless = os.getenv("STORY_BROWSER_HEADLESS", "1") != "0"
    max_items = max(2, min(int(os.getenv("STORY_MAX_ITEMS", "50")), 100))
    normalized_url = sequence_url(url)
    responses: deque[dict] = deque(maxlen=250)
    seen_urls: set[str] = set()
    items: list[dict] = []
    browser_name = "unknown"

    try:
        with sync_playwright() as playwright:
            browser, browser_name = launch_story_browser(playwright, headless=headless)
            context = browser.new_context(
                locale="en-US",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                ),
                viewport={"width": 1440, "height": 1000},
                service_workers="block",
            )
            cookies = playwright_cookies()
            if cookies:
                context.add_cookies(cookies)

            page = context.new_page()

            def on_response(response) -> None:
                try:
                    content_type = response.headers.get("content-type", "").lower()
                    media_type = None
                    if content_type.startswith("video/"):
                        media_type = "video"
                    elif content_type.startswith("image/"):
                        media_type = "image"
                    elif re.search(r"\.(mp4|webm)(?:\?|$)", response.url, re.I):
                        media_type = "video"
                    if media_type and _looks_like_direct_media(response.url):
                        responses.append(
                            {
                                "type": media_type,
                                "url": response.url,
                                "content_type": content_type,
                            }
                        )
                except Exception:
                    return

            page.on("response", on_response)
            page.goto(
                normalized_url,
                wait_until="domcontentloaded",
                timeout=45_000,
            )
            page.wait_for_timeout(2500)

            if "/login" in page.url.lower():
                raise BrowserStoryError(
                    "Facebook طلب تسجيل الدخول. أضف cookies.txt صالحًا ثم أعد التحليل."
                )

            _rewind_to_first(page, responses, max_items)
            page.wait_for_timeout(700)

            unchanged_steps = 0
            for _ in range(max_items):
                fingerprint, snapshot = _current_snapshot(page, responses, seen_urls)
                if snapshot and _looks_like_direct_media(snapshot.get("url")):
                    media_url = snapshot["url"]
                    if media_url not in seen_urls:
                        seen_urls.add(media_url)
                        media_type = snapshot["type"]
                        items.append(
                            {
                                "type": media_type,
                                "url": media_url,
                                "source_url": snapshot["page_url"],
                                "title": f"جزء الستوري {len(items) + 1}",
                                "extension": _media_extension(
                                    media_url,
                                    media_type,
                                    snapshot.get("content_type", ""),
                                ),
                                "thumbnail": snapshot.get("thumbnail"),
                                "http_headers": {"Referer": snapshot["page_url"]},
                            }
                        )

                if not _click_direction(page, "next"):
                    break
                if _wait_for_change(page, fingerprint, responses, seen_urls):
                    unchanged_steps = 0
                else:
                    unchanged_steps += 1
                    if unchanged_steps >= 2:
                        break

            title = page.title() or "قصة فيسبوك"
            context.close()
            browser.close()
    except BrowserStoryError:
        raise
    except Exception as exc:
        raise BrowserStoryError(
            "تم فتح المتصفح ولكن فشل فحص صفحة Facebook. "
            f"المتصفح: {browser_name}. التفاصيل: {_compact_error(exc)}"
        ) from exc

    if not items:
        raise BrowserStoryError(
            "تم تشغيل المتصفح، لكن لم يتم التقاط عناصر الستوري. "
            "قد تحتاج إلى cookies.txt صالح أو قد تكون القصة منتهية. "
            f"المتصفح المستخدم: {browser_name}."
        )

    return {
        "title": title,
        "method": f"playwright-story-sequence:{browser_name}",
        "items": items,
        "sequence_url": normalized_url,
    }
