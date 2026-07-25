from __future__ import annotations

import sys
from pathlib import Path

from extractor.browser_story import launch_story_browser

BASE_DIR = Path(__file__).resolve().parent
AUTH_DIR = BASE_DIR / ".auth"
STATE_FILE = AUTH_DIR / "facebook_state.json"


def facebook_storage_state() -> Path | None:
    return STATE_FILE if STATE_FILE.is_file() else None


def save_facebook_session() -> Path:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is not installed. Run repair_browser.bat first."
        ) from exc

    AUTH_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser, browser_name = launch_story_browser(playwright, headless=False)
        context = browser.new_context(locale="en-US")
        page = context.new_page()
        page.goto("https://www.facebook.com/login", wait_until="domcontentloaded", timeout=60_000)

        print()
        print("A Facebook window has opened.")
        print("1. Sign in to Facebook in that window.")
        print("2. Wait until your Facebook home page appears.")
        print("3. Return to this black window and press Enter.")
        print()
        input("Press Enter after login is complete...")

        current_url = page.url.lower()
        if "/login" in current_url or "checkpoint" in current_url:
            context.close()
            browser.close()
            raise RuntimeError(
                "Facebook still appears to be on the login or checkpoint page. "
                "Complete login and any verification, then run this file again."
            )

        context.storage_state(path=str(STATE_FILE))
        context.close()
        browser.close()

    return STATE_FILE


def main() -> int:
    try:
        saved = save_facebook_session()
    except Exception as exc:
        print()
        print(f"Facebook session was not saved: {exc}")
        return 1

    print()
    print(f"Facebook session saved successfully using: {saved}")
    print("You can now run start.bat and analyze the story again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
