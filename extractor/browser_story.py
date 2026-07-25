from __future__ import annotations

import json
import os
import re
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .facebook_cookies import find_storage_state, playwright_cookies


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

_VIDEO_JSON_KEYS = {
    "playable_url",
    "playable_url_quality_hd",
    "browser_native_hd_url",
    "browser_native_sd_url",
    "progressive_url",
    "video_url",
    "hd_src",
    "sd_src",
}
_IMAGE_CONTEXT_WORDS = {
    "image",
    "photo",
    "thumbnail",
    "preview",
    "story",
    "media",
}
_BLOCKED_IMAGE_CONTEXT_WORDS = {
    "avatar",
    "profile_picture",
    "icon",
    "emoji",
    "badge",
    "logo",
}


def sequence_url(url: str) -> str:
    """Remove flags that force Facebook to show a single story card."""
    parts = urlsplit(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in _REMOVE_QUERY_KEYS
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def _compact_error(exc: Exception, limit: int = 700) -> str:
    text = re.sub(r"\s+", " ", str(exc)).strip()
    return (text or exc.__class__.__name__)[:limit]


def _looks_like_direct_media(url: str | None) -> bool:
    if not url:
        return False
    value = str(url).strip().lower()
    return value.startswith(("http://", "https://")) and not value.startswith(
        ("blob:", "data:")
    )


def _decode_json_url(value: str) -> str:
    value = value.strip()
    try:
        decoded = json.loads(f'"{value}"')
        if isinstance(decoded, str):
            return decoded.replace("\\/", "/")
    except (ValueError, TypeError, json.JSONDecodeError):
        pass
    return (
        value.replace("\\/", "/")
        .replace("\\u0025", "%")
        .replace("\\u0026", "&")
        .replace("\\u003d", "=")
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


def _network_score(entry: dict) -> float:
    media_type = entry.get("type")
    size = int(entry.get("content_length") or 0)
    priority = float(entry.get("priority") or 0)
    age = max(0.0, time.monotonic() - float(entry.get("seen_at") or 0))
    recency = max(0.0, 120.0 - age)
    type_bonus = 1_000_000_000 if media_type == "video" else 0
    return type_bonus + priority * 10_000_000 + min(size, 50_000_000) + recency


def _best_network_media(
    responses: deque[dict],
    already_seen: set[str],
    media_type: str | None = None,
) -> dict | None:
    candidates = [
        item
        for item in responses
        if item.get("url") not in already_seen
        and (media_type is None or item.get("type") == media_type)
    ]
    if not candidates:
        return None

    if media_type == "image":
        large = [
            item
            for item in candidates
            if int(item.get("content_length") or 0) >= 40_000
            or float(item.get("priority") or 0) >= 5
        ]
        if large:
            candidates = large

    return max(candidates, key=_network_score)


def _visible_media(page) -> list[dict]:
    return page.evaluate(
        """
        () => {
          const candidates = [];
          const cx = window.innerWidth / 2;
          const cy = window.innerHeight / 2;
          const seen = new Set();

          function isVisible(el, rect, style) {
            return !(
              style.display === 'none' ||
              style.visibility === 'hidden' ||
              Number(style.opacity || 1) < 0.03 ||
              rect.width < 80 ||
              rect.height < 80 ||
              rect.bottom <= 0 ||
              rect.right <= 0 ||
              rect.top >= window.innerHeight ||
              rect.left >= window.innerWidth
            );
          }

          function add(el, type, src, poster = '', source = 'dom') {
            src = String(src || '').trim();
            if (!src || seen.has(type + '|' + src)) return;

            const rect = el.getBoundingClientRect();
            const style = getComputedStyle(el);
            if (!isVisible(el, rect, style)) return;

            const x = rect.left + rect.width / 2;
            const y = rect.top + rect.height / 2;
            const distance = Math.hypot(x - cx, y - cy);
            const area = rect.width * rect.height;
            const typeBoost = type === 'video' ? 2.0 : 1.0;
            const centerBoost = 1 / (1 + distance / 900);
            seen.add(type + '|' + src);
            candidates.push({
              type,
              src,
              poster: String(poster || ''),
              width: Math.round(rect.width),
              height: Math.round(rect.height),
              area: Math.round(area),
              source,
              score: area * centerBoost * typeBoost,
            });
          }

          document.querySelectorAll('video').forEach((el) => {
            const src = el.currentSrc || el.src || el.querySelector('source')?.src || '';
            add(el, 'video', src, el.poster || '', 'video');
          });

          document.querySelectorAll('img').forEach((el) => {
            add(el, 'image', el.currentSrc || el.src || '', '', 'img');
          });

          const elements = document.querySelectorAll(
            'main, article, section, div[style], div[role="img"], span[style]'
          );
          let checked = 0;
          for (const el of elements) {
            if (++checked > 5000) break;
            const rect = el.getBoundingClientRect();
            const style = getComputedStyle(el);
            if (!isVisible(el, rect, style)) continue;
            const background = style.backgroundImage || '';
            const matches = [...background.matchAll(/url\(["']?([^"')]+)["']?\)/g)];
            for (const match of matches) {
              add(el, 'image', match[1], '', 'background');
            }
          }

          candidates.sort((a, b) => b.score - a.score);
          return candidates.slice(0, 20);
        }
        """
    )


def _current_snapshot(
    page, responses: deque[dict], seen_urls: set[str]
) -> tuple[str, dict | None]:
    visible_candidates: list[dict] = []
    try:
        visible_candidates = _visible_media(page) or []
    except Exception:
        visible_candidates = []

    for visible in visible_candidates:
        media_type = visible.get("type") or "image"
        source = visible.get("src")
        network = None

        if not _looks_like_direct_media(source):
            network = _best_network_media(responses, seen_urls, media_type)
            source = network.get("url") if network else None

        if not _looks_like_direct_media(source):
            continue

        return str(source), {
            "type": media_type,
            "url": str(source),
            "thumbnail": visible.get("poster")
            or (str(source) if media_type == "image" else None),
            "content_type": network.get("content_type", "") if network else "",
            "page_url": page.url,
            "capture_source": visible.get("source", "dom"),
        }

    for media_type in ("video", "image"):
        network = _best_network_media(responses, seen_urls, media_type)
        if network and _looks_like_direct_media(network.get("url")):
            source = str(network["url"])
            return source, {
                "type": media_type,
                "url": source,
                "thumbnail": source if media_type == "image" else None,
                "content_type": network.get("content_type", ""),
                "page_url": page.url,
                "capture_source": network.get("source", "network"),
            }

    fingerprint = f"{page.url}|responses={len(responses)}"
    return fingerprint, None


def _append_response(
    responses: deque[dict],
    media_type: str,
    url: str,
    *,
    content_type: str = "",
    content_length: int = 0,
    priority: int = 0,
    source: str = "network",
) -> None:
    if not _looks_like_direct_media(url):
        return
    cleaned = str(url).replace("\\/", "/")
    for existing in reversed(responses):
        if existing.get("url") == cleaned:
            if priority > int(existing.get("priority") or 0):
                existing["priority"] = priority
            return
    responses.append(
        {
            "type": media_type,
            "url": cleaned,
            "content_type": content_type,
            "content_length": content_length,
            "priority": priority,
            "source": source,
            "seen_at": time.monotonic(),
        }
    )


def _walk_json_media(
    value,
    responses: deque[dict],
    path: tuple[str, ...] = (),
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _walk_json_media(child, responses, (*path, str(key).lower()))
        return

    if isinstance(value, list):
        for child in value:
            _walk_json_media(child, responses, path)
        return

    if not isinstance(value, str):
        return

    url = _decode_json_url(value)
    if not _looks_like_direct_media(url):
        return

    key = path[-1] if path else ""
    context = " ".join(path[-5:])

    if key in _VIDEO_JSON_KEYS or any(
        marker in key for marker in ("playable", "video_url", "native_hd", "native_sd")
    ):
        _append_response(
            responses,
            "video",
            url,
            priority=10 if "hd" in key else 8,
            source=f"graphql:{key}",
        )
        return

    if any(word in context for word in _BLOCKED_IMAGE_CONTEXT_WORDS):
        return

    host = urlsplit(url).netloc.lower()
    looks_like_fb_image = any(
        marker in host for marker in ("fbcdn", "scontent", "fbsbx")
    )
    if (
        key in {"uri", "url", "src"}
        and looks_like_fb_image
        and any(word in context for word in _IMAGE_CONTEXT_WORDS)
    ):
        _append_response(
            responses,
            "image",
            url,
            priority=6,
            source=f"graphql:{key}",
        )


def _extract_graphql_media(text: str, responses: deque[dict]) -> None:
    if not text:
        return

    parsed_any = False
    for part in text.splitlines():
        candidate = part.strip()
        if not candidate:
            continue
        if candidate.startswith("for (;;);"):
            candidate = candidate[len("for (;;);") :]
        try:
            payload = json.loads(candidate)
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
        parsed_any = True
        _walk_json_media(payload, responses)

    if parsed_any:
        return

    video_pattern = re.compile(
        r'"(?:playable_url_quality_hd|playable_url|browser_native_hd_url|'
        r'browser_native_sd_url|progressive_url|video_url)"\s*:\s*"([^"]+)"',
        re.I,
    )
    for match in video_pattern.finditer(text):
        _append_response(
            responses,
            "video",
            _decode_json_url(match.group(1)),
            priority=9,
            source="graphql-regex",
        )


def _click_direction(page, direction: str) -> bool:
    if direction == "next":
        patterns = [
            re.compile(r"^Next$", re.I),
            re.compile(r"Next (card|photo|video|story)", re.I),
            re.compile(r"^(التالي|القصة التالية)$", re.I),
            re.compile(r"^Nästa", re.I),
        ]
        key = "ArrowRight"
        x_ratio = 0.88
    else:
        patterns = [
            re.compile(r"^Previous$", re.I),
            re.compile(r"Previous (card|photo|video|story)", re.I),
            re.compile(r"^(السابق|القصة السابقة)$", re.I),
            re.compile(r"^Föregående", re.I),
        ]
        key = "ArrowLeft"
        x_ratio = 0.12

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
        pass

    try:
        viewport = page.viewport_size or {"width": 1440, "height": 1000}
        page.mouse.click(
            int(viewport["width"] * x_ratio),
            int(viewport["height"] * 0.5),
        )
        return True
    except Exception:
        return False


def _wait_for_snapshot(
    page,
    responses: deque[dict],
    seen_urls: set[str],
    *,
    timeout_seconds: float = 10.0,
) -> tuple[str, dict | None]:
    deadline = time.monotonic() + timeout_seconds
    last: tuple[str, dict | None] = (page.url, None)
    while time.monotonic() < deadline:
        try:
            last = _current_snapshot(page, responses, seen_urls)
        except Exception:
            time.sleep(0.35)
            continue
        if last[1] is not None:
            return last
        time.sleep(0.35)
    return last


def _wait_for_change(
    page,
    previous: str,
    responses: deque[dict],
    seen_urls: set[str],
) -> tuple[bool, str, dict | None]:
    deadline = time.monotonic() + float(os.getenv("STORY_NEXT_TIMEOUT", "6.5"))
    latest: tuple[str, dict | None] = (previous, None)
    while time.monotonic() < deadline:
        time.sleep(0.35)
        try:
            latest = _current_snapshot(page, responses, seen_urls)
        except Exception:
            continue
        if latest[0] and latest[0] != previous and latest[1] is not None:
            return True, latest[0], latest[1]
    return False, latest[0], latest[1]


def _story_owner(url: str) -> str | None:
    match = re.search(r"/stories/([^/?#]+)/", urlsplit(url).path, re.I)
    return match.group(1) if match else None


def _same_story_owner(page_url: str, owner: str | None) -> bool:
    if not owner:
        return True
    current_owner = _story_owner(page_url)
    return current_owner is None or current_owner == owner


def _page_problem(page) -> str | None:
    try:
        text = page.locator("body").inner_text(timeout=2000).lower()
    except Exception:
        return None

    problems = {
        "story is no longer available": "هذه الستوري لم تعد متاحة على Facebook.",
        "this story is no longer available": "هذه الستوري لم تعد متاحة على Facebook.",
        "content isn't available": "محتوى الستوري غير متاح للحساب المستخدم.",
        "content is not available": "محتوى الستوري غير متاح للحساب المستخدم.",
        "هذه القصة لم تعد متوفرة": "هذه الستوري لم تعد متاحة على Facebook.",
        "هذا المحتوى غير متوفر": "محتوى الستوري غير متاح للحساب المستخدم.",
    }
    for marker, message in problems.items():
        if marker in text:
            return message
    return None


def _settle_page(page) -> None:
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15_000)
    except Exception:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=8_000)
    except Exception:
        pass
    page.wait_for_timeout(2500)
    try:
        page.evaluate(
            """
            () => {
              document.querySelectorAll('video').forEach((video) => {
                video.muted = true;
                video.play().catch(() => {});
              });
            }
            """
        )
    except Exception:
        pass
    page.wait_for_timeout(1500)


def _snapshot_to_item(snapshot: dict, order: int) -> dict:
    media_type = snapshot["type"]
    media_url = snapshot["url"]
    return {
        "type": media_type,
        "url": media_url,
        "source_url": snapshot["page_url"],
        "title": f"جزء الستوري {order}",
        "extension": _media_extension(
            media_url,
            media_type,
            snapshot.get("content_type", ""),
        ),
        "thumbnail": snapshot.get("thumbnail"),
        "http_headers": {
            "Referer": snapshot["page_url"],
        },
        "capture_source": snapshot.get("capture_source"),
    }


def _save_diagnostics(page, responses: deque[dict], note: str) -> str | None:
    try:
        root = Path(__file__).resolve().parents[1]
        folder = root / "data" / "diagnostics"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        screenshot = folder / f"facebook_story_{stamp}.png"
        report = folder / f"facebook_story_{stamp}.txt"
        page.screenshot(path=str(screenshot), full_page=False)
        recent = list(responses)[-30:]
        lines = [
            note,
            f"URL: {page.url}",
            f"Title: {page.title()}",
            f"Captured network candidates: {len(responses)}",
            "",
        ]
        lines.extend(
            f"{item.get('type')} | {item.get('source')} | "
            f"{item.get('content_length')} | {item.get('url')}"
            for item in recent
        )
        report.write_text("\n".join(lines), encoding="utf-8")
        return str(folder)
    except Exception:
        return None


def launch_story_browser(playwright, headless: bool = True):
    """Launch bundled Chromium, then installed Edge or Chrome."""
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

    raise BrowserStoryError(
        "تعذر فتح Chromium أو Microsoft Edge أو Google Chrome. "
        "شغّل repair_browser.bat ثم أعد المحاولة. "
        f"التفاصيل: {' | '.join(errors)}"
    )


def _extract_once(url: str, *, headless: bool) -> dict:
    from playwright.sync_api import sync_playwright

    max_items = max(2, min(int(os.getenv("STORY_MAX_ITEMS", "50")), 100))
    responses: deque[dict] = deque(maxlen=600)
    seen_urls: set[str] = set()
    browser_name = "unknown"
    diagnostic_folder: str | None = None
    owner = _story_owner(url)

    with sync_playwright() as playwright:
        browser, browser_name = launch_story_browser(playwright, headless=headless)
        context_kwargs: dict = {
            "locale": "en-US",
            "viewport": {"width": 1440, "height": 1000},
            "ignore_https_errors": True,
        }
        storage_state = find_storage_state()
        if storage_state:
            context_kwargs["storage_state"] = str(storage_state)

        context = browser.new_context(**context_kwargs)
        if not storage_state:
            cookies = playwright_cookies()
            if cookies:
                context.add_cookies(cookies)

        page = context.new_page()

        def on_response(response) -> None:
            try:
                content_type = response.headers.get("content-type", "").lower()
                content_length = int(response.headers.get("content-length") or 0)
                media_type = None
                if content_type.startswith("video/"):
                    media_type = "video"
                elif content_type.startswith("image/"):
                    media_type = "image"
                elif re.search(r"\.(mp4|webm)(?:\?|$)", response.url, re.I):
                    media_type = "video"

                if media_type:
                    priority = 5 if media_type == "video" else 1
                    _append_response(
                        responses,
                        media_type,
                        response.url,
                        content_type=content_type,
                        content_length=content_length,
                        priority=priority,
                        source="network-response",
                    )

                if (
                    "graphql" in response.url.lower()
                    and any(
                        marker in content_type
                        for marker in ("json", "javascript", "text/plain")
                    )
                ):
                    try:
                        _extract_graphql_media(response.text(), responses)
                    except Exception:
                        pass
            except Exception:
                return

        page.on("response", on_response)

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            _settle_page(page)

            if "/login" in page.url.lower():
                raise BrowserStoryError(
                    "Facebook طلب تسجيل الدخول. شغّل login_facebook.bat ثم أعد التحليل."
                )

            problem = _page_problem(page)
            if problem:
                raise BrowserStoryError(problem)

            start_fingerprint, start_snapshot = _wait_for_snapshot(
                page,
                responses,
                seen_urls,
                timeout_seconds=12.0,
            )
            if start_snapshot:
                seen_urls.add(start_snapshot["url"])

            previous_snapshots: list[dict] = []
            current_fingerprint = start_fingerprint
            for _ in range(max_items):
                if not _click_direction(page, "previous"):
                    break
                changed, fingerprint, snapshot = _wait_for_change(
                    page,
                    current_fingerprint,
                    responses,
                    seen_urls,
                )
                if not changed or not snapshot or not _same_story_owner(page.url, owner):
                    break
                current_fingerprint = fingerprint
                media_url = snapshot["url"]
                if media_url in seen_urls:
                    break
                seen_urls.add(media_url)
                previous_snapshots.append(snapshot)

            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            _settle_page(page)
            current_fingerprint, current_snapshot = _wait_for_snapshot(
                page,
                responses,
                set(),
                timeout_seconds=10.0,
            )
            if not start_snapshot and current_snapshot:
                start_snapshot = current_snapshot
                seen_urls.add(current_snapshot["url"])

            next_snapshots: list[dict] = []
            for _ in range(max_items):
                if not _click_direction(page, "next"):
                    break
                changed, fingerprint, snapshot = _wait_for_change(
                    page,
                    current_fingerprint,
                    responses,
                    seen_urls,
                )
                if not changed or not snapshot or not _same_story_owner(page.url, owner):
                    break
                current_fingerprint = fingerprint
                media_url = snapshot["url"]
                if media_url in seen_urls:
                    break
                seen_urls.add(media_url)
                next_snapshots.append(snapshot)

            ordered: list[dict] = []
            ordered_urls: set[str] = set()
            for snapshot in reversed(previous_snapshots):
                if snapshot["url"] not in ordered_urls:
                    ordered.append(snapshot)
                    ordered_urls.add(snapshot["url"])
            if start_snapshot and start_snapshot["url"] not in ordered_urls:
                ordered.append(start_snapshot)
                ordered_urls.add(start_snapshot["url"])
            for snapshot in next_snapshots:
                if snapshot["url"] not in ordered_urls:
                    ordered.append(snapshot)
                    ordered_urls.add(snapshot["url"])

            if not ordered:
                network_candidates = sorted(
                    [
                        item
                        for item in responses
                        if item.get("type") == "video"
                        or float(item.get("priority") or 0) >= 6
                    ],
                    key=_network_score,
                    reverse=True,
                )
                for candidate in network_candidates[:max_items]:
                    media_url = candidate["url"]
                    if media_url in ordered_urls:
                        continue
                    ordered.append(
                        {
                            "type": candidate["type"],
                            "url": media_url,
                            "thumbnail": media_url
                            if candidate["type"] == "image"
                            else None,
                            "content_type": candidate.get("content_type", ""),
                            "page_url": page.url,
                            "capture_source": candidate.get("source"),
                        }
                    )
                    ordered_urls.add(media_url)

            title = page.title() or "قصة فيسبوك"
            if not ordered:
                diagnostic_folder = _save_diagnostics(
                    page,
                    responses,
                    "No story media could be captured.",
                )

            context.close()
            browser.close()
        except Exception:
            try:
                diagnostic_folder = diagnostic_folder or _save_diagnostics(
                    page,
                    responses,
                    "Story extraction failed.",
                )
            except Exception:
                pass
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass
            raise

    if not ordered:
        details = (
            f" تم حفظ ملف تشخيص داخل: {diagnostic_folder}."
            if diagnostic_folder
            else ""
        )
        raise BrowserStoryError(
            "تم فتح الستوري، لكن Facebook لم يوفّر رابط الوسائط بالطريقة المتوقعة."
            f"{details}"
        )

    return {
        "title": title,
        "method": (
            f"playwright-story-sequence:{browser_name}:"
            f"{'headless' if headless else 'visible'}"
        ),
        "items": [
            _snapshot_to_item(snapshot, index)
            for index, snapshot in enumerate(ordered, start=1)
        ],
        "sequence_url": sequence_url(url),
    }


def extract_story_sequence(url: str) -> dict:
    """Open the Facebook viewer and enumerate all discoverable story cards."""
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError as exc:
        raise BrowserStoryError(
            "مكتبة Playwright غير مثبتة. شغّل repair_browser.bat ثم أعد المحاولة."
        ) from exc

    headless = os.getenv("STORY_BROWSER_HEADLESS", "1") != "0"
    attempts = [headless]
    if headless and os.getenv("STORY_VISIBLE_RETRY", "1") != "0":
        attempts.append(False)

    errors: list[str] = []
    for attempt_headless in attempts:
        try:
            return _extract_once(url, headless=attempt_headless)
        except BrowserStoryError as exc:
            errors.append(str(exc))
        except Exception as exc:
            mode = "الخفي" if attempt_headless else "المرئي"
            errors.append(f"فشل المتصفح {mode}: {_compact_error(exc)}")

    unique_errors = list(dict.fromkeys(errors))
    raise BrowserStoryError(" | ".join(unique_errors))
