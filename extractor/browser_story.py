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


def _looks_like_direct_media(url: str | None) -> bool:
    if not url:
        return False
    value = url.lower()
    if value.startswith(("blob:", "data:")):
        return False
    return value.startswith(("http://", "https://"))


def _media_extension(url: str, media_type: str, content_type: str = "") -> str:
    content_type = content_type.lower()
    if "video/mp4" in content_type:
        return "mp4"
    if "video/webm" in content_type:
        return "webm"
    if "image/png" in content_type:
        return "png"
    if "image/webp" in content_type:
        return "webp"
    if "image/gif" in content_type:
        return "gif"
    path = urlsplit(url).path.lower()
    match = re.search(r"\.([a-z0-9]{2,5})$", path)
    if match:
        return match.group(1)
    return "mp4" if media_type == "video" else "jpg"


def _latest_network_media(
    responses: deque[dict], media_type: str, already_seen: set[str]
) -> dict | None:
    for response in reversed(responses):
        if response["type"] != media_type:
            continue
        if response["url"] in already_seen:
            continue
        return response
    return None


def _visible_media(page) -> dict | None:
    return page.evaluate(
        """
        () => {
          const candidates = [];
          const viewportCenterX = window.innerWidth / 2;
          const viewportCenterY = window.innerHeight / 2;

          function addCandidate(el, type) {
            const rect = el.getBoundingClientRect();
            const style = getComputedStyle(el);
            if (
              style.display === 'none' || style.visibility === 'hidden' ||
              Number(style.opacity || 1) < 0.05 ||
              rect.width < 220 || rect.height < 220 ||
              rect.bottom <= 0 || rect.right <= 0 ||
              rect.top >= window.innerHeight || rect.left >= window.innerWidth
            ) return;

            const centerX = rect.left + rect.width / 2;
            const centerY = rect.top + rect.height / 2;
            const distance = Math.hypot(centerX - viewportCenterX, centerY - viewportCenterY);
            const area = rect.width * rect.height;
            const centerBonus = 1 / (1 + distance / 1000);
            const src = type === 'video'
              ? (el.currentSrc || el.src || el.querySelector('source')?.src || '')
              : (el.currentSrc || el.src || '');

            candidates.push({
              type,
              src,
              poster: type === 'video' ? (el.poster || '') : '',
              width: Math.round(rect.width),
              height: Math.round(rect.height),
              score: area * centerBonus,
            });
          }

          document.querySelectorAll('video').forEach((el) => addCandidate(el, 'video'));
          document.querySelectorAll('img').forEach((el) => addCandidate(el, 'image'));
          candidates.sort((a, b) => b.score - a.score);
          return candidates[0] || null;
        }
        """
    )


def _current_fingerprint(
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

    fingerprint = source if source else (
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


def _click_next(page) -> bool:
    patterns = [
        re.compile(r"^Next$", re.I),
        re.compile(r"Next (card|photo|video|story)", re.I),
        re.compile(r"^(التالي|القصة التالية)$", re.I),
        re.compile(r"^Nästa", re.I),
    ]
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
        page.keyboard.press("ArrowRight")
        return True
    except Exception:
        return False


def _wait_for_change(
    page, previous: str, responses: deque[dict], seen_urls: set[str]
) -> bool:
    timeout_seconds = float(os.getenv("STORY_NEXT_TIMEOUT", "4.5"))
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        time.sleep(0.3)
        try:
            current, _ = _current_fingerprint(page, responses, seen_urls)
        except Exception:
            continue
        if current and current != previous:
            return True
    return False


def extract_story_sequence(url: str) -> dict:
    """Enumerate visible Facebook story cards in the browser viewer.

    Opens the story viewer, captures the largest visible media element,
    advances to the next card, and stops when the card no longer changes.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise BrowserStoryError(
            "مكتبة Playwright غير مثبتة، لذلك تعذر فحص جميع أجزاء الستوري."
        ) from exc

    headless = os.getenv("STORY_BROWSER_HEADLESS", "1") != "0"
    max_items = max(2, min(int(os.getenv("STORY_MAX_ITEMS", "50")), 100))
    normalized_url = sequence_url(url)
    responses: deque[dict] = deque(maxlen=250)
    seen_urls: set[str] = set()
    items: list[dict] = []

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
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
                    "Facebook طلب تسجيل الدخول. أضف ملف cookies.txt صالحًا ثم أعد التحليل."
                )

            unchanged_steps = 0
            for _ in range(max_items):
                fingerprint, snapshot = _current_fingerprint(
                    page, responses, seen_urls
                )
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
                                "http_headers": {
                                    "Referer": snapshot["page_url"],
                                },
                            }
                        )

                if not _click_next(page):
                    break
                if _wait_for_change(
                    page, fingerprint, responses, seen_urls
                ):
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
            "تعذر تشغيل متصفح فحص الستوري. تأكد من تثبيت Chromium الخاص بـ Playwright."
        ) from exc

    if not items:
        raise BrowserStoryError(
            "لم يتمكن المتصفح من التقاط عناصر الستوري. قد تحتاج إلى cookies.txt صالح."
        )

    return {
        "title": title,
        "method": "playwright-story-sequence",
        "items": items,
        "sequence_url": normalized_url,
    }
