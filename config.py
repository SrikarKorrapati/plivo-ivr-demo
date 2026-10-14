"""Settings for the IVR demo. Secrets come from the .env file (see .env.example)."""
import os

from dotenv import load_dotenv

load_dotenv()

# Plivo credentials: console.plivo.com -> Overview page (Auth ID / Auth Token)
PLIVO_AUTH_ID = os.getenv("PLIVO_AUTH_ID", "")
PLIVO_AUTH_TOKEN = os.getenv("PLIVO_AUTH_TOKEN", "")

# The Plivo number the call comes from (also the caller ID when we forward the call)
PLIVO_NUMBER = os.getenv("PLIVO_NUMBER", "+918035454161")

# Level 2, option 2 forwards the caller to this "live associate" number
ASSOCIATE_NUMBER = os.getenv("ASSOCIATE_NUMBER", "+912264236412")

# The phone to call (pre-filled on the dashboard; you can change it there)
TARGET_NUMBER = os.getenv("TARGET_NUMBER", "")

# Public https address of this server, so Plivo can fetch our XML.
# Leave empty and app.py opens a free Cloudflare tunnel and fills it in for you.
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")

try:
    PORT = int(os.getenv("PORT") or 5050)
except ValueError:
    raise SystemExit("PORT in .env must be a number, for example PORT=5050")

# The MP3 played for "press 1". Empty = our own static/audio/jingle.mp3.
AUDIO_URL = os.getenv("AUDIO_URL", "")

# Reject webhook requests that are not signed by Plivo (X-Plivo-Signature-V3).
VALIDATE_SIGNATURES = os.getenv("VALIDATE_SIGNATURES", "true").lower() != "false"

# The OTP is my birthdate in DDMM format: 12 April -> "1204".
# Hardcoded on purpose, as the assignment asks (no database needed).
OTP = "1204"
