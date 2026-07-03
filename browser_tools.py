"""
XEON V2 - Browser Tools
Web search via DuckDuckGo Lite, page visits via Playwright, URL opening.
"""

import re
import asyncio
import json
import webbrowser
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote_plus, unquote, parse_qs, urlparse, urlencode
import httpx
from playwright.async_api import async_playwright

_browser = None
_context = None
_playwright = None
_world_monitor_page = None
PROFILE_DIR = Path(__file__).parent / "data" / "browser-profile"
NEWS_HISTORY_PATH = Path(__file__).parent / "data" / "news_history.json"

WORLD_MONITOR_LAYERS = (
    "conflicts,bases,hotspots,nuclear,sanctions,weather,economic,waterways,"
    "outages,military,natural,iranAttacks"
)

COUNTRY_FOCUS = {
    "germany": {"name": "Deutschland", "search": "Germany", "search_terms": ["Germany", "Deutschland", "Berlin"], "lat": 51.2, "lon": 10.4, "iso": "DE", "zoom": 4.1},
    "turkey": {"name": "Tuerkei", "search": "Turkey", "search_terms": ["Turkey", "Ankara", "Istanbul Turkey"], "lat": 39.0, "lon": 35.2, "iso": "TR", "zoom": 4.2},
    "china": {"name": "China", "search": "China", "search_terms": ["China", "Beijing", "Shanghai China"], "lat": 35.9, "lon": 104.2, "iso": "CN", "zoom": 3.2},
    "usa": {"name": "USA", "search": "USA", "search_terms": ["USA", "United States", "Washington United States"], "lat": 39.8, "lon": -98.6, "iso": "US", "zoom": 3.5},
    "russia": {"name": "Russland", "search": "Russia", "search_terms": ["Russia", "Moscow", "Moskau"], "lat": 61.5, "lon": 105.3, "iso": "RU", "zoom": 2.6},
    "ukraine": {"name": "Ukraine", "search": "Ukraine", "search_terms": ["Ukraine", "Kyiv", "Kiew"], "lat": 49.0, "lon": 31.4, "iso": "UA", "zoom": 4.8},
    "israel": {"name": "Israel", "search": "Israel", "search_terms": ["Israel", "Jerusalem", "Tel Aviv"], "lat": 31.0, "lon": 34.8, "iso": "IL", "zoom": 6.0},
    "iran": {"name": "Tehran", "search": "Tehran", "search_terms": ["Tehran", "Iran", "Teheran"], "lat": 32.4, "lon": 53.7, "iso": "IR", "zoom": 4.3},
    "india": {"name": "Indien", "search": "India", "search_terms": ["India", "New Delhi", "Mumbai India"], "lat": 20.6, "lon": 78.9, "iso": "IN", "zoom": 4.0},
    "brazil": {"name": "Brasilien", "search": "Brazil", "search_terms": ["Brazil", "Brasilia", "Sao Paulo Brazil"], "lat": -14.2, "lon": -51.9, "iso": "BR", "zoom": 3.7},
    "saudi-arabia": {"name": "Saudi-Arabien", "search": "Saudi Arabia", "search_terms": ["Saudi Arabia", "Riyadh", "Saudi"], "lat": 23.9, "lon": 45.1, "iso": "SA", "zoom": 4.5},
    "egypt": {"name": "Aegypten", "search": "Egypt", "search_terms": ["Egypt", "Cairo", "Kairo"], "lat": 26.8, "lon": 30.8, "iso": "EG", "zoom": 4.8},
    "france": {"name": "Frankreich", "search": "France", "search_terms": ["France", "Paris"], "lat": 46.2, "lon": 2.2, "iso": "FR", "zoom": 4.7},
    "united-kingdom": {"name": "Grossbritannien", "search": "United Kingdom", "search_terms": ["United Kingdom", "Britain", "London"], "lat": 55.4, "lon": -3.4, "iso": "GB", "zoom": 4.8},
}


def _is_bad_news_source_or_title(title: str, source: str) -> bool:
    normalized = f"{title} {source}".lower()
    source_norm = str(source or "").lower()
    blocked_sources = [
        "ad hoc news", "finanznachrichten", "wallstreet online", "gurufocus",
        "marketscreener", "simply wall st", "tradingview", "traders union",
        "coindesk", "cointelegraph", "beincrypto", "cryptonews",
        "pr newswire", "yahoo finanzen", "it-times",
    ]
    if any(source_name in source_norm for source_name in blocked_sources):
        return True
    hard_marketing_terms = [
        "pr newswire", "supply chain expo", "international supply chain expo",
        "healthy life chain", "smart vehicle chain", "announces vehicle delivery results",
        "from china to the world", "von china in die welt", "streamlined export service",
        "token china shock", "yesigiveafig", "cross-chain", "on-chain",
        "onegrowth", "global partner conference", "etfs in spotlight",
    ]
    if any(term in normalized for term in hard_marketing_terms):
        return True
    noise_terms = [
        "stock", "aktie", "aktien", "share price", "shares", "boerse",
        "kursziel", "dividend", "dividende", "trading stays", "stock holds",
        "crypto", "bitcoin", "solana", "ethereum", "token", "prediction market",
        "analyst", "startup funding", "job cuts",
        "etf", "etfs", "conference",
        "expo", "messe", "fair", "presented", "praesentiert", "präsentiert",
        "announces", "kuendigt an", "kündigt an", "delivery results",
        "entire spectrum", "gesamte spektrum", "bequemer gestalten",
    ]
    strong_terms = [
        "tariff", "customs", "supply chain", "shipping", "freight", "container",
        "port", "import", "export", "regulation", "zoll", "lieferkette",
        "seefracht", "hafen", "suez", "hormuz", "hormus", "red sea",
        "rotes meer", "turkey", "tuerkei", "china", "nearshoring",
    ]
    return any(term in normalized for term in noise_terms) and not any(term in normalized for term in strong_terms)


def _deep_news_score(section: str, title: str, source: str) -> int:
    normalized = f"{section} {title} {source}".lower()
    score = 0
    priority_terms = {
        "supply chain": 8, "lieferkette": 8, "shipping": 8, "freight": 8,
        "seefracht": 8, "container": 8, "containerpreise": 9, "drewry": 9,
        "xeneta": 9, "freightos": 9, "scfi": 9, "port": 7, "hafen": 7,
        "customs": 7, "tariff": 7, "zoll": 7, "import": 6, "export": 6,
        "regulation": 6, "gesetz": 6, "compliance": 6, "suez": 9,
        "hormuz": 9, "hormus": 9, "red sea": 9, "rotes meer": 9,
        "rerouting": 8, "umweg": 8, "congestion": 7, "stau": 7,
        "china": 6, "turkey": 7, "tuerkei": 7, "istanbul": 8,
        "nearshoring": 8, "manufacturing": 5, "factory": 5, "pmi": 5,
        "shortage": 6, "engpass": 6, "klimaanlagen": 6, "ventilatoren": 5,
        "matratzen": 5,
    }
    for term, value in priority_terms.items():
        if term in normalized:
            score += value
    penalty_terms = [
        "stock", "aktie", "aktien", "share price", "dividend", "kursziel",
        "crypto", "bitcoin", "solana", "token", "startup funding", "job cuts",
        "press release", "pr newswire", "bicycle fair", "vorhersagemarkt",
    ]
    for term in penalty_terms:
        if term in normalized:
            score -= 8
    if any(term in normalized for term in ["china", "suez", "hormuz", "hormus", "red sea", "container"]):
        score += 3
    return score


def _world_monitor_url(country: dict | None = None, global_view: bool = False) -> str:
    params = {
        "lat": 20 if global_view or not country else country["lat"],
        "lon": 20 if global_view or not country else country["lon"],
        "zoom": 1.7 if global_view or not country else country.get("zoom", 4.0),
        "view": "global",
        "timeRange": "7d",
        "layers": WORLD_MONITOR_LAYERS,
    }
    if country and country.get("iso"):
        params["country"] = country["iso"]
    return "https://www.worldmonitor.app/dashboard?" + urlencode(params)


async def _ensure_world_monitor_page():
    global _world_monitor_page
    ctx = await _get_browser()
    if _world_monitor_page is None or _world_monitor_page.is_closed():
        _world_monitor_page = await ctx.new_page()
        await _world_monitor_page.goto("https://www.worldmonitor.app/dashboard", timeout=20000, wait_until="domcontentloaded")
        await _world_monitor_page.wait_for_timeout(3500)
    elif "worldmonitor.app" not in _world_monitor_page.url:
        await _world_monitor_page.goto("https://www.worldmonitor.app/dashboard", timeout=20000, wait_until="domcontentloaded")
        await _world_monitor_page.wait_for_timeout(2500)
    return _world_monitor_page


async def _reset_world_monitor_in_place(page) -> None:
    clicked = await page.evaluate(
        """() => {
            const reset = document.querySelector('.zoom-reset, [aria-label*="Reset"], [title*="Reset"]');
            if (reset instanceof HTMLElement) {
                reset.click();
                return true;
            }
            const region = document.querySelector('#regionSelect');
            if (region instanceof HTMLSelectElement) {
                region.value = 'global';
                region.dispatchEvent(new Event('change', { bubbles: true }));
                return true;
            }
            return false;
        }"""
    )
    if clicked:
        await page.wait_for_timeout(550)
    await page.evaluate(
        """() => {
            const url = new URL(location.href);
            if (url.searchParams.has('country')) {
                url.searchParams.delete('country');
                history.replaceState({}, '', url.toString());
            }
        }"""
    )


async def _svg_country_screen_plan(page, country: dict) -> dict:
    return await page.evaluate(
        """(target) => {
            const container = document.querySelector('#mapContainer, .map-container, #mapSection');
            const svg = document.querySelector('#mapSvg');
            const wrapper = document.querySelector('#mapWrapper');
            if (!container || !svg || !wrapper) {
                return { ok: false, reason: 'svg_map_unavailable' };
            }
            const rect = container.getBoundingClientRect();
            const width = container.clientWidth || rect.width;
            const height = container.clientHeight || rect.height;
            if (!width || !height) return { ok: false, reason: 'map_has_no_size' };
            const transform = getComputedStyle(wrapper).transform;
            const matrix = transform && transform !== 'none'
                ? new DOMMatrixReadOnly(transform)
                : new DOMMatrixReadOnly();
            const zoom = matrix.a || 1;
            const tx = matrix.e || 0;
            const ty = matrix.f || 0;

            const latNorth = 72;
            const latSouth = -56;
            const latCenter = (latNorth + latSouth) / 2;
            const latRange = latNorth - latSouth;
            const scaleForWidth = width / (2 * Math.PI);
            const scaleForHeight = height / (latRange * Math.PI / 180);
            const scale = Math.min(scaleForWidth, scaleForHeight);
            const x = width / 2 + scale * (Number(target.lon) * Math.PI / 180);
            const y = height / 2 - scale * ((Number(target.lat) - latCenter) * Math.PI / 180);
            const centerX = rect.left + width / 2;
            const centerY = rect.top + height / 2;
            const targetX = rect.left + x * zoom + tx;
            const targetY = rect.top + y * zoom + ty;
            return {
                ok: true,
                targetX,
                targetY,
                centerX,
                centerY,
                dx: centerX - targetX,
                dy: centerY - targetY,
                zoom,
                rect: { left: rect.left, top: rect.top, width, height },
                url: location.href,
            };
        }""",
        {"lat": country["lat"], "lon": country["lon"]},
    )


async def _drag_country_to_center(page, country: dict, max_passes: int = 7) -> bool:
    for _ in range(max_passes):
        plan = await _svg_country_screen_plan(page, country)
        if not plan.get("ok"):
            return False
        dx = float(plan.get("dx") or 0)
        dy = float(plan.get("dy") or 0)
        if abs(dx) < 16 and abs(dy) < 16:
            return True
        rect = plan.get("rect") or {}
        width = max(320.0, float(rect.get("width") or 900))
        height = max(240.0, float(rect.get("height") or 650))
        max_step_x = max(120.0, min(520.0, width * 0.38))
        max_step_y = max(100.0, min(360.0, height * 0.38))
        step_x = max(-max_step_x, min(max_step_x, dx))
        step_y = max(-max_step_y, min(max_step_y, dy))
        start_x = float(plan["centerX"])
        start_y = float(plan["centerY"])
        await page.mouse.move(start_x, start_y)
        await page.mouse.down()
        await page.mouse.move(start_x + step_x, start_y + step_y, steps=18)
        await page.mouse.up()
        await page.wait_for_timeout(180)
    plan = await _svg_country_screen_plan(page, country)
    return bool(plan.get("ok")) and abs(float(plan.get("dx") or 0)) < 28 and abs(float(plan.get("dy") or 0)) < 28


async def _focus_svg_world_monitor_country(page, country: dict) -> bool:
    await page.wait_for_selector("#mapContainer, .map-container", timeout=12000)
    await page.wait_for_selector("#mapSvg", timeout=12000)
    await _reset_world_monitor_in_place(page)
    await page.wait_for_timeout(650)
    plan = await _svg_country_screen_plan(page, country)
    if not plan.get("ok"):
        return False
    clicked = await _click_country_focus_point(page, country, plan)
    if clicked:
        return True
    await _reset_world_monitor_in_place(page)
    await page.wait_for_timeout(650)
    plan = await _svg_country_screen_plan(page, country)
    return bool(plan.get("ok")) and await _click_country_focus_point(page, country, plan)


async def _click_country_focus_point(page, country: dict, plan: dict) -> bool:
    iso = str(country.get("iso", "")).upper()
    base_x = float(plan.get("targetX") or plan.get("centerX"))
    base_y = float(plan.get("targetY") or plan.get("centerY"))
    offsets = [
        (0, 0), (26, 0), (-26, 0), (0, 26), (0, -26),
        (42, 22), (-42, 22), (42, -22), (-42, -22),
        (64, 0), (-64, 0), (0, 48), (0, -48),
    ]
    for offset_x, offset_y in offsets:
        await page.mouse.move(base_x + offset_x, base_y + offset_y, steps=6)
        await page.wait_for_timeout(180)
        await page.mouse.click(base_x + offset_x, base_y + offset_y)
        await page.wait_for_timeout(650)
        selected = await page.evaluate("() => new URL(location.href).searchParams.get('country') || ''")
        if selected.upper() == iso:
            return True
    return False


async def _world_monitor_state_matches_country(page, country: dict) -> bool:
    state = await page.evaluate(
        """() => {
            const params = new URL(location.href).searchParams;
            return {
                country: (params.get('country') || '').toUpperCase(),
                lat: Number.parseFloat(params.get('lat') || ''),
                lon: Number.parseFloat(params.get('lon') || ''),
                zoom: Number.parseFloat(params.get('zoom') || ''),
            };
        }"""
    )
    if str(state.get("country") or "").upper() == str(country.get("iso", "")).upper():
        return True
    lat = state.get("lat")
    lon = state.get("lon")
    zoom = state.get("zoom")
    if not all(isinstance(value, (int, float)) for value in [lat, lon, zoom]):
        return False
    return (
        abs(float(lat) - float(country["lat"])) <= 6.0
        and abs(float(lon) - float(country["lon"])) <= 9.0
        and float(zoom) >= min(3.0, float(country.get("zoom", 3.0)) - 0.5)
    )


async def _clear_stale_world_monitor_country_param(page, country: dict) -> None:
    await page.evaluate(
        """(iso) => {
            const url = new URL(location.href);
            const selected = (url.searchParams.get('country') || '').toUpperCase();
            if (selected && selected !== String(iso || '').toUpperCase()) {
                url.searchParams.delete('country');
                history.replaceState({}, '', url.toString());
            }
        }""",
        country.get("iso", ""),
    )


def _world_monitor_command_matches_country(command_text: str, country: dict) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", command_text.lower()).strip()
    if "karte" not in normalized and "map" not in normalized:
        return False
    names = [
        country.get("name", ""),
        country.get("search", ""),
        country.get("iso", ""),
        *(country.get("search_terms") or []),
    ]
    for name in names:
        name_norm = re.sub(r"[^a-z0-9]+", " ", str(name).lower()).strip()
        if name_norm and name_norm in normalized:
            return True
    return False


async def _focus_world_monitor_country_by_search(page, country: dict) -> bool:
    try:
        command_text = ""
        terms = []
        for value in list(country.get("search_terms") or []) + [country.get("search"), country.get("name"), country.get("iso")]:
            value = str(value or "").strip()
            if value and value not in terms:
                terms.append(value)
        for term in terms[:4]:
            for attempt in range(1, 4):
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(140)
                await page.click("#searchBtn", timeout=5000)
                await page.wait_for_timeout(250)
                search_input = page.locator(".search-overlay .search-input").first
                await search_input.wait_for(state="visible", timeout=5000)
                await search_input.fill("")
                await search_input.type(term)
                await page.wait_for_timeout(750)
                command = page.locator(".search-overlay .search-result-item.command-item").first
                if await command.count() == 0:
                    await page.keyboard.press("Escape")
                    break
                try:
                    command_text = (await command.inner_text(timeout=1200)).replace("\n", " | ")[:160]
                except Exception:
                    command_text = ""
                await command.click(timeout=5000)
                await page.wait_for_timeout(1700)
                focused = await _world_monitor_state_matches_country(page, country)
                state_debug = await page.evaluate(
                    """() => {
                        const p = new URL(location.href).searchParams;
                        return `${p.get('lat') || ''},${p.get('lon') || ''},${p.get('zoom') || ''},${p.get('country') || ''}`;
                    }"""
                )
                if not focused and _world_monitor_command_matches_country(command_text, country):
                    try:
                        lat_s, lon_s, zoom_s, _ = (state_debug.split(",") + ["", "", "", ""])[:4]
                        zoom_value = float(zoom_s)
                        lat_value = float(lat_s)
                        lon_value = float(lon_s)
                        moved_from_global = abs(lat_value - 20.0) > 1.0 or abs(lon_value) > 1.0
                        focused = zoom_value >= 2.5 and moved_from_global
                    except Exception:
                        focused = False
                print(f"[world-monitor] search focus {country.get('iso')} term='{term}' attempt={attempt} hit='{command_text}' state={state_debug} focused={focused}", flush=True)
                if focused:
                    await _clear_stale_world_monitor_country_param(page, country)
                    return True
        return False
    except Exception:
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        return False


async def _focus_world_monitor_country_by_url(page, country: dict) -> bool:
    return False


async def _maplibre_country_screen_plan(page, country: dict) -> dict:
    return await page.evaluate(
        """(target) => {
            const container = document.querySelector('#mapContainer, .map-container, #deckgl-basemap');
            const canvas = document.querySelector('.maplibregl-canvas');
            if (!container || !canvas) return { ok: false, reason: 'maplibre_unavailable' };
            const rect = container.getBoundingClientRect();
            const width = container.clientWidth || rect.width;
            const height = container.clientHeight || rect.height;
            if (!width || !height) return { ok: false, reason: 'map_has_no_size' };
            const params = new URL(location.href).searchParams;
            const centerLat = Number.parseFloat(params.get('lat') || '20');
            const centerLon = Number.parseFloat(params.get('lon') || '0');
            const zoom = Number.parseFloat(params.get('zoom') || '1');
            const z = Number.isFinite(zoom) ? zoom : 1;
            const scale = 512 * Math.pow(2, z);
            const clampLat = (lat) => Math.max(-85.05112878, Math.min(85.05112878, Number(lat)));
            const mercX = (lon) => (Number(lon) + 180) / 360;
            const mercY = (lat) => {
                const rad = clampLat(lat) * Math.PI / 180;
                return (1 - Math.log(Math.tan(Math.PI / 4 + rad / 2)) / Math.PI) / 2;
            };
            const targetX = rect.left + width / 2 + (mercX(target.lon) - mercX(centerLon)) * scale;
            const targetY = rect.top + height / 2 + (mercY(target.lat) - mercY(centerLat)) * scale;
            const centerX = rect.left + width / 2;
            const centerY = rect.top + height / 2;
            return {
                ok: true,
                targetX,
                targetY,
                centerX,
                centerY,
                dx: centerX - targetX,
                dy: centerY - targetY,
                zoom: z,
                centerLat,
                centerLon,
                rect: { left: rect.left, top: rect.top, width, height },
                url: location.href,
            };
        }""",
        {"lat": country["lat"], "lon": country["lon"]},
    )


async def _drag_maplibre_country_to_center(page, country: dict, max_passes: int = 8) -> bool:
    for _ in range(max_passes):
        plan = await _maplibre_country_screen_plan(page, country)
        if not plan.get("ok"):
            return False
        dx = float(plan.get("dx") or 0)
        dy = float(plan.get("dy") or 0)
        if abs(dx) < 18 and abs(dy) < 18:
            return True
        rect = plan.get("rect") or {}
        width = max(320.0, float(rect.get("width") or 900))
        height = max(240.0, float(rect.get("height") or 650))
        max_step_x = max(140.0, min(560.0, width * 0.38))
        max_step_y = max(110.0, min(380.0, height * 0.38))
        step_x = max(-max_step_x, min(max_step_x, dx))
        step_y = max(-max_step_y, min(max_step_y, dy))
        start_x = float(plan["centerX"])
        start_y = float(plan["centerY"])
        await page.mouse.move(start_x, start_y)
        await page.mouse.down()
        await page.mouse.move(start_x + step_x, start_y + step_y, steps=20)
        await page.mouse.up()
        await page.wait_for_timeout(520)
    plan = await _maplibre_country_screen_plan(page, country)
    return bool(plan.get("ok")) and abs(float(plan.get("dx") or 0)) < 35 and abs(float(plan.get("dy") or 0)) < 35


async def _focus_maplibre_world_monitor_country(page, country: dict) -> bool:
    await page.wait_for_selector("#mapContainer, .map-container", timeout=12000)
    await page.wait_for_selector(".maplibregl-canvas", timeout=12000)
    await _reset_world_monitor_in_place(page)
    await page.wait_for_timeout(650)
    plan = await _maplibre_country_screen_plan(page, country)
    if not plan.get("ok"):
        return False
    clicked = await _click_country_focus_point(page, country, plan)
    if clicked:
        return True
    await _reset_world_monitor_in_place(page)
    await page.wait_for_timeout(650)
    plan = await _maplibre_country_screen_plan(page, country)
    return bool(plan.get("ok")) and await _click_country_focus_point(page, country, plan)


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
    global _browser, _context, _playwright
    if _context is None:
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        _playwright = await async_playwright().start()
        _context = await _playwright.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=False,
            args=["--start-maximized"],
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            no_viewport=True,
        )
        _browser = _context
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


async def fetch_news(open_world_monitor: bool = False) -> str:
    """Deep-research current news from multiple fresh RSS searches."""
    cache_buster = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")

    def load_news_history() -> set[str]:
        try:
            data = json.loads(NEWS_HISTORY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return {str(item) for item in data[-500:]}
        except Exception:
            pass
        return set()

    def save_news_history(keys: list[str]) -> None:
        try:
            existing = list(load_news_history())
            merged = (existing + keys)[-500:]
            NEWS_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
            NEWS_HISTORY_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def make_title_key(value: str) -> str:
        key = re.sub(r"\s+\([^)]*\)\s*$", "", str(value or "").lower())
        key = re.sub(r"[^a-z0-9äöüß]+", " ", key).strip()
        return key[:190]

    def is_deep_news_noise(title: str, source: str) -> bool:
        normalized = f"{title} {source}".lower()
        noise_terms = [
            "stock", "aktie", "aktien", "share price", "shares", "börsen",
            "boerse", "kursziel", "dividend", "dividende", "trading stays",
            "stock holds", "ad hoc news", "finanznachrichten", "wallstreet online",
            "gurufocus", "marketscreener", "simply wall st",
        ]
        strong_terms = [
            "trade", "tariff", "customs", "supply chain", "shipping", "freight",
            "container", "port", "import", "export", "regulation", "zoll",
            "lieferkette", "seefracht", "hafen", "suez", "hormuz", "hormus",
            "red sea", "rotes meer", "turkey", "tuerkei", "china", "nearshoring",
        ]
        return any(term in normalized for term in noise_terms) and not any(term in normalized for term in strong_terms)

    def google_news(query: str, force_fresh: bool = True) -> str:
        fresh_query = f"({query}) when:7d" if force_fresh else query
        return (
            "https://news.google.com/rss/search?"
            + urlencode({"q": fresh_query, "hl": "de", "gl": "DE", "ceid": "DE:de", "_": cache_buster})
        )

    feeds = {
        "Deep Research: Welthandel": google_news("international trade OR global trade OR tariffs OR customs OR supply chain OR import OR export"),
        "Deep Research: Neue Gesetze und Regulierung": google_news("EU regulation OR new law OR customs law OR trade compliance OR import rules OR supply chain due diligence"),
        "EU Zoll und Import-Compliance": google_news("EU customs OR import regulation OR CBAM OR EUDR OR forced labour regulation"),
        "Deutschland Einkauf und Import": google_news("Germany import OR Germany procurement OR German retailers OR Germany sourcing OR logistics shortages"),
        "Tuerkei Industrie und Export": google_news("Turkey exports OR Turkey manufacturing OR Istanbul logistics OR Turkey Germany trade"),
        "Tuerkei Nearshoring und Produktion": google_news("Turkey nearshoring OR Turkey suppliers OR Turkey manufacturing Europe OR Istanbul Germany logistics"),
        "China Export und Fabrikdaten": google_news("China exports OR China manufacturing PMI OR China factory orders OR China supply chain"),
        "China-Lieferketten und Seefrachtpreise": google_news("China freight rates OR Shanghai Europe freight OR SCFI OR Drewry OR Freightos OR Xeneta"),
        "Containerpreise Reports": google_news("Drewry World Container Index Shanghai Europe freight rates Xeneta Freightos Baltic Index"),
        "Hafenstau und Transitzeiten": google_news("port congestion OR container transit times OR Shanghai port OR Ningbo port OR Rotterdam port OR Hamburg port"),
        "USA und China": google_news("USA China trade OR US China tariffs OR export controls OR China import restrictions"),
        "USA Handelspolitik": google_news("United States trade policy OR tariffs OR imports China OR EU trade"),
        "Suez Kanal und Aegypten": google_news("Suez Canal shipping OR Egypt Suez OR Europe Asia container vessels OR Suez disruption"),
        "Strasse von Hormus und Tehran": google_news("Tehran Strait of Hormuz OR Hormuz shipping OR oil gas shipping risk OR freight insurance"),
        "Rotes Meer und Frachtsicherheit": google_news("Red Sea shipping OR Red Sea attacks OR freight insurance OR container ships rerouting"),
        "Naher Osten und Handelsrouten": google_news("Middle East shipping OR trade routes OR Red Sea OR Suez OR Hormuz logistics"),
        "Saudi-Arabien und Energie": google_news("Saudi Arabia oil OR Saudi energy OR Red Sea trade OR shipping logistics"),
        "Russland Sanktionen und Energie": google_news("Russia sanctions OR Russia energy trade OR Europe gas OR shipping logistics"),
        "Ukraine Krieg und Lieferketten": google_news("Ukraine war OR grain logistics OR Ukraine energy trade OR Europe supply chain"),
        "Indien Beschaffung und Export": google_news("India manufacturing exports OR India suppliers OR India procurement OR India logistics"),
        "Niederlande und Rotterdam": google_news("Netherlands Rotterdam port OR Rotterdam container congestion OR Europe trade logistics"),
        "Grossbritannien Handel": google_news("United Kingdom trade OR UK customs OR UK imports OR suppliers logistics"),
        "Frankreich Industrie und Import": google_news("France industry OR France imports OR procurement OR trade logistics"),
        "Italien Industrie und Haefen": google_news("Italy manufacturing OR Italy imports exports OR Trieste port OR Genoa port logistics"),
        "Polen Logistik und Produktion": google_news("Poland manufacturing OR Poland logistics OR Germany supply chain OR nearshoring"),
        "Vietnam als China Alternative": google_news("Vietnam manufacturing OR Vietnam exports OR China alternative sourcing OR supply chain"),
        "Taiwan Halbleiter und Risiko": google_news("Taiwan semiconductor OR Taiwan trade China risk OR supply chain Europe"),
        "Japan und Korea Industrie": google_news("Japan manufacturing exports OR South Korea manufacturing exports OR supply chain Europe"),
        "VAE und Jebel Ali": google_news("UAE Dubai Jebel Ali port OR Middle East shipping logistics OR Europe trade"),
        "Singapur Seefracht": google_news("Singapore port OR Singapore shipping congestion OR container freight Asia Europe"),
        "Mexiko Nearshoring": google_news("Mexico nearshoring OR Mexico manufacturing exports OR USA supply chain"),
        "Deutschland Produktengpaesse": google_news("Deutschland Lieferengpass Warenmangel Klimaanlagen Ventilatoren Matratzen Import Handel"),
        "Deutsche B2B Nachfrage": google_news("Deutschland B2B Einkauf Lieferanten Produkte Nachfrage Handel Import"),
        "Aktuelle Engpaesse Deutschland": google_news("Deutschland Engpass Lieferengpass Produkte Handel Verbraucher Import"),
        "Aktuelle Supply Chain Research": google_news("supply chain disruption Europe Asia shipping logistics analysis"),
        "Aktuelle Frachtraten Asien Europa": google_news("Asia Europe container rates Shanghai Rotterdam Drewry Xeneta Freightos latest"),
        "Aktuelle Tuerkei Deutschland Handel": google_news("Turkey Germany trade logistics exports manufacturing latest"),
        "Energie und Rohstoffe": google_news("energy OR oil OR gas OR commodities OR shipping freight rates OR Europe trade"),
        "B2B Commerce und Plattformen": google_news("B2B commerce OR procurement OR supplier marketplace OR manufacturing AI OR sourcing"),
        "Weltpolitik mit Handelswirkung": google_news("geopolitics sanctions OR conflict trade impact OR supply chains"),
    }
    page = None
    try:
        if open_world_monitor:
            ctx = await _get_browser()
            page = await ctx.new_page()
            await page.goto("https://www.worldmonitor.app/", timeout=20000)
            _bring_chromium_to_front()
            await page.wait_for_timeout(2500)

        async def load_feed(client, section: str, url: str) -> tuple[str, list[tuple[datetime, str, str]]]:
            response = await client.get(url)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            parsed_items = []
            for item in root.findall(".//item")[:40]:
                title = (item.findtext("title") or "").strip()
                source = item.findtext("source") or ""
                published = item.findtext("pubDate") or ""
                link = (item.findtext("link") or "").strip()
                if title:
                    try:
                        published_dt = parsedate_to_datetime(published)
                    except Exception:
                        published_dt = datetime.min.replace(tzinfo=timezone.utc)
                    link_part = f", {link}" if link else ""
                    parsed_items.append((published_dt, make_title_key(title), f"- {title} ({source}, {published}{link_part})"))
            parsed_items.sort(key=lambda row: row[0], reverse=True)
            return section, parsed_items[:12]

        sections = []
        seen_titles = set()
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            tasks = [load_feed(client, section, url) for section, url in feeds.items()]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    continue
                section, items = result
                unique_items = []
                for line in items:
                    title_key = re.sub(r"\s+\([^)]*\)\s*$", "", line.lower())
                    title_key = re.sub(r"[^a-z0-9äöüß]+", " ", title_key).strip()[:180]
                    if title_key in seen_titles:
                        continue
                    seen_titles.add(title_key)
                    unique_items.append(line)
                if unique_items:
                    sections.append(f"{section}:\n" + "\n".join(unique_items))

        if not sections:
            return "Keine aktuellen Nachrichtenfeeds konnten geladen werden."
        return "Aktuelle Nachrichten mit Fokus auf Handel, Lieferketten und Geopolitik:\n\n" + "\n\n".join(sections)
    except Exception as e:
        return f"News konnten nicht geladen werden: {e}"
    finally:
        pass  # Keep page open so user can see it


async def fetch_news_deep(open_world_monitor: bool = False) -> str:
    """Deep-research current news; avoids repeating already reported headlines."""
    cache_buster = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")

    def make_title_key(value: str) -> str:
        key = re.sub(r"\s+\([^)]*\)\s*$", "", str(value or "").lower())
        key = re.sub(r"[^a-z0-9äöüß]+", " ", key).strip()
        return key[:190]

    def is_deep_news_noise(title: str, source: str) -> bool:
        normalized = f"{title} {source}".lower()
        noise_terms = [
            "stock", "aktie", "aktien", "share price", "shares", "börsen",
            "boerse", "kursziel", "dividend", "dividende", "trading stays",
            "stock holds", "ad hoc news", "finanznachrichten", "wallstreet online",
            "gurufocus", "marketscreener", "simply wall st",
        ]
        strong_terms = [
            "trade", "tariff", "customs", "supply chain", "shipping", "freight",
            "container", "port", "import", "export", "regulation", "zoll",
            "lieferkette", "seefracht", "hafen", "suez", "hormuz", "hormus",
            "red sea", "rotes meer", "turkey", "tuerkei", "china", "nearshoring",
        ]
        return any(term in normalized for term in noise_terms) and not any(term in normalized for term in strong_terms)

    def load_news_history() -> set[str]:
        try:
            data = json.loads(NEWS_HISTORY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return {str(item) for item in data[-500:]}
        except Exception:
            pass
        return set()

    def save_news_history(keys: list[str]) -> None:
        try:
            existing = list(load_news_history())
            merged = (existing + keys)[-500:]
            NEWS_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
            NEWS_HISTORY_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def google_news(query: str, force_fresh: bool = True) -> str:
        fresh_query = f"({query}) when:7d" if force_fresh else query
        return "https://news.google.com/rss/search?" + urlencode({
            "q": fresh_query,
            "hl": "de",
            "gl": "DE",
            "ceid": "DE:de",
            "_": cache_buster,
        })

    def bing_news(query: str) -> str:
        simple_query = re.sub(r"\s+OR\s+", " ", str(query or ""), flags=re.IGNORECASE)
        simple_query = re.sub(r"[()]+", " ", simple_query)
        simple_query = re.sub(r"\s+", " ", simple_query).strip()
        return "https://www.bing.com/news/search?" + urlencode({
            "q": simple_query,
            "format": "rss",
            "setlang": "de-DE",
            "cc": "DE",
            "_": cache_buster,
        })

    query_clusters = [
        ("Deep Research: Welthandel", "international trade OR global trade OR tariffs OR customs OR supply chain OR import OR export"),
        ("Deep Research: Regulierung", "EU regulation OR new law OR customs law OR trade compliance OR import rules OR supply chain due diligence"),
        ("EU Zoll und Import-Compliance", "EU customs OR import regulation OR CBAM OR EUDR OR forced labour regulation"),
        ("Deutschland Einkauf und Import", "Germany import OR Germany procurement OR German retailers OR Germany sourcing OR logistics shortages"),
        ("Tuerkei Industrie und Export", "Turkey exports OR Turkey manufacturing OR Istanbul logistics OR Turkey Germany trade"),
        ("Tuerkei Nearshoring", "Turkey nearshoring OR Turkey suppliers OR Turkey manufacturing Europe OR Istanbul Germany logistics"),
        ("China Export und Fabrikdaten", "China exports OR China manufacturing PMI OR China factory orders OR China supply chain"),
        ("China Seefrachtpreise", "China freight rates OR Shanghai Europe freight OR SCFI OR Drewry OR Freightos OR Xeneta"),
        ("Containerpreise Reports", "Drewry World Container Index OR Shanghai Europe freight rates OR Xeneta OR Freightos Baltic Index"),
        ("Hafenstau und Transitzeiten", "port congestion OR container transit times OR Shanghai port OR Ningbo port OR Rotterdam port OR Hamburg port"),
        ("USA China Handel", "USA China trade OR US China tariffs OR export controls OR China import restrictions"),
        ("Suez Kanal", "Suez Canal shipping OR Egypt Suez OR Europe Asia container vessels OR Suez disruption"),
        ("Strasse von Hormus", "Tehran Strait of Hormuz OR Hormuz shipping OR oil gas shipping risk OR freight insurance"),
        ("Rotes Meer Frachtsicherheit", "Red Sea shipping OR Red Sea attacks OR freight insurance OR container ships rerouting"),
        ("Naher Osten Handelsrouten", "Middle East shipping OR trade routes OR Red Sea OR Suez OR Hormuz logistics"),
        ("Russland Sanktionen Energie", "Russia sanctions OR Russia energy trade OR Europe gas OR shipping logistics"),
        ("Ukraine Lieferketten", "Ukraine war OR grain logistics OR Ukraine energy trade OR Europe supply chain"),
        ("Indien Beschaffung Export", "India manufacturing exports OR India suppliers OR India procurement OR India logistics"),
        ("Rotterdam und Hamburg", "Rotterdam port OR Hamburg port container congestion OR Europe trade logistics"),
        ("Vietnam China Alternative", "Vietnam manufacturing OR Vietnam exports OR China alternative sourcing OR supply chain"),
        ("Taiwan Supply Chain Risiko", "Taiwan semiconductor OR Taiwan trade China risk OR supply chain Europe"),
        ("Deutschland Produktengpaesse", "Deutschland Lieferengpass Warenmangel Klimaanlagen Ventilatoren Matratzen Import Handel"),
        ("Aktuelle Engpaesse Deutschland", "Deutschland Engpass Lieferengpass Produkte Handel Verbraucher Import"),
        ("B2B Commerce Procurement", "B2B commerce OR procurement OR supplier marketplace OR manufacturing AI OR sourcing"),
        ("Weltpolitik mit Handelswirkung", "geopolitics sanctions OR conflict trade impact OR supply chains"),
    ]
    bing_query_overrides = {
        "Deep Research: Welthandel": "global trade supply chain shipping tariffs latest",
        "Deep Research: Regulierung": "EU import customs regulation forced labour CBAM EUDR latest",
        "EU Zoll und Import-Compliance": "EU customs import compliance CBAM EUDR forced labour regulation",
        "Deutschland Einkauf und Import": "Germany import logistics truck shortage procurement retail latest",
        "Tuerkei Industrie und Export": "Turkey manufacturing exports Germany trade",
        "Tuerkei Nearshoring": "Turkey nearshoring Europe suppliers manufacturing",
        "China Export und Fabrikdaten": "China factory activity exports manufacturing PMI latest",
        "China Seefrachtpreise": "China freight rates Shanghai Europe container shipping latest",
        "Containerpreise Reports": "Drewry World Container Index Freightos Xeneta container rates latest",
        "Hafenstau und Transitzeiten": "port congestion container shipping Rotterdam Hamburg Shanghai latest",
        "USA China Handel": "US China tariffs export controls trade latest",
        "Suez Kanal": "Suez Canal shipping Europe Asia containers latest",
        "Strasse von Hormus": "Strait of Hormuz shipping risk Iran latest",
        "Rotes Meer Frachtsicherheit": "Red Sea shipping attacks rerouting container ships latest",
        "Naher Osten Handelsrouten": "Middle East shipping routes Red Sea Suez Hormuz latest",
        "Russland Sanktionen Energie": "Russia sanctions Europe energy gas trade latest",
        "Ukraine Lieferketten": "Ukraine war Europe supply chain logistics latest",
        "Indien Beschaffung Export": "India manufacturing exports supply chain labour rules latest",
        "Rotterdam und Hamburg": "Rotterdam Hamburg port container congestion latest",
        "Vietnam China Alternative": "Vietnam manufacturing exports China alternative sourcing latest",
        "Taiwan Supply Chain Risiko": "Taiwan trade China supply chain risk latest",
        "Deutschland Produktengpaesse": "Germany product shortage air conditioners mattresses fans import",
        "Aktuelle Engpaesse Deutschland": "Germany supply shortage retail import products",
        "B2B Commerce Procurement": "B2B procurement supplier marketplace manufacturing AI latest",
        "Weltpolitik mit Handelswirkung": "geopolitics sanctions conflict trade impact supply chains latest",
    }

    if open_world_monitor:
        ctx = await _get_browser()
        page = await ctx.new_page()
        await page.goto("https://www.worldmonitor.app/", timeout=20000)
        _bring_chromium_to_front()
        await page.wait_for_timeout(2500)

    async def load_feed(client, section: str, query: str, force_fresh: bool = True, provider: str = "google") -> tuple[str, list[tuple[int, datetime, str, str]]]:
        url = bing_news(query) if provider == "bing" else google_news(query, force_fresh=force_fresh)
        response = await client.get(url)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        parsed_items = []
        for item in root.findall(".//item")[:40]:
            title = (item.findtext("title") or "").strip()
            source = item.findtext("source") or ""
            published = item.findtext("pubDate") or ""
            link = (item.findtext("link") or "").strip()
            if not title:
                continue
            if is_deep_news_noise(title, source) or _is_bad_news_source_or_title(title, source):
                continue
            score = _deep_news_score(section, title, source)
            if score < 5:
                continue
            try:
                published_dt = parsedate_to_datetime(published)
            except Exception:
                published_dt = datetime.min.replace(tzinfo=timezone.utc)
            if published_dt.tzinfo is None:
                published_dt = published_dt.replace(tzinfo=timezone.utc)
            if published_dt != datetime.min.replace(tzinfo=timezone.utc):
                age_days = (datetime.now(timezone.utc) - published_dt.astimezone(timezone.utc)).days
                if age_days > 14:
                    continue
            link_part = f", {link}" if link else ""
            provider_label = "Bing News" if provider == "bing" else (source or "Google News")
            parsed_items.append((score, published_dt, make_title_key(title), f"- {title} ({provider_label}, {published}{link_part})"))
        parsed_items.sort(key=lambda row: (row[0], row[1]), reverse=True)
        return section, parsed_items[:5]

    sections = []
    seen_titles = set()
    reported_history = load_news_history()
    selected_history_keys: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            tasks = (
                [load_feed(client, section, query, True, "google") for section, query in query_clusters]
                + [load_feed(client, section, bing_query_overrides.get(section, query), True, "bing") for section, query in query_clusters]
            )
            results = await asyncio.gather(*tasks, return_exceptions=True)
            if all(isinstance(result, Exception) or not result[1] for result in results):
                tasks = [load_feed(client, section, query, False, "google") for section, query in query_clusters]
                results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    continue
                section, items = result
                unique_items = []
                fallback_items = []
                for _score, _published_dt, key, line in items:
                    if key in seen_titles:
                        continue
                    seen_titles.add(key)
                    if key in reported_history:
                        fallback_items.append((key, line))
                        continue
                    unique_items.append(line)
                    selected_history_keys.append(key)
                if not unique_items and fallback_items:
                    for key, line in fallback_items[:2]:
                        unique_items.append(line)
                        selected_history_keys.append(key)
                if unique_items:
                    sections.append(f"{section}:\n" + "\n".join(unique_items))
        if not sections:
            return "Keine aktuellen Deep-Research-Newsfeeds konnten geladen werden."
        save_news_history(selected_history_keys)
        return (
            "Deep-Research-Nachrichten mit Fokus auf Handel, Lieferketten, Regulierung, China-Alternative und MySupplieX:\n"
            f"Methodik: {len(query_clusters)} frische Suchcluster, Google-News-Zeitraum 7 Tage, lokale Dedupe-History gegen Wiederholungen.\n\n"
            + "\n\n".join(sections)
        )
    except Exception as exc:
        return f"Deep-Research-News konnten nicht geladen werden: {exc}"


async def _show_country_overlay(page, country_name: str):
    await page.evaluate(
        """(name) => {
            let box = document.getElementById('xeon-country-focus');
            if (!box) {
                box = document.createElement('div');
                box.id = 'xeon-country-focus';
                box.style.position = 'fixed';
                box.style.top = '22px';
                box.style.left = '50%';
                box.style.transform = 'translateX(-50%)';
                box.style.zIndex = '2147483647';
                box.style.padding = '12px 18px';
                box.style.border = '1px solid rgba(255, 40, 60, .75)';
                box.style.borderRadius = '10px';
                box.style.background = 'rgba(18, 3, 7, .88)';
                box.style.color = '#ffecef';
                box.style.fontFamily = 'Segoe UI, Arial, sans-serif';
                box.style.fontSize = '18px';
                box.style.fontWeight = '700';
                box.style.boxShadow = '0 0 32px rgba(255, 40, 60, .42)';
                document.body.appendChild(box);
            }
            box.textContent = 'XEON Fokus: ' + name;
        }""",
        country_name,
    )


async def focus_world_monitor_countries(country_codes: list[str]) -> str:
    """Best-effort visual country focus on World Monitor."""
    codes = []
    for code in country_codes:
        if code in COUNTRY_FOCUS and code not in codes:
            codes.append(code)
    if not codes:
        codes = ["germany", "turkey", "china", "usa"]
    codes = codes[:6]

    try:
        for code in codes:
            await focus_world_monitor_country(code)
            await asyncio.sleep(1.5)
            await reset_world_monitor_zoom()
            await asyncio.sleep(0.4)
        return "World Monitor wurde fuer diese Laender fokussiert: " + ", ".join(COUNTRY_FOCUS[code]["name"] for code in codes)
    except Exception as exc:
        return f"World-Monitor-Fokus konnte nicht ausgefuehrt werden: {exc}"
    finally:
        pass


async def focus_world_monitor_country(country_code: str, label: str = "") -> str:
    """Focus one country on the existing World Monitor page while XEON speaks."""
    country = COUNTRY_FOCUS.get(country_code)
    if not country:
        return f"Unbekanntes Land fuer World Monitor: {country_code}"
    try:
        page = await _ensure_world_monitor_page()
        await page.bring_to_front()
        _bring_chromium_to_front()
        await _show_country_overlay(page, label or country["name"])
        focused = await _focus_world_monitor_country_by_search(page, country)
        await _show_country_overlay(page, label or country["name"])
        if not focused:
            return f"World Monitor fokussiert: {country['name']} (Klickbestaetigung nicht erkannt)"
        return f"World Monitor fokussiert: {country['name']}"
    except Exception as exc:
        return f"World-Monitor-Fokus konnte nicht ausgefuehrt werden: {exc}"


async def reset_world_monitor_zoom() -> str:
    try:
        if _world_monitor_page is None or _world_monitor_page.is_closed():
            return "World Monitor ist nicht offen."
        page = _world_monitor_page
        await page.bring_to_front()
        _bring_chromium_to_front()
        await _reset_world_monitor_in_place(page)
        await page.wait_for_timeout(450)
        return "World Monitor herausgezoomt."
    except Exception as exc:
        return f"World Monitor konnte nicht herauszoomen: {exc}"


async def close_world_monitor() -> str:
    global _world_monitor_page
    try:
        if _world_monitor_page is None or _world_monitor_page.is_closed():
            return "World Monitor war bereits geschlossen."
        await _world_monitor_page.close()
        _world_monitor_page = None
        return "World Monitor geschlossen."
    except Exception as exc:
        return f"World Monitor konnte nicht geschlossen werden: {exc}"


async def open_url(url: str):
    """Open URL in user's default browser (non-blocking)."""
    import asyncio
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, webbrowser.open, url)
    return {"success": True, "url": url}


async def indeed_employer(action: str = "read") -> str:
    """Open Indeed employer account and read visible applicant/message text."""
    ctx = await _get_browser()
    page = await ctx.new_page()
    try:
        await page.goto("https://employers.indeed.com/applicants", timeout=25000, wait_until="domcontentloaded")
        _bring_chromium_to_front()
        await page.wait_for_timeout(3500)
        title = await page.title()
        url = page.url
        text = await page.evaluate("""
            () => document.body?.innerText?.trim() || ''
        """)
        if "login" in url.lower() or "signin" in url.lower() or "einloggen" in text.lower() or "sign in" in text.lower():
            return (
                "Indeed Arbeitgeber ist geoeffnet, aber Sie muessen sich dort einmal einloggen. "
                "Nach dem Login kann XEON diese Browser-Session wiederverwenden."
            )
        if action == "open":
            return f"Indeed Arbeitgeber wurde geoeffnet: {title}"
        return f"Indeed Arbeitgeber Ansicht: {title}\nURL: {url}\n\n{text[:6000]}"
    except Exception as exc:
        return f"Indeed Arbeitgeber konnte nicht gelesen werden: {exc}"


async def close():
    global _browser, _context, _playwright
    if _context:
        await _context.close()
        _browser = None
        _context = None
    if _playwright:
        await _playwright.stop()
        _playwright = None
