"""
Opens a free Cloudflare "quick tunnel" so Plivo can reach this laptop.

Plivo needs a public https URL to fetch our XML from. `cloudflared tunnel --url`
gives us one (https://<random-words>.trycloudflare.com) without any account.
The URL changes every time the app starts. That's fine: we send it to Plivo
with every call we place.
"""
import atexit
import queue
import re
import shutil
import subprocess
import threading
import time

# https://some-random-words.trycloudflare.com (but not api.trycloudflare.com)
URL_PATTERN = re.compile(r"https://[a-z0-9]+(?:-[a-z0-9]+)+\.trycloudflare\.com")
READY_TEXT = "Registered tunnel connection"


def start(port, timeout=40):
    """Start cloudflared and return the public URL once the tunnel is connected."""
    exe = shutil.which("cloudflared")
    if not exe:
        raise RuntimeError("cloudflared is not installed. Run `brew install cloudflared`, "
                           "or put your own public URL in PUBLIC_URL in .env.")

    process = subprocess.Popen(
        [exe, "tunnel", "--url", f"http://localhost:{port}", "--no-autoupdate"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    atexit.register(process.terminate)  # close the tunnel when the app stops

    lines = queue.Queue()
    started = threading.Event()

    def read_log():
        # Keep reading cloudflared's output so it never blocks. After startup,
        # only errors are worth showing.
        for line in process.stdout:
            if not started.is_set():
                lines.put(line)
            elif " ERR " in line:
                print("[cloudflared]", line.strip(), flush=True)

    threading.Thread(target=read_log, daemon=True).start()

    url, ready = None, False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not (url and ready):
        try:
            line = lines.get(timeout=0.5)
        except queue.Empty:
            if process.poll() is not None:
                break  # cloudflared exited
            continue
        match = URL_PATTERN.search(line)
        if match:
            url = match.group(0)
        if READY_TEXT in line:
            ready = True
    started.set()

    if not url:
        process.terminate()
        raise RuntimeError("cloudflared did not hand out a public URL. "
                           "Check your internet connection, or set PUBLIC_URL in .env.")
    if not ready:
        print("Warning: the tunnel URL exists but cloudflared has not confirmed the connection yet.")
    return url
