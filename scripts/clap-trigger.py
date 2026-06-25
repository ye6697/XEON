#!/usr/bin/env python3
"""
XEON - Persistent clap trigger.
Two claps launch XEON. Three claps close XEON.
"""

import json
import os
import subprocess
import time

import numpy as np
import sounddevice as sd


CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config.json")
with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
    config = json.load(f)

WORKSPACE_PATH = config["workspace_path"]
LAUNCH_SCRIPT = os.path.join(WORKSPACE_PATH, "scripts", "launch-session.ps1")
CLOSE_SCRIPT = os.path.join(WORKSPACE_PATH, "scripts", "close-session.ps1")

SAMPLE_RATE = 44100
BLOCK_SIZE = 1024
THRESHOLD = 0.10
MIN_GAP = 0.1
MAX_GAP = 1.5
DOUBLE_WAIT = 0.8
COOLDOWN = 4.0

claps: list[float] = []
pending_double_time = 0.0
last_trigger_time = 0.0


def run_script(path: str):
    subprocess.Popen(["powershell", "-ExecutionPolicy", "Bypass", "-File", path])


def fire_launch():
    print("[xeon] Double clap detected. Launching session.", flush=True)
    run_script(LAUNCH_SCRIPT)


def fire_close():
    print("[xeon] Triple clap detected. Closing session.", flush=True)
    run_script(CLOSE_SCRIPT)


def audio_callback(indata, frames, time_info, status):
    global claps, pending_double_time, last_trigger_time

    now = time.time()
    if now - last_trigger_time < COOLDOWN:
        return

    rms = float(np.sqrt(np.mean(indata**2)))
    if rms <= THRESHOLD:
        return

    if claps and now - claps[-1] < MIN_GAP:
        return

    claps = [t for t in claps if now - t <= MAX_GAP]
    claps.append(now)
    print(f"[xeon] Clap {len(claps)} detected (rms={rms:.3f})", flush=True)

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
    print("[xeon] Listening: double clap launches, triple clap closes.", flush=True)
    while True:
        now = time.time()
        if pending_double_time and now >= pending_double_time:
            fire_launch()
            claps = []
            pending_double_time = 0.0
            last_trigger_time = now
        time.sleep(0.05)
