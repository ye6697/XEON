"""Small Windows EXE launcher for XEON.

The executable lives next to server.py. It starts the existing backend from this
folder and opens XEON in a native WebView window, without bundling Whisper/Torch.
"""

import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path


HOST = "127.0.0.1"
PORT = 8340


def start_url() -> str:
    path = os.environ.get("XEON_START_PATH", "/")
    if not path.startswith("/"):
        path = "/" + path
    return f"http://{HOST}:{PORT}{path}"


def workspace_path() -> Path:
    configured = os.environ.get("XEON_WORKSPACE")
    if configured and (Path(configured) / "server.py").exists():
        return Path(configured)
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        if (exe_dir / "server.py").exists():
            return exe_dir
    source_dir = Path(__file__).resolve().parent
    if (source_dir / "server.py").exists():
        return source_dir
    bundled_workspace = Path(r"c:\Users\User\Downloads\jarvis-voice-assistant-master\jarvis-voice-assistant-master")
    if (bundled_workspace / "server.py").exists():
        return bundled_workspace
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else source_dir


def port_open() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex((HOST, PORT)) == 0


def python_executable() -> str:
    local_python = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python312" / "python.exe"
    return str(local_python) if local_python.exists() else "python"


def start_backend(root: Path):
    if port_open():
        return None
    server_path = root / "server.py"
    if not server_path.exists():
        raise FileNotFoundError(f"server.py nicht gefunden neben XEON.exe: {server_path}")
    log = root / "xeon-server.log"
    err = root / "xeon-server.err.log"
    return subprocess.Popen(
        [python_executable(), str(server_path)],
        cwd=str(root),
        stdout=log.open("a", encoding="utf-8"),
        stderr=err.open("a", encoding="utf-8"),
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def wait_for_backend(seconds: int = 12):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if port_open():
            return True
        time.sleep(0.35)
    return False


def open_window():
    try:
        import webview

        start_path = os.environ.get("XEON_START_PATH", "/")
        intro_mode = start_path.startswith("/intro")
        focus_guard_mode = "focus_guard=1" in start_path
        fullscreen_mode = intro_mode or focus_guard_mode
        if fullscreen_mode:
            existing_args = os.environ.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "")
            autoplay_arg = "--autoplay-policy=no-user-gesture-required"
            if autoplay_arg not in existing_args:
                os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"{existing_args} {autoplay_arg}".strip()
        webview.create_window(
            "XEON",
            start_url(),
            width=980,
            height=760,
            min_size=(420, 620),
            fullscreen=fullscreen_mode,
        )
        webview.start()
    except Exception as exc:
        print(f"[xeon-launcher] WebView nicht verfuegbar, Browser-Fallback: {exc}", flush=True)
        webbrowser.open(start_url())


def main():
    root = workspace_path()
    start_backend(root)
    if not wait_for_backend():
        raise RuntimeError("XEON Backend ist nicht auf Port 8340 erreichbar. Siehe xeon-server.err.log.")
    open_window()


if __name__ == "__main__":
    main()
