"""
XEON V2 - Browser Tools
Web search via DuckDuckGo Lite, page visits via Playwright, URL opening.
"""

import re
import webbrowser
import subprocess
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus, unquote, parse_qs, urlparse
import httpx
from playwright.async_api import async_playwright

_browser = None
_context = None


def _bring_chromium_to_front():
    """Bring the Playwright Chromium window to the foreground on Windows."""
    try:
        subprocess.run([
            "powershell", "-Command",
            '(Get-Process -Name "chromium","chrome" -ErrorAction SilentlyContinue | '
            'Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -Last 1).MainWindowHandle | '
            'ForEach-Object { Add-Type "using System; using System.Runtime.InteropServices; '
            'public class W { [DllImport(\\\"user32.dll\\\")] public static extern bool SetForegroundWindow(IntPtr h); }"; '
            '[W]::SetForegroundWindow($_) }'
        ], capture_output=True, timeout=3)
    except Exception:
        pass


async def _get_browser():
    global _browser, _context
    if _browser is None:
        pw = await async_playwright().start()
        _browser = await pw.chromium.launch(headless=False, args=["--start-maximized"])
        _context = await _browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            no_viewport=True,
        )
    return _context


async def search_and_read(query: str) -> dict:
    """Search DuckDuckGo in visible browser, click first result, read the page."""
    ctx = await _get_browser()
    page = await ctx.new_page()
    try:
        # DuckDuckGo search (no cookie banner, no reCAPTCHA)
        search_url = f"https://duckduckgo.com/?q={query}"
        await page.goto(search_url, timeout=15000)
        _bring_chromium_to_front()
        await page.wait_for_timeout(2000)

        # Click first organic result
        first_link = page.locator('[data-testid="result-title-a"]').first
        if await first_link.count() > 0:
            await first_link.click()
            await page.wait_for_timeout(3000)

            # Read page content
            title = await page.title()
            url = page.url
            text = await page.evaluate("""
                () => {
                    const selectors = ['main', 'article', '[role="main"]', '.content', '#content', 'body'];
                    for (const sel of selectors) {
                        const el = document.querySelector(sel);
                        if (el && el.innerText.trim().length > 100) {
                            return el.innerText.trim();
                        }
                    }
                    return document.body?.innerText?.trim() || '';
                }
            """)
            return {"title": title, "url": url, "content": text[:3000]}
        else:
            return {"title": "Keine Ergebnisse", "url": search_url, "content": "Keine Ergebnisse gefunden."}
    except Exception as e:
        return {"error": str(e), "url": query}
    finally:
        pass


async def visit(url: str, max_chars: int = 5000) -> dict:
    """Visit a URL and extract main text content."""
    ctx = await _get_browser()
    page = await ctx.new_page()
    try:
        await page.goto(url, timeout=15000, wait_until="domcontentloaded")
        text = await page.evaluate("""
            () => {
                const selectors = ['main', 'article', '[role="main"]', '.content', '#content', 'body'];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el && el.innerText.trim().length > 100) {
                        return el.innerText.trim();
                    }
                }
                return document.body?.innerText?.trim() || '';
            }
        """)
        title = await page.title()
        return {"title": title, "url": url, "content": text[:max_chars]}
    except Exception as e:
        return {"error": str(e), "url": url}
    finally:
        await page.close()


async def fetch_news() -> str:
    """Open World Monitor visually and fetch current news from reliable RSS feeds."""
    ctx = await _get_browser()
    page = await ctx.new_page()
    feeds = {
        "Internationaler Handel": "https://news.google.com/rss/search?q=international%20trade%20OR%20global%20trade%20OR%20tariffs%20OR%20supply%20chain&hl=de&gl=DE&ceid=DE:de",
        "Weltpolitik": "https://news.google.com/rss/search?q=world%20politics%20geopolitics&hl=de&gl=DE&ceid=DE:de",
        "Energie und Rohstoffe": "https://news.google.com/rss/search?q=energy%20oil%20gas%20commodities%20shipping&hl=de&gl=DE&ceid=DE:de",
    }
    try:
        await page.goto("https://www.worldmonitor.app/", timeout=20000)
        _bring_chromium_to_front()
        await page.wait_for_timeout(4000)
        try:
            await page.mouse.wheel(0, -900)
            await page.keyboard.press("+")
            await page.keyboard.press("+")
        except Exception:
            pass

        sections = []
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            for section, url in feeds.items():
                response = await client.get(url)
                response.raise_for_status()
                root = ET.fromstring(response.content)
                items = []
                for item in root.findall(".//item")[:5]:
                    title = (item.findtext("title") or "").strip()
                    source = item.findtext("source") or ""
                    published = item.findtext("pubDate") or ""
                    if title:
                        items.append(f"- {title} ({source}, {published})")
                if items:
                    sections.append(f"{section}:\n" + "\n".join(items))

        if not sections:
            return "Keine aktuellen Nachrichtenfeeds konnten geladen werden."
        return "Aktuelle Nachrichten mit Fokus auf Handel, Lieferketten und Geopolitik:\n\n" + "\n\n".join(sections)
    except Exception as e:
        return f"News konnten nicht geladen werden: {e}"
    finally:
        pass  # Keep page open so user can see it


async def open_url(url: str):
    """Open URL in user's default browser (non-blocking)."""
    import asyncio
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, webbrowser.open, url)
    return {"success": True, "url": url}


async def close():
    global _browser, _context
    if _browser:
        await _browser.close()
        _browser = None
        _context = None
