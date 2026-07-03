#!/usr/bin/env python3
"""
XEON - Persistent acoustic trigger.
Two claps or finger snaps launch XEON. Three claps/snaps close XEON.
"""

import json
import os
import subprocess
import time
import ctypes

import numpy as np
import sounddevice as sd


CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config.json")
with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
    config = json.load(f)

WORKSPACE_PATH = config["workspace_path"]
LAUNCH_SCRIPT = os.path.join(WORKSPACE_PATH, "scripts", "launch-session.ps1")
INTRO_LAUNCH_SCRIPT = os.path.join(WORKSPACE_PATH, "scripts", "launch-session-with-intro.ps1")
CLOSE_SCRIPT = os.path.join(WORKSPACE_PATH, "scripts", "close-session.ps1")

SAMPLE_RATE = 44100
BLOCK_SIZE = 1024
THRESHOLD = 0.18
MIN_GAP = 0.16
MAX_GAP = 2.40
DOUBLE_WAIT = 1.75
COOLDOWN = 2.2

claps: list[float] = []
pending_double_time = 0.0
last_trigger_time = 0.0
noise_floor = 0.008
last_rms = 0.0
last_peak = 0.0
keyboard_quiet_until = 0.0

user32 = ctypes.windll.user32 if os.name == "nt" else None
KEY_CODES = list(range(0x08, 0x0E)) + list(range(0x20, 0x5B)) + list(range(0x60, 0x88)) + list(range(0xBA, 0xE3))


def run_script(path: str):
    subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def keyboard_active() -> bool:
    if not user32:
        return False
    try:
        for code in KEY_CODES:
            if user32.GetAsyncKeyState(code) & 0x8000:
                return True
    except Exception:
        return False
    return False


def xeon_window_open() -> bool:
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                (
                    "$p = Get-CimInstance Win32_Process | Where-Object { "
                    "(($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and $_.CommandLine -like '*xeon_launcher.py*') -or "
                    "(($_.Name -eq 'chrome.exe' -or $_.Name -eq 'msedge.exe') -and $_.CommandLine -like '*chrome-xeon-profile*') -or "
                    "($_.Name -eq 'XEON.exe') "
                    "}; if ($p) { '1' }"
                ),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1.5,
        )
        return "1" in result.stdout
    except Exception:
        return False


def fire_launch():
    if xeon_window_open():
        print("[xeon] Double clap/snap detected. XEON already open; ignoring launch.", flush=True)
        return
    print("[xeon] Double clap/snap detected. Playing intro and launching session.", flush=True)
    run_script(INTRO_LAUNCH_SCRIPT if os.path.exists(INTRO_LAUNCH_SCRIPT) else LAUNCH_SCRIPT)


def fire_close():
    print("[xeon] Triple clap/snap detected. Closing session.", flush=True)
    run_script(CLOSE_SCRIPT)


def audio_callback(indata, frames, time_info, status):
    global claps, pending_double_time, last_trigger_time, noise_floor, last_rms, last_peak, keyboard_quiet_until

    now = time.time()
    if keyboard_active():
        keyboard_quiet_until = now + 0.75
        claps = []
        pending_double_time = 0.0
        return
    if now < keyboard_quiet_until:
        return
    if now - last_trigger_time < COOLDOWN:
        return

    samples = np.abs(indata[:, 0] if len(indata.shape) > 1 else indata)
    rms = float(np.sqrt(np.mean(samples**2)))
    peak = float(np.max(samples))

    previous_rms = last_rms
    previous_peak = last_peak
    last_rms = rms
    last_peak = peak

    if peak < 0.06 and rms < 0.035:
        noise_floor = (noise_floor * 0.985) + (rms * 0.015)

    crest = peak / max(rms, 0.0001)
    quiet_before = previous_rms < 0.055 and previous_peak < 0.22
    rms_threshold = max(0.085, min(0.22, noise_floor * 11.0))
    peak_threshold = max(0.50, min(0.72, noise_floor * 34.0))
    transient = quiet_before and peak >= peak_threshold and rms >= max(0.060, noise_floor * 6.0) and 3.0 <= crest <= 16.0
    loud_clap = quiet_before and peak >= 0.58 and rms >= max(THRESHOLD, rms_threshold) and crest <= 11.0
    finger_snap = quiet_before and peak >= 0.32 and rms >= max(0.022, noise_floor * 3.0) and 6.0 <= crest <= 28.0
    if not (transient or loud_clap or finger_snap):
        return

    if claps and now - claps[-1] < MIN_GAP:
        return

    claps = [t for t in claps if now - t <= MAX_GAP]
    claps.append(now)
    print(
        f"[xeon] Trigger {len(claps)} detected (rms={rms:.3f}, peak={peak:.3f}, crest={crest:.1f}, noise={noise_floor:.3f})",
        flush=True,
    )

    if len(claps) >= 3:
        fire_close()
        claps = []
        pending_double_time = 0.0
        last_trigger_time = now
    elif len(claps) == 2:
        pending_double_time = now + DOUBLE_WAIT


with sd.InputStream(
    samplerate=SAMPLE_RATE,
    blocksize=BLOCK_SIZE,
    channels=1,
    dtype="float32",
    callback=audio_callback,
):
    print("[xeon] Listening: double clap/snap opens XEON, triple clap/snap closes.", flush=True)
    while True:
        now = time.time()
        if keyboard_active():
            keyboard_quiet_until = now + 0.75
            claps = []
            pending_double_time = 0.0
        if pending_double_time and now >= pending_double_time:
            fire_launch()
            claps = []
            pending_double_time = 0.0
            last_trigger_time = now
        time.sleep(0.05)
