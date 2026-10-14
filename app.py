"""
InspireWorks IVR demo: the web app.

    python app.py      then open http://localhost:5050

This file holds the dashboard and the "Call me" API that asks Plivo to place
the outbound call. The call flow itself (OTP, menus, audio, forwarding) is
in ivr.py.
"""
import re
import socket
from functools import wraps

import plivo
from flask import Flask, abort, jsonify, render_template, request

import config
import timeline
import tunnel
from ivr import ivr, url

app = Flask(__name__)
app.register_blueprint(ivr)

state = {"credentials": None, "tunnel_error": None}  # filled in at startup


# --------------------------------------------------------------------------
# The dashboard only opens on this computer
# --------------------------------------------------------------------------

def local_only(view):
    """The public tunnel exposes this server to the internet, and "Call me"
    spends Plivo credit. So the dashboard and its APIs only answer requests
    made on this computer, never requests that came in through the tunnel."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        through_tunnel = "Cf-Connecting-Ip" in request.headers or "X-Forwarded-For" in request.headers
        if through_tunnel or request.remote_addr not in ("127.0.0.1", "::1"):
            abort(403, "The dashboard only opens on the computer running the app "
                       f"(http://localhost:{config.PORT}).")
        return view(*args, **kwargs)
    return wrapper


@app.route("/")
@local_only
def dashboard():
    return render_template(
        "index.html",
        public_url=config.PUBLIC_URL,
        tunnel_error=state["tunnel_error"],
        credentials_ok=state["credentials"] in (None, "OK") and bool(
            config.PLIVO_AUTH_ID and config.PLIVO_AUTH_TOKEN),
        plivo_number=config.PLIVO_NUMBER,
        target_number=config.TARGET_NUMBER,
    )


@app.route("/api/events")
@local_only
def events():
    return jsonify(events=timeline.since(request.args.get("after", 0, type=int)))


@app.route("/health")
def health():
    return "ok"


# --------------------------------------------------------------------------
# Start the outbound call
# --------------------------------------------------------------------------

def is_public(address):
    """Plivo must be able to reach the address: http(s), and not this laptop's localhost."""
    return (address.startswith(("https://", "http://"))
            and not re.search(r"//(localhost|127\.0\.0\.1|0\.0\.0\.0)\b", address))


def clean_number(raw):
    """'+91 98765-43210' -> '+919876543210'. None if it isn't an international number."""
    number = re.sub(r"[\s\-().]", "", raw or "")
    if number.startswith("00"):
        number = "+" + number[2:]
    return number if re.fullmatch(r"\+[1-9]\d{7,14}", number) else None


@app.route("/api/call", methods=["POST"])
@local_only
def start_call():
    data = request.get_json(silent=True) or request.form
    to = clean_number(data.get("to") or config.TARGET_NUMBER)

    if not to:
        return jsonify(ok=False, error="Please enter the number in international format, "
                                       "for example +919876543210."), 400
    if not (config.PLIVO_AUTH_ID and config.PLIVO_AUTH_TOKEN):
        return jsonify(ok=False, error="Plivo credentials are missing. "
                                       "Add PLIVO_AUTH_ID and PLIVO_AUTH_TOKEN to .env."), 500
    if not is_public(config.PUBLIC_URL):
        return jsonify(ok=False, error="There is no public URL, so Plivo couldn't reach "
                                       "this app. See the red banner at the top."), 500

    try:
        client = plivo.RestClient(config.PLIVO_AUTH_ID, config.PLIVO_AUTH_TOKEN, timeout=15)
        response = client.calls.create(
            from_=config.PLIVO_NUMBER.lstrip("+"),
            to_=to.lstrip("+"),
            answer_url=url("/answer"),    # Plivo asks this URL what to do once the call is answered
            answer_method="POST",
            ring_url=url("/ringing"),     # ...tells us when the phone starts ringing
            hangup_url=url("/hangup"),    # ...and when the call ends
            ring_timeout=45,              # give up if nobody answers within 45 seconds
            time_limit=900,               # safety net: no call lasts longer than 15 minutes
        )
    except plivo.exceptions.AuthenticationError:
        message = "Plivo rejected the Auth ID / Auth Token. Check them in .env."
    except plivo.exceptions.PlivoRestError as error:
        message = f"Plivo refused the call: {error}"
    except Exception as error:  # network trouble, DNS, ...
        message = f"Could not reach Plivo: {error}"
    else:
        timeline.add(f"Calling {to} from {config.PLIVO_NUMBER}", stage="calling",
                     call=response.request_uuid, endpoint="/api/call")
        return jsonify(ok=True, to=to, request_uuid=response.request_uuid)

    timeline.add(message, stage="calling", level="err", endpoint="/api/call")
    return jsonify(ok=False, error=message), 502


# --------------------------------------------------------------------------
# Run it
# --------------------------------------------------------------------------

def check_credentials():
    """One read-only API request, so a wrong Auth ID/Token shows up at startup."""
    if not (config.PLIVO_AUTH_ID and config.PLIVO_AUTH_TOKEN):
        return "MISSING: add PLIVO_AUTH_ID and PLIVO_AUTH_TOKEN to .env"
    try:
        plivo.RestClient(config.PLIVO_AUTH_ID, config.PLIVO_AUTH_TOKEN, timeout=15).account.get()
        return "OK"
    except plivo.exceptions.AuthenticationError:
        return "REJECTED by Plivo: check the Auth ID / Auth Token in .env"
    except Exception as error:
        return f"could not reach Plivo to check them ({type(error).__name__})"


def port_is_free(port):
    with socket.socket() as probe:
        return probe.connect_ex(("127.0.0.1", port)) != 0


if __name__ == "__main__":
    if not port_is_free(config.PORT):
        raise SystemExit(f"Port {config.PORT} is already in use (is the app already running?). "
                         "Stop the other program, or set PORT=5051 in .env.")
    state["credentials"] = check_credentials()
    if not config.PUBLIC_URL:
        print("Opening a Cloudflare tunnel so Plivo can reach this app...")
        try:
            config.PUBLIC_URL = tunnel.start(config.PORT)
        except RuntimeError as error:
            state["tunnel_error"] = str(error)

    print()
    print("  InspireWorks IVR demo")
    print(f"  Dashboard (open this):  http://localhost:{config.PORT}")
    print(f"  Public URL for Plivo:   {config.PUBLIC_URL or 'none: ' + str(state['tunnel_error'])}")
    print(f"  Plivo credentials:      {state['credentials']}")
    print()
    app.run(host="127.0.0.1", port=config.PORT, threaded=True)
