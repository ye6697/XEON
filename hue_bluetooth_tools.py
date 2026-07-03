"""
Philips Hue Bluetooth control for XEON.

Works without a Hue Bridge by using Bluetooth LE. Hue Bluetooth pairing can be
fussy on Windows; if writes fail, put the lamp into discoverable mode in the Hue
app or pair it in Windows Bluetooth settings, then retry.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from struct import pack
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CACHE_PATH = Path("data/hue_ble_devices.json")
_news_pulse_task: asyncio.Task | None = None
_news_restore_state: dict[str, dict[str, Any]] = {}
_focus_flash_task: asyncio.Task | None = None

COLOR_NAMES: dict[str, tuple[int, int, int]] = {
    "rot": (255, 0, 0),
    "red": (255, 0, 0),
    "blau": (0, 50, 255),
    "blue": (0, 50, 255),
    "gruen": (0, 255, 70),
    "grün": (0, 255, 70),
    "green": (0, 255, 70),
    "gelb": (255, 220, 0),
    "yellow": (255, 220, 0),
    "orange": (255, 110, 0),
    "lila": (160, 55, 255),
    "violett": (150, 45, 255),
    "purple": (150, 45, 255),
    "pink": (255, 45, 170),
    "rosa": (255, 70, 185),
    "cyan": (0, 210, 255),
    "tuerkis": (0, 230, 210),
    "türkis": (0, 230, 210),
    "weiss": (255, 244, 229),
    "weiß": (255, 244, 229),
    "white": (255, 244, 229),
}

SCENES: dict[str, dict[str, Any]] = {
    "fokus": {"temperature": 250, "brightness": 90},
    "arbeit": {"temperature": 250, "brightness": 90},
    "konzentration": {"temperature": 230, "brightness": 95},
    "abend": {"temperature": 420, "brightness": 35},
    "entspann": {"temperature": 430, "brightness": 30},
    "gemuetlich": {"temperature": 430, "brightness": 32},
    "gemütlich": {"temperature": 430, "brightness": 32},
    "film": {"color": "orange", "brightness": 25},
    "kino": {"color": "orange", "brightness": 20},
    "ceo": {"color": "rot", "brightness": 65},
    "alarm": {"color": "rot", "brightness": 100},
    "nacht": {"color": "blau", "brightness": 12},
}


@dataclass
class HueCommand:
    operation: str
    target: str = "all"
    on: bool | None = None
    brightness: int | None = None
    color: str | None = None
    rgb: tuple[int, int, int] | None = None
    temperature: int | None = None
    scan_seconds: int = 7


def _load_cache() -> list[dict[str, str]]:
    try:
        if CACHE_PATH.exists():
            data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict) and item.get("address")]
    except Exception:
        pass
    return []


def _save_cache(devices: list[Any]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = []
    seen = set()
    for device in devices:
        address = str(getattr(device, "address", "") or "")
        if not address or address in seen:
            continue
        seen.add(address)
        data.append({"address": address, "name": str(getattr(device, "name", "") or "Hue Lampe")})
    CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize(text: str) -> str:
    text = str(text or "").lower()
    text = text.replace("ß", "ss")
    replacements = {"ä": "ae", "ö": "oe", "ü": "ue"}
    for old, new in replacements.items():
        text = text.replace(old, new)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9%]+", " ", text)).strip()


def _percent_to_brightness(percent: int) -> int:
    return max(1, min(254, round(max(0, min(100, percent)) / 100 * 254)))


def _brightness_to_percent(value: int) -> int:
    return max(1, min(100, round(value / 254 * 100)))


def rgb_to_xy(red: int, green: int, blue: int) -> tuple[float, float]:
    r = red / 255
    g = green / 255
    b = blue / 255

    r = ((r + 0.055) / 1.055) ** 2.4 if r > 0.04045 else r / 12.92
    g = ((g + 0.055) / 1.055) ** 2.4 if g > 0.04045 else g / 12.92
    b = ((b + 0.055) / 1.055) ** 2.4 if b > 0.04045 else b / 12.92

    x = r * 0.664511 + g * 0.154324 + b * 0.162028
    y = r * 0.283881 + g * 0.668433 + b * 0.047685
    z = r * 0.000088 + g * 0.072310 + b * 0.986039
    total = x + y + z
    if total <= 0:
        return 0.3227, 0.3290
    return max(0.0, min(1.0, x / total)), max(0.0, min(1.0, y / total))


def is_hue_request(text: str) -> bool:
    normalized = _normalize(text)
    if not normalized:
        return False
    lighting_words = [
        "hue", "philips", "lampe", "lampen", "licht", "lichter", "gluehbirne",
        "gluehbirnen", "leuchte", "leuchten", "beleuchtung",
    ]
    action_words = [
        "an", "aus", "einschalten", "ausschalten", "farbe", "helligkeit", "heller",
        "dunkler", "dimmen", "rot", "blau", "gruen", "gelb", "orange", "lila",
        "pink", "weiss", "warm", "kalt", "fokus", "gemuetlich", "scan", "suche",
    ]
    return any(word in normalized for word in lighting_words) and any(word in normalized for word in action_words)


def parse_hue_command(payload: str | dict[str, Any]) -> HueCommand:
    if isinstance(payload, dict):
        rgb = payload.get("rgb")
        rgb_tuple = tuple(rgb) if isinstance(rgb, list | tuple) and len(rgb) == 3 else None
        return HueCommand(
            operation=str(payload.get("operation") or "set").lower(),
            target=str(payload.get("target") or "all"),
            on=payload.get("on"),
            brightness=payload.get("brightness"),
            color=payload.get("color"),
            rgb=rgb_tuple,  # type: ignore[arg-type]
            temperature=payload.get("temperature"),
            scan_seconds=int(payload.get("scan_seconds") or 7),
        )

    text = str(payload or "")
    normalized = _normalize(text)
    command = HueCommand(operation="set")

    target_match = re.search(r"(?:lampe|lamp|licht)\s*(\d+)", normalized)
    if target_match:
        command.target = f"lamp {target_match.group(1)}"

    if any(term in normalized for term in ["scan", "suche", "finden", "auflisten", "liste"]):
        command.operation = "scan"
        return command

    if any(term in normalized for term in ["status", "zustand"]):
        command.operation = "status"
        return command

    if any(term in normalized for term in ["ausschalten", "mach aus", "licht aus", "lampen aus", "ausmachen"]) or re.search(r"(?:lampe|lamp|licht)\s*\d+\s*aus", normalized):
        command.on = False
    elif any(term in normalized for term in ["einschalten", "mach an", "licht an", "lampen an", "anmachen"]) or re.search(r"(?:lampe|lamp|licht)\s*\d+\s*an", normalized):
        command.on = True

    percent_match = re.search(r"(\d{1,3})\s*(?:%|prozent)", normalized)
    if percent_match:
        command.brightness = max(1, min(100, int(percent_match.group(1))))
    elif "heller" in normalized:
        command.brightness = 90
    elif "dunkler" in normalized or "dimmen" in normalized:
        command.brightness = 25

    if "warm" in normalized:
        command.temperature = 420
    elif "kalt" in normalized or "tageslicht" in normalized:
        command.temperature = 230

    for scene, settings in SCENES.items():
        if _normalize(scene) in normalized:
            command.on = True
            command.color = settings.get("color")
            command.brightness = settings.get("brightness", command.brightness)
            command.temperature = settings.get("temperature", command.temperature)
            break

    for color in COLOR_NAMES:
        if _normalize(color) in normalized:
            command.color = color
            command.on = True
            break

    if command.on is None and (command.color or command.brightness or command.temperature):
        command.on = True

    return command


async def discover_devices(timeout: int = 7) -> list[Any]:
    import HueBLE

    devices = await HueBLE.discover_lights(timeout=timeout)
    _save_cache(devices)
    return devices


async def _get_target_devices(command: HueCommand) -> list[Any]:
    import HueBLE
    from bleak.backends.device import BLEDevice

    devices = await HueBLE.discover_lights(timeout=command.scan_seconds)
    if devices:
        _save_cache(devices)
    else:
        devices = [
            BLEDevice(item["address"], item.get("name") or "Hue Lampe", details={})
            for item in _load_cache()
        ]

    target = _normalize(command.target)
    if target in {"", "all", "alle", "lampen", "licht", "lichter"}:
        return devices

    filtered = [
        device for device in devices
        if target in _normalize(getattr(device, "name", "") or getattr(device, "address", ""))
    ]
    return filtered or devices[:1]


async def _apply_to_device(device: Any, command: HueCommand) -> str:
    import HueBLE

    light = HueBLE.HueBleLight(device)
    name = str(getattr(device, "name", "") or "Hue Lampe")
    try:
        await light.connect(connection_timeout=20)
        if command.rgb or command.color:
            rgb = command.rgb or COLOR_NAMES.get(str(command.color).lower())
            if rgb:
                x, y = rgb_to_xy(*rgb)
                brightness = _percent_to_brightness(int(command.brightness if command.brightness is not None else 100))
                # One Hue effects write carries on/off, brightness and colour together.
                # This is more reliable on Windows BLE than three separate writes.
                await light.set_colour_effect(x, y, brightness, HueBLE.EffectType.NONE, 0)
        elif command.temperature is not None:
            brightness = _percent_to_brightness(int(command.brightness if command.brightness is not None else 100))
            await light.set_temperature_effect(int(command.temperature), brightness, HueBLE.EffectType.NONE, 0)
        else:
            if command.on is not None:
                await light.set_power(bool(command.on))
            if command.brightness is not None:
                await light.set_brightness(_percent_to_brightness(int(command.brightness)))
        if command.operation == "status":
            try:
                await light.poll_state()
            except Exception:
                pass
            return f"{name}: verbunden."
        return f"{name}: ausgefuehrt."
    finally:
        try:
            await light.disconnect()
        except Exception:
            pass


async def execute_hue_command(payload: str | dict[str, Any]) -> str:
    command = parse_hue_command(payload)
    if command.operation == "scan":
        try:
            devices = await discover_devices(command.scan_seconds)
        except Exception as exc:
            return _format_hue_error(exc)
        if not devices:
            return (
                "Keine Philips-Hue-Bluetooth-Lampen gefunden. Bluetooth muss an sein, die Lampen muessen in Reichweite sein, "
                "und falls sie bereits mit der Hue-App gekoppelt sind: Hue-App oeffnen, Einstellungen, Sprachassistenten, Alexa oder Google, 'Make Discoverable'."
            )
        names = [f"{getattr(device, 'name', 'Hue Lampe')} ({getattr(device, 'address', 'keine Adresse')})" for device in devices]
        return "Gefundene Hue-Bluetooth-Lampen: " + "; ".join(names)

    devices = await _get_target_devices(command)
    if not devices:
        return (
            "Ich finde gerade keine Hue-Bluetooth-Lampe, Sir. Bitte Bluetooth aktivieren und die Lampen in Discoverable/Pairing-Modus setzen. "
            "Ohne Bridge laeuft das direkt ueber Bluetooth, also muss der PC wirklich in Reichweite sein."
        )

    results = []
    errors = []
    for device in devices:
        try:
            results.append(await asyncio.wait_for(_apply_to_device_with_retry(device, command), timeout=55))
        except Exception as exc:
            errors.append(f"{getattr(device, 'name', 'Hue Lampe')}: {_format_hue_error(exc)}")

    if results and not errors:
        return "Hue-Befehl erledigt, Sir. " + " ".join(results)
    if results:
        return "Teilweise erledigt, Sir. " + " ".join(results + errors)
    return "Hue-Befehl fehlgeschlagen, Sir. " + " ".join(errors)


async def _apply_to_device_with_retry(device: Any, command: HueCommand) -> str:
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            return await _apply_to_device(device, command)
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                await asyncio.sleep(1.2)
                continue
            try:
                return await _apply_to_device_raw(device, command)
            except Exception:
                raise last_error
    if last_error:
        raise last_error
    return f"{getattr(device, 'name', 'Hue Lampe')}: nicht ausgefuehrt."


async def _write_raw(client: Any, uuid: str, data: bytes) -> None:
    await client.write_gatt_char(uuid, data, response=True)


async def _apply_to_device_raw(device: Any, command: HueCommand) -> str:
    import HueBLE
    from bleak import BleakClient

    name = str(getattr(device, "name", "") or "Hue Lampe")
    async with BleakClient(device, timeout=25, pair=True) as client:
        if command.rgb or command.color:
            rgb = command.rgb or COLOR_NAMES.get(str(command.color).lower())
            if not rgb:
                raise RuntimeError("Unbekannte Farbe")
            x, y = rgb_to_xy(*rgb)
            brightness = _percent_to_brightness(int(command.brightness if command.brightness is not None else 100))
            effects_buf = pack(
                "<2sB2sB2sHH",
                bytes.fromhex(HueBLE.EffectCommands.ONOFF.value),
                0x1,
                bytes.fromhex(HueBLE.EffectCommands.BRIGHTNESS.value),
                brightness,
                bytes.fromhex(HueBLE.EffectCommands.COLOURXY.value),
                int(x * 0xFFFF),
                int(y * 0xFFFF),
            )
            try:
                await _write_raw(client, HueBLE.UUID_EFFECTS, effects_buf)
            except Exception:
                await _write_raw(client, HueBLE.UUID_POWER, bytes([1]))
                await asyncio.sleep(0.12)
                await _write_raw(client, HueBLE.UUID_BRIGHTNESS, bytes([brightness]))
                await asyncio.sleep(0.12)
                await _write_raw(client, HueBLE.UUID_XY_COLOUR, pack("<HH", int(x * 0xFFFF), int(y * 0xFFFF)))
        elif command.temperature is not None:
            brightness = _percent_to_brightness(int(command.brightness if command.brightness is not None else 100))
            temperature = max(min(int(command.temperature), 500), 153)
            effects_buf = pack(
                "<2sB2sB2sH",
                bytes.fromhex(HueBLE.EffectCommands.ONOFF.value),
                0x1,
                bytes.fromhex(HueBLE.EffectCommands.BRIGHTNESS.value),
                brightness,
                bytes.fromhex(HueBLE.EffectCommands.TEMPERATURE.value),
                temperature,
            )
            try:
                await _write_raw(client, HueBLE.UUID_EFFECTS, effects_buf)
            except Exception:
                await _write_raw(client, HueBLE.UUID_POWER, bytes([1]))
                await asyncio.sleep(0.12)
                await _write_raw(client, HueBLE.UUID_BRIGHTNESS, bytes([brightness]))
                await asyncio.sleep(0.12)
                await _write_raw(client, HueBLE.UUID_TEMPERATURE, int(temperature).to_bytes(2, "little"))
        else:
            if command.on is not None:
                await _write_raw(client, HueBLE.UUID_POWER, bytes([1 if command.on else 0]))
            if command.brightness is not None:
                await _write_raw(client, HueBLE.UUID_BRIGHTNESS, bytes([_percent_to_brightness(int(command.brightness))]))
    return f"{name}: ausgefuehrt."


async def _capture_state(client: Any) -> dict[str, Any]:
    import HueBLE

    state: dict[str, Any] = {}
    for key, uuid in {
        "power": HueBLE.UUID_POWER,
        "brightness": HueBLE.UUID_BRIGHTNESS,
        "temperature": HueBLE.UUID_TEMPERATURE,
        "xy": HueBLE.UUID_XY_COLOUR,
    }.items():
        try:
            state[key] = bytes(await client.read_gatt_char(uuid))
        except Exception:
            state[key] = None
    return state


async def _restore_state(client: Any, state: dict[str, Any]) -> None:
    import HueBLE

    if state.get("power") is not None:
        await _write_raw(client, HueBLE.UUID_POWER, state["power"])
        await asyncio.sleep(0.08)
    if state.get("brightness") is not None:
        await _write_raw(client, HueBLE.UUID_BRIGHTNESS, state["brightness"])
        await asyncio.sleep(0.08)
    xy = state.get("xy")
    temperature = state.get("temperature")
    if isinstance(xy, bytes) and len(xy) == 4 and xy != b"\xff\xff\xff\xff":
        await _write_raw(client, HueBLE.UUID_XY_COLOUR, xy)
    elif isinstance(temperature, bytes) and len(temperature) == 2 and temperature != b"\xff\xff":
        await _write_raw(client, HueBLE.UUID_TEMPERATURE, temperature)


async def _set_raw_red(client: Any, brightness_percent: int) -> None:
    import HueBLE

    x, y = rgb_to_xy(255, 0, 0)
    brightness = _percent_to_brightness(brightness_percent)
    await _write_raw(client, HueBLE.UUID_POWER, bytes([1]))
    await asyncio.sleep(0.08)
    await _write_raw(client, HueBLE.UUID_BRIGHTNESS, bytes([brightness]))
    await asyncio.sleep(0.08)
    await _write_raw(client, HueBLE.UUID_XY_COLOUR, pack("<HH", int(x * 0xFFFF), int(y * 0xFFFF)))


async def start_news_pulse() -> str:
    global _news_pulse_task, _news_restore_state
    if _news_pulse_task and not _news_pulse_task.done():
        return "Hue-News-Puls laeuft bereits."

    devices = await _get_target_devices(HueCommand(operation="set", target="all", scan_seconds=5))
    _news_restore_state = {}
    if not devices:
        return "Keine Hue-Bluetooth-Lampen fuer den News-Puls gefunden."

    async def pulse_loop():
        from bleak import BleakClient

        connected: list[tuple[Any, Any]] = []
        try:
            for device in devices:
                name = str(getattr(device, "name", "") or getattr(device, "address", "") or "Hue Lampe")
                try:
                    client = BleakClient(device, timeout=25, pair=True)
                    await client.connect()
                    _news_restore_state[name] = await _capture_state(client)
                    connected.append((device, client))
                except Exception:
                    continue
            high = True
            while True:
                brightness = 100 if high else 28
                for _, client in list(connected):
                    try:
                        await _set_raw_red(client, brightness)
                    except Exception:
                        pass
                high = not high
                await asyncio.sleep(0.85)
        except asyncio.CancelledError:
            raise
        finally:
            for device, client in connected:
                name = str(getattr(device, "name", "") or getattr(device, "address", "") or "Hue Lampe")
                try:
                    state = _news_restore_state.get(name)
                    if state:
                        await _restore_state(client, state)
                except Exception:
                    pass
                try:
                    await client.disconnect()
                except Exception:
                    pass

    _news_pulse_task = asyncio.create_task(pulse_loop())
    return "Hue-News-Puls gestartet."


async def stop_news_pulse() -> str:
    global _news_pulse_task
    if not _news_pulse_task or _news_pulse_task.done():
        return "Hue-News-Puls war nicht aktiv."
    _news_pulse_task.cancel()
    try:
        await _news_pulse_task
    except asyncio.CancelledError:
        pass
    return "Hue-News-Puls gestoppt und Lampen wiederhergestellt."


async def start_focus_guard_flash(duration_seconds: float = 10.0) -> str:
    global _focus_flash_task
    if _focus_flash_task and not _focus_flash_task.done():
        return "Hue-Focus-Guard-Blitz laeuft bereits."

    devices = await _get_target_devices(HueCommand(operation="set", target="all", scan_seconds=4))
    if not devices:
        return "Keine Hue-Bluetooth-Lampen fuer Focus Guard gefunden."

    async def flash_once():
        from bleak import BleakClient
        import HueBLE

        connected: list[tuple[Any, Any, dict[str, Any]]] = []
        try:
            for device in devices:
                try:
                    client = BleakClient(device, timeout=18, pair=True)
                    await client.connect()
                    state = await _capture_state(client)
                    connected.append((device, client, state))
                except Exception:
                    continue
            deadline = asyncio.get_running_loop().time() + float(duration_seconds)
            on_state = True
            while asyncio.get_running_loop().time() < deadline:
                for _, client, _ in list(connected):
                    try:
                        if on_state:
                            await _set_raw_red(client, 100)
                        else:
                            await _write_raw(client, HueBLE.UUID_POWER, bytes([0]))
                    except Exception:
                        pass
                on_state = not on_state
                await asyncio.sleep(0.18)
        finally:
            for _, client, state in connected:
                try:
                    await _restore_state(client, state)
                except Exception:
                    pass
                try:
                    await client.disconnect()
                except Exception:
                    pass

    _focus_flash_task = asyncio.create_task(flash_once())
    return "Hue-Focus-Guard-Blitz gestartet."


def _format_hue_error(exc: Exception) -> str:
    text = str(exc) or exc.__class__.__name__
    hint = (
        " Falls Windows die Lampe noch nicht gekoppelt hat: Hue-App auf Bluetooth-Modus oeffnen, "
        "Lampe unter Sprachassistenten fuer Alexa/Google discoverable machen oder in Windows Bluetooth koppeln, dann erneut versuchen."
    )
    if any(word in text.lower() for word in ["pair", "auth", "permission", "access", "not permitted", "protocol", "unable to write"]):
        return f"Bluetooth-Pairing oder aktiver BLE-Zugriff blockiert diese Lampe.{hint}"
    if any(word in text.lower() for word in ["not found", "device", "connect", "timeout"]):
        return f"Verbindung zur Lampe nicht stabil oder nicht in Reichweite.{hint}"
    return f"{text}.{hint}"


if __name__ == "__main__":
    import sys

    query = " ".join(sys.argv[1:]) or "scan"
    print(asyncio.run(execute_hue_command(query)))
