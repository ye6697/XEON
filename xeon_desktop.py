"""Native desktop launcher for XEON.

This starts the existing FastAPI backend in-process and opens the XEON UI in a
Windows WebView window. Build it with scripts/build-xeon-exe.ps1.
"""

import threading
import time
import webbrowser

import uvicorn


HOST = "127.0.0.1"
PORT = 8340
URL = f"http://{HOST}:{PORT}/?v=model-spend-3"


def run_server():
    import server

    uvicorn.run(server.app, host=HOST, port=PORT, log_level="info")


def main():
    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    time.sleep(2)
    try:
        import webview

        window = webview.create_window("XEON", URL, width=980, height=760, min_size=(420, 620))
        webview.start()
        return
    except Exception as exc:
        print(f"[xeon-desktop] WebView unavailable, opening browser instead: {exc}", flush=True)

    webbrowser.open(URL)
    while thread.is_alive():
        time.sleep(1)


if __name__ == "__main__":
    main()