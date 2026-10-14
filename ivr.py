"""
The phone call itself: every step of the IVR, top to bottom.

How a Plivo call works
----------------------
When the phone is answered, Plivo sends an HTTP request to our answer URL and
we reply with Plivo XML: a short script such as "<Speak> this, then
<GetDigits> (wait for keys)". When the caller presses keys, Plivo sends them
as "Digits" to the `action` URL written in that <GetDigits>, and we reply with
the next piece of XML. That loop is the whole IVR.

Each question therefore has two endpoints:

    /<step>/ask    asks the question (Speak inside GetDigits)
    /<step>/check  reads the keys, then moves forward or asks again

The flow:

    /answer -> /otp/ask <-> /otp/check            (re-asks until the OTP is right)
            -> /language/ask <-> /language/check  (1 English, 2 Spanish)
            -> /menu/ask <-> /menu/check          (1 audio, 2 associate, 9 back)

Wrong keys, or no keys at all, never end the call: the bot says what went
wrong and repeats the current question. Only after three silent prompts in a
row does it say goodbye, so a forgotten call doesn't run forever.
"""
from urllib.parse import urlencode
from xml.dom import minidom

import plivo
from flask import Blueprint, Response, abort, request
from plivo import plivoxml

import config
import timeline
from prompts import LANGUAGE_NAMES, PROMPTS, VOICES

ivr = Blueprint("ivr", __name__)

MAX_SILENT_PROMPTS = 3  # hang up after this many prompts in a row with no key pressed


# --------------------------------------------------------------------------
# Small helpers that build Plivo XML
# --------------------------------------------------------------------------

def url(path, **params):
    """Full public URL of one of our endpoints (Plivo needs absolute URLs).
    Query parameters are sorted, which is also how Plivo's signature check sees them."""
    query = "?" + urlencode(sorted(params.items())) if params else ""
    return f"{config.PUBLIC_URL}{path}{query}"


def say(lang, key):
    """A <Speak> element: Plivo's text-to-speech reads one of our prompts."""
    return plivoxml.SpeakElement(PROMPTS[lang][key], **VOICES[lang])


def ask(step, speeches, num_digits, lang=None, silence=0, secret=False):
    """Ask a question and wait for keys.

    The speeches play inside <GetDigits>, so the caller can press a key at
    any time. If nobody presses anything, Plivo moves on to the elements
    after <GetDigits>: we say so and come back to the same question.
    """
    lang_param = {"lang": lang} if lang else {}
    response = plivoxml.ResponseElement()
    get_digits = plivoxml.GetDigitsElement(
        action=url(f"/{step}/check", **lang_param),
        method="POST",
        num_digits=num_digits,
        timeout=7,         # seconds to wait for the first key after the prompt
        digit_timeout=4,   # seconds to wait between keys (matters for the 4-digit OTP)
        retries=1,         # one attempt; we handle repeats ourselves, below
        log=not secret,    # keep OTP digits out of Plivo's debug logs
    )
    for speech in speeches:
        get_digits.add(speech)
    response.add(get_digits)
    # Reached only when the caller pressed nothing:
    response.add(say(lang or "en", "no_input"))
    response.add(plivoxml.RedirectElement(
        url(f"/{step}/ask", silence=silence + 1, **lang_param), method="POST"))
    return response


def go_to(path, *speeches, **params):
    """Optionally say something, then continue at another step."""
    response = plivoxml.ResponseElement()
    for speech in speeches:
        response.add(speech)
    response.add(plivoxml.RedirectElement(url(path, **params), method="POST"))
    return response


def goodbye(lang, key="goodbye"):
    response = plivoxml.ResponseElement()
    response.add(say(lang, key))
    response.add(plivoxml.HangupElement())
    return response


def reply(response, text, stage, level="info", step_label=None):
    """Send the XML back to Plivo, and log the step for the live dashboard."""
    xml = response.to_string(pretty=False)
    timeline.add(text, stage=stage, level=level, call=request.values.get("CallUUID"),
                 endpoint=request.path, xml=pretty(xml), step_label=step_label)
    return Response(xml, mimetype="application/xml")


def pretty(xml):
    return minidom.parseString(xml).toprettyxml(indent="  ").split("\n", 1)[1].strip()


def current_lang():
    """The language chosen at Level 1 travels in the URL (?lang=es)."""
    lang = request.args.get("lang", "en")
    return lang if lang in PROMPTS else "en"


def pressed():
    """The keys the caller pressed (Plivo sends them as "Digits")."""
    return request.values.get("Digits", "").strip()


def silent_count():
    return request.args.get("silence", 0, type=int)


# --------------------------------------------------------------------------
# Only Plivo may call these endpoints
# --------------------------------------------------------------------------

@ivr.before_request
def check_plivo_signature():
    """Every request from Plivo is signed with our Auth Token (X-Plivo-Signature-V3).
    Anything without a valid signature is rejected, so nobody else can drive the IVR."""
    if not config.VALIDATE_SIGNATURES:
        return
    signature = request.headers.get("X-Plivo-Signature-V3", "").replace(" ", "")
    nonce = request.headers.get("X-Plivo-Signature-V3-Nonce", "")
    # Plivo signed the public URL it called, not the localhost URL Flask sees.
    signed_url = config.PUBLIC_URL + request.full_path.rstrip("?")
    params = request.form.to_dict() if request.method == "POST" else {}
    try:
        valid = signature and nonce and plivo.utils.validate_v3_signature(
            request.method, signed_url, nonce, config.PLIVO_AUTH_TOKEN, signature, params)
    except Exception:
        valid = False
    if not valid:
        timeline.add(f"Rejected a request to {request.path}: missing or invalid Plivo signature",
                     level="err", endpoint=request.path)
        abort(403)


# --------------------------------------------------------------------------
# Call status callbacks (Plivo tells us; no XML needed back)
# --------------------------------------------------------------------------

@ivr.route("/ringing", methods=["POST"])
def ringing():
    timeline.add("Phone is ringing", stage="ringing", call=request.values.get("CallUUID"),
                 endpoint=request.path)
    return ""


@ivr.route("/hangup", methods=["POST"])
def hangup():
    cause = request.values.get("HangupCauseName") or request.values.get("HangupCause") or "unknown"
    seconds = request.values.get("Duration", "0")
    answered = bool(request.values.get("AnswerTime")) or (seconds.isdigit() and int(seconds) > 0)
    timeline.add(f"Call ended after {seconds}s ({cause})" if answered
                 else f"Call was not answered ({cause})",
                 stage="ended", level="info" if answered else "warn",
                 call=request.values.get("CallUUID"), endpoint=request.path)
    return ""


# --------------------------------------------------------------------------
# Step 0: the call is answered
# --------------------------------------------------------------------------

@ivr.route("/answer", methods=["POST"])
def answer():
    response = go_to("/otp/ask", say("en", "welcome"))
    return reply(response, "Call answered: greeting the caller", stage="answered")


# --------------------------------------------------------------------------
# Step 1: OTP check (re-asks until the right code is entered)
# --------------------------------------------------------------------------

@ivr.route("/otp/ask", methods=["POST"])
def otp_ask():
    silence = silent_count()
    if silence >= MAX_SILENT_PROMPTS:
        return reply(goodbye("en", "silent_goodbye"), "No keys pressed 3 times: hanging up",
                     stage="otp", level="warn")
    response = ask("otp", [say("en", "otp_ask")], num_digits=4, silence=silence, secret=True)
    note = "Asking for the 4-digit OTP" + (" again (no keys heard)" if silence else "")
    return reply(response, note, stage="otp")


@ivr.route("/otp/check", methods=["POST"])
def otp_check():
    digits = pressed()
    if digits == config.OTP:
        return reply(go_to("/language/ask", say("en", "otp_ok")),
                     "OTP correct: caller verified", stage="otp", level="ok", step_label="Verified")
    if not digits:
        return reply(go_to("/otp/ask", say("en", "no_input")),
                     "No OTP entered: asking again", stage="otp", level="warn")
    if len(digits) < 4:
        return reply(go_to("/otp/ask", say("en", "otp_too_short")),
                     f"Only {len(digits)} digit(s) entered: asking again", stage="otp", level="warn")
    # The digits themselves are never logged: an OTP is a secret.
    return reply(go_to("/otp/ask", say("en", "otp_wrong")),
                 "Wrong OTP: asking again", stage="otp", level="err")


# --------------------------------------------------------------------------
# Step 2 (IVR level 1): choose a language
# --------------------------------------------------------------------------

@ivr.route("/language/ask", methods=["POST"])
def language_ask():
    silence = silent_count()
    if silence >= MAX_SILENT_PROMPTS:
        return reply(goodbye("en", "silent_goodbye"), "No keys pressed 3 times: hanging up",
                     stage="language", level="warn")
    # "For English, press 1" in an English voice, "Para español, presione 2" in a Spanish one
    response = ask("language", [say("en", "language_ask"), say("es", "language_ask")],
                   num_digits=1, silence=silence)
    note = "Level 1: asking for a language" + (" again (no keys heard)" if silence else "")
    return reply(response, note, stage="language")


@ivr.route("/language/check", methods=["POST"])
def language_check():
    choice = {"1": "en", "2": "es"}.get(pressed())
    if choice:
        name = LANGUAGE_NAMES[choice]
        return reply(go_to("/menu/ask", lang=choice), f"Caller chose {name}",
                     stage="language", level="ok", step_label=name)
    if not pressed():
        return reply(go_to("/language/ask", say("en", "no_input")),
                     "No key pressed at Level 1: asking again", stage="language", level="warn")
    return reply(go_to("/language/ask", say("en", "invalid")),
                 f"Invalid key '{pressed()}' at Level 1: asking again", stage="language", level="warn")


# --------------------------------------------------------------------------
# Step 3 (IVR level 2): audio message, live associate, or back
# --------------------------------------------------------------------------

@ivr.route("/menu/ask", methods=["POST"])
def menu_ask():
    lang = current_lang()
    silence = silent_count()
    if silence >= MAX_SILENT_PROMPTS:
        return reply(goodbye(lang, "silent_goodbye"), "No keys pressed 3 times: hanging up",
                     stage="menu", level="warn")
    response = ask("menu", [say(lang, "menu_ask")], num_digits=1, lang=lang, silence=silence)
    note = f"Level 2 ({LANGUAGE_NAMES[lang]}): asking for an option" + (
        " again (no keys heard)" if silence else "")
    return reply(response, note, stage="menu")


@ivr.route("/menu/check", methods=["POST"])
def menu_check():
    lang = current_lang()
    choice = pressed()

    if choice == "1":
        # Play an MP3, then come back to this menu
        response = plivoxml.ResponseElement()
        response.add(say(lang, "audio_intro"))
        response.add(plivoxml.PlayElement(config.AUDIO_URL or url("/static/audio/jingle.mp3")))
        response.add(plivoxml.RedirectElement(url("/menu/ask", lang=lang), method="POST"))
        return reply(response, "Playing the audio message", stage="action", level="ok",
                     step_label="Audio")

    if choice == "2":
        # Forward the call. When the associate leg ends, Plivo calls /dial/status.
        response = plivoxml.ResponseElement()
        response.add(say(lang, "connecting"))
        dial = plivoxml.DialElement(
            action=url("/dial/status", lang=lang),
            method="POST",
            caller_id=config.PLIVO_NUMBER,
            timeout=30,  # seconds to let the associate's phone ring
        )
        dial.add(plivoxml.NumberElement(config.ASSOCIATE_NUMBER))
        response.add(dial)
        return reply(response, f"Forwarding the call to the associate ({config.ASSOCIATE_NUMBER})",
                     stage="action", level="ok", step_label="Associate")

    if choice == "9":
        return reply(go_to("/language/ask"), "Caller went back to Level 1", stage="language")

    if not choice:
        return reply(go_to("/menu/ask", say(lang, "no_input"), lang=lang),
                     "No key pressed at Level 2: asking again", stage="menu", level="warn")
    return reply(go_to("/menu/ask", say(lang, "invalid"), lang=lang),
                 f"Invalid key '{choice}' at Level 2: asking again", stage="menu", level="warn")


@ivr.route("/dial/status", methods=["POST"])
def dial_status():
    """Plivo calls this when the forwarded call ends (or never connected)."""
    lang = current_lang()
    status = request.values.get("DialStatus", "unknown")
    if status == "completed":
        return reply(goodbye(lang), "Associate call finished", stage="action", level="ok")
    # busy, no-answer, failed, timeout...: tell the caller and go back to the menu
    return reply(go_to("/menu/ask", say(lang, "associate_unavailable"), lang=lang),
                 f"Associate not reached ({status}): back to Level 2", stage="action", level="warn")
