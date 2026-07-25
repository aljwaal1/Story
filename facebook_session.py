from __future__ import annotations

from pathlib import Path

from extractor.browser_story import launch_story_browser

BASE_DIR = Path(__file__).resolve().parent
AUTH_DIR = BASE_DIR / ".auth"
STATE_FILE = AUTH_DIR / "facebook_state.json"
COOKIES_FILE = BASE_DIR / "cookies.txt"


def _write_netscape_cookies(cookies: list[dict], path: Path) -> None:
    lines = [
        "# Netscape HTTP Cookie File",
        "# Generated locally by Story Downloader Pro. Do not share this file.",
        "",
    ]
    for cookie in cookies:
        domain = str(cookie.get("domain") or "")
        if not domain:
            continue
        http_only = bool(cookie.get("httpOnly"))
        output_domain = f"#HttpOnly_{domain}" if http_only else domain
        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        cookie_path = str(cookie.get("path") or "/")
        secure = "TRUE" if cookie.get("secure") else "FALSE"
        expires = cookie.get("expires")
        try:
            expires_value = max(0, int(float(expires or 0)))
        except (TypeError, ValueError):
            expires_value = 0
        name = str(cookie.get("name") or "")
        value = str(cookie.get("value") or "")
        if not name:
            continue
        lines.append(
            "\t".join(
                [
                    output_domain,
                    include_subdomains,
                    cookie_path,
                    secure,
                    str(expires_value),
                    name,
                    value,
                ]
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def save_facebook_session() -> tuple[Path, Path]:
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
        page.goto(
            "https://www.facebook.com/login",
            wait_until="domcontentloaded",
            timeout=60_000,
        )

        print()
        print(f"Facebook opened using {browser_name}.")
        print("1. Sign in to Facebook in the opened browser window.")
        print("2. Complete any code or security verification.")
        print("3. Wait until the Facebook home page appears.")
        print("4. Return to this black window and press Enter.")
        print()
        input("Press Enter after login is complete...")

        page.goto(
            "https://www.facebook.com/",
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        page.wait_for_timeout(1500)

        cookies = context.cookies(["https://www.facebook.com/"])
        logged_in = any(
            cookie.get("name") == "c_user" and cookie.get("value")
            for cookie in cookies
        )
        if not logged_in:
            context.close()
            browser.close()
            raise RuntimeError(
                "Facebook login was not detected. Complete login and verification "
                "in the browser, then run login_facebook.bat again."
            )

        context.storage_state(path=str(STATE_FILE))
        _write_netscape_cookies(cookies, COOKIES_FILE)
        context.close()
        browser.close()

    return STATE_FILE, COOKIES_FILE


def main() -> int:
    try:
        state_file, cookies_file = save_facebook_session()
    except Exception as exc:
        print()
        print(f"Facebook session was not saved: {exc}")
        return 1

    print()
    print("Facebook session saved successfully.")
    print(f"State file: {state_file}")
    print(f"Cookies file: {cookies_file}")
    print("You can now run start.bat and analyze the story again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
