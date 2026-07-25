from __future__ import annotations


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
        from extractor.browser_story import launch_story_browser
    except Exception as exc:
        print(f"Browser check failed during import: {exc}")
        return 1

    try:
        with sync_playwright() as playwright:
            browser, label = launch_story_browser(playwright, headless=True)
            page = browser.new_page()
            page.set_content("<title>Story Downloader Browser Check</title>")
            print(f"Browser check passed: {label}")
            browser.close()
        return 0
    except Exception as exc:
        print(f"Browser check failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
