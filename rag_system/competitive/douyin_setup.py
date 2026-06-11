"""One-time Douyin login setup — auto-detects when login is complete.

Run: cd MediaCrawler && uv run python ../rag_system/competitive/douyin_setup.py

A Chrome window opens. Log in to Douyin (QR scan). Once logged in,
the script auto-detects success, saves cookies, and closes the browser.
"""

import asyncio, json, sys, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "MediaCrawler"))
os.chdir(str(Path(__file__).parent.parent.parent / "MediaCrawler"))

from playwright.async_api import async_playwright
from tools.cdp_browser import CDPBrowserManager

COOKIE_FILE = Path("../output/competitive/douyin_cookies.json").resolve()
AUTH_STATE = Path("../output/competitive/douyin_auth.json").resolve()


async def wait_for_login(page, timeout_sec: int = 180) -> bool:
    """Poll until login page disappears and we reach the Douyin feed."""
    for i in range(timeout_sec // 3):
        await asyncio.sleep(3)
        try:
            title = await page.title()
            url = page.url
            # Login complete when we're on the main feed, not login/verify page
            if "验证码" not in title and "登录" not in title and "login" not in url.lower():
                print(f"[{i*3}s] 登录成功！标题: {title}")
                return True
        except Exception:
            pass
    return False


async def setup():
    print("=" * 50)
    print("  抖音登录初始化")
    print("=" * 50)
    print("\nChrome浏览器已打开 → 请扫码登录抖音")
    print("登录成功后浏览器自动关闭，cookies自动保存。")
    print(f"等待超时: 3分钟\n")

    async with async_playwright() as pw:
        mgr = CDPBrowserManager()
        ctx = await mgr.launch_and_connect(
            playwright=pw, playwright_proxy=None,
            user_agent=None, headless=False,
        )

        try:
            pages = ctx.pages
            page = pages[0] if pages else await ctx.new_page()
            await page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=30000)
            title = await page.title()
            print(f"当前页面: {title}")

            if "验证码" in title:
                print("⚠ 页面需要验证码，请在浏览器中完成")

            # Auto-wait for login
            ok = await wait_for_login(page, timeout_sec=180)
            if not ok:
                print("⚠ 超时 — 可能未完成登录。继续尝试保存...")

            # Save cookies
            cookies = await ctx.cookies()
            COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
            COOKIE_FILE.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")
            AUTH_STATE.write_text(json.dumps({"setup_done": True}))

            print(f"\nCookies -> {COOKIE_FILE}")
            print("抖音管线已就绪。")

        finally:
            await mgr.cleanup()


asyncio.run(setup())
