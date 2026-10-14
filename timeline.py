"""
A small in-memory log of what happens during calls.

Every IVR step adds an event here. The dashboard polls /api/events once a
second and draws them as a live timeline, so you can watch the call move
through the menus. It lives in memory on purpose: restart the app and the
timeline starts empty.
"""
import itertools
import threading
from datetime import datetime

MAX_EVENTS = 500
ECHO = True  # also print each event in the terminal

_events = []
_ids = itertools.count(1)
_lock = threading.Lock()


def add(text, stage=None, level="info", call=None, endpoint=None, xml=None, step_label=None):
    """Record one event.

    stage      -> which step of the dashboard's progress bar this belongs to
    level      -> "info", "ok", "warn" or "err" (the colour of the dot)
    step_label -> optional new label for that step, e.g. "Spanish"
    """
    event = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "text": text,
        "stage": stage,
        "level": level,
        "call": call[:8] if call else None,
        "endpoint": endpoint,
        "xml": xml,
        "step_label": step_label,
    }
    with _lock:
        event["id"] = next(_ids)
        _events.append(event)
        del _events[:-MAX_EVENTS]
    if ECHO:
        print(f"[{event['time']}] {text}", flush=True)
    return event


def since(event_id):
    """All events newer than event_id (the dashboard asks for what it hasn't seen yet)."""
    with _lock:
        return [e for e in _events if e["id"] > event_id]
