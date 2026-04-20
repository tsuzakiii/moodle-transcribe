"""Moodle page → m3u8 URL + lecture title.

Uses curl_cffi (TLS impersonation) for cookie validation, Playwright for
JS-rendered pages where the m3u8 URL is fetched dynamically.
"""
from __future__ import annotations

import asyncio
import re
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import Callable

Logger = Callable[[str], None]


def _load_cookiejar(cookies_file: Path) -> MozillaCookieJar:
    """Wrap MozillaCookieJar.load with a clearer error for malformed files."""
    cj = MozillaCookieJar()
    try:
        cj.load(str(cookies_file), ignore_discard=True, ignore_expires=True)
    except Exception as e:
        raise RuntimeError(
            f"クッキーファイルの読み込みに失敗 ({cookies_file}): {e}\n"
            "  → 'Get cookies.txt LOCALLY' で再エクスポートしてください"
        ) from e
    return cj


def check_cookies_valid(cookies_file: Path, login_check_url: str, log: Logger) -> bool:
    """Hit the login-check URL with cookies; 200 = valid."""
    from curl_cffi import requests as cr

    if not cookies_file.exists():
        log(f"  ❌ クッキーファイルなし: {cookies_file}")
        return False
    try:
        cj = _load_cookiejar(cookies_file)
    except RuntimeError as e:
        log(f"  ❌ {e}")
        return False
    cookies = {c.name: c.value for c in cj}
    try:
        r = cr.get(login_check_url, cookies=cookies, impersonate="chrome",
                   allow_redirects=False, timeout=15)
    except Exception as e:
        log(f"  ❌ 通信失敗: {e}")
        return False
    if r.status_code == 200:
        return True
    loc = r.headers.get("Location", "")
    log(f"  ❌ クッキー期限切れ (status={r.status_code}, redirect→{loc[:80]})")
    log("     → ブラウザ拡張で再エクスポートして上書きしてください")
    return False


def resolve_video(moodle_url: str, cookies_file: Path, log: Logger,
                  headless: bool = True) -> tuple[str, str]:
    """Open the Moodle page in headless Chromium, return (m3u8_url, page_title)."""
    from playwright.async_api import async_playwright

    if not cookies_file.exists():
        raise RuntimeError(
            f"クッキーファイルがありません: {cookies_file}\n"
            "Chrome拡張 'Get cookies.txt LOCALLY' でMoodleドメインを書き出してください"
        )

    async def _run() -> tuple[str, list[str]]:
        cj = _load_cookiejar(cookies_file)
        cookies = [{
            "name": c.name, "value": c.value, "domain": c.domain, "path": c.path,
            "secure": bool(c.secure), "httpOnly": False,
            "expires": c.expires if c.expires else -1,
        } for c in cj]
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            ctx = await browser.new_context()
            await ctx.add_cookies(cookies)
            page = await ctx.new_page()
            urls: list[str] = []
            page.on("request", lambda req: urls.append(req.url) if "m3u8" in req.url else None)
            await page.goto(moodle_url, wait_until="networkidle", timeout=30000)
            title = await page.title()
            await asyncio.sleep(3)
            await browser.close()
            return title, urls

    log("  Moodleページを読み込み中 (Playwright)…")
    title, urls = asyncio.run(_run())
    masters = [u for u in urls if "/index.m3u8" in u]
    if not masters:
        raise RuntimeError(f"m3u8が見つかりません。取得URL: {urls}")
    log(f"  ページタイトル: {title}")
    log("  m3u8 取得OK")
    return masters[0], title


def clean_page_title(title: str) -> str:
    """Strip common Moodle suffixes like ' | Waseda Moodle'."""
    return re.sub(r"\s*[|｜]\s*[A-Za-z0-9 ]*Moodle\s*$", "", title).strip()
