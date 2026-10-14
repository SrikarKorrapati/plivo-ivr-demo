"""
Tests for the whole IVR, without a phone or Plivo credit.

Most tests "make a call" with the PhoneSimulator from simulate.py: it plays
Plivo's part, follows our XML, and presses the keys we give it.
Run with:  pytest -v
"""
import xml.etree.ElementTree as ET

import plivo
import pytest
from plivo.base import ResponseObject
from plivo.utils.signature_v3 import construct_post_url, get_signature_v3

import config
import timeline
from app import app
from prompts import PROMPTS
from simulate import PhoneSimulator

PUBLIC = "https://test-ivr-demo.trycloudflare.com"
EN, ES = PROMPTS["en"], PROMPTS["es"]


class FakePlivo:
    """Stands in for plivo.RestClient so no test ever places a real call."""
    created = []
    error = None

    def __init__(self, auth_id, auth_token, timeout=None):
        self.calls = self

    def create(self, **kwargs):
        if FakePlivo.error:
            raise FakePlivo.error
        FakePlivo.created.append(kwargs)
        return ResponseObject({"api_id": "a1", "message": "call fired", "request_uuid": "req-123"})


@pytest.fixture(autouse=True)
def test_settings(monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_URL", PUBLIC)
    monkeypatch.setattr(config, "VALIDATE_SIGNATURES", False)
    monkeypatch.setattr(config, "PLIVO_AUTH_ID", "MATESTAUTHID00000000")
    monkeypatch.setattr(config, "PLIVO_AUTH_TOKEN", "test-auth-token")
    monkeypatch.setattr(config, "PLIVO_NUMBER", "+918035454161")
    monkeypatch.setattr(config, "ASSOCIATE_NUMBER", "+912264236412")
    monkeypatch.setattr(config, "AUDIO_URL", "")
    monkeypatch.setattr(config, "TARGET_NUMBER", "")
    monkeypatch.setattr(timeline, "ECHO", False)
    monkeypatch.setattr(plivo, "RestClient", FakePlivo)
    FakePlivo.created, FakePlivo.error = [], None


@pytest.fixture
def client():
    return app.test_client()


def make_call(client, keys, associate_answers=True):
    """Simulate a whole call. `keys` are pressed in order; "" means silence."""
    keys = iter(keys)
    simulator = PhoneSimulator(client, press=lambda n: next(keys), show=lambda line: None,
                               associate_answers=associate_answers)
    return simulator.run()


def said(heard):
    return [text for kind, text in heard if kind == "bot"]


def post_xml(client, path, **form):
    response = client.post(path, data={"CallUUID": "test-call", **form})
    assert response.status_code == 200
    assert response.mimetype == "application/xml"
    return ET.fromstring(response.data)


# ---------------------------------------------------------------- full calls

def test_wrong_otp_then_spanish_audio_then_associate(client):
    heard = make_call(client, ["1111", "1204", "2", "1", "2"])
    speech = said(heard)
    assert speech[0] == EN["welcome"]
    assert EN["otp_wrong"] in speech
    assert speech.index(EN["otp_wrong"]) < speech.index(EN["otp_ok"])
    assert ES["menu_ask"] in speech
    assert ("audio", "plays jingle.mp3") in heard
    assert ES["connecting"] in speech
    assert ("dial", "forwarding to +912264236412") in heard
    assert speech[-1] == ES["goodbye"]
    assert heard[-1] == ("call", "hangs up")


def test_otp_is_asked_again_until_correct(client):
    heard = make_call(client, ["0000", "9999", "3105", "1204", "1", "2"])
    assert said(heard).count(EN["otp_wrong"]) == 3
    assert EN["otp_ok"] in said(heard)


def test_menu_is_only_reachable_after_the_right_otp(client):
    speech = said(make_call(client, ["0000", "", "", ""]))
    assert EN["menu_ask"] not in speech
    assert EN["language_ask"] not in speech
    assert speech[-1] == EN["silent_goodbye"]


def test_english_audio_returns_to_menu_and_9_goes_back(client):
    heard = make_call(client, ["1204", "1", "1", "9", "2", "2"])
    speech = said(heard)
    assert speech.count(EN["menu_ask"]) == 2          # menu repeated after the audio
    assert speech.count(EN["language_ask"]) == 2      # 9 went back to level 1
    assert ES["connecting"] in speech                 # then Spanish was chosen


def test_associate_not_answering_goes_back_to_menu(client):
    speech = said(make_call(client, ["1204", "1", "2", "", "", ""], associate_answers=False))
    assert EN["associate_unavailable"] in speech
    assert speech.index(EN["associate_unavailable"]) < len(speech) - 1
    assert speech[-1] == EN["silent_goodbye"]


# ------------------------------------------------------------ invalid input

def test_short_otp_is_explained_and_asked_again(client):
    speech = said(make_call(client, ["12", "1204", "1", "2"]))
    assert EN["otp_too_short"] in speech
    assert EN["otp_ok"] in speech


def test_otp_with_star_or_hash_counts_as_wrong(client):
    speech = said(make_call(client, ["12*4", "1204", "1", "2"]))
    assert EN["otp_wrong"] in speech


def test_invalid_key_at_level_1_repeats_level_1(client):
    speech = said(make_call(client, ["1204", "5", "*", "1", "2"]))
    assert speech.count(EN["invalid"]) == 2
    assert speech.count(EN["language_ask"]) == 3


def test_invalid_key_at_level_2_repeats_level_2_in_the_chosen_language(client):
    speech = said(make_call(client, ["1204", "2", "7", "#", "2"]))
    assert speech.count(ES["invalid"]) == 2
    assert speech.count(ES["menu_ask"]) == 3


def test_silence_repeats_the_question_then_hangs_up_after_three(client):
    heard = make_call(client, ["", "", ""])
    speech = said(heard)
    assert speech.count(EN["otp_ask"]) == 3
    assert speech.count(EN["no_input"]) == 3
    assert speech[-1] == EN["silent_goodbye"]
    assert heard[-1] == ("call", "hangs up")


def test_pressing_a_key_resets_the_silence_counter(client):
    speech = said(make_call(client, ["", "", "0000", "", "", "1204", "1", "2"]))
    assert EN["silent_goodbye"] not in speech
    assert EN["otp_ok"] in speech


def test_silence_in_spanish_menu_is_handled_in_spanish(client):
    speech = said(make_call(client, ["1204", "2", "", "", ""]))
    assert speech.count(ES["no_input"]) == 3
    assert speech[-1] == ES["silent_goodbye"]


def test_empty_digits_posted_to_a_check_endpoint_asks_again(client):
    for path, prompt in [("/otp/check", EN["no_input"]), ("/language/check", EN["no_input"]),
                         ("/menu/check?lang=es", ES["no_input"])]:
        xml = post_xml(client, path, Digits="")
        assert xml.find("Speak").text == prompt
        assert xml.find("Redirect") is not None


def test_unknown_language_in_url_falls_back_to_english(client):
    xml = post_xml(client, "/menu/ask?lang=fr")
    assert xml.find("GetDigits/Speak").text == EN["menu_ask"]


def test_garbage_silence_counter_is_ignored(client):
    xml = post_xml(client, "/otp/ask?silence=abc")
    assert xml.find("GetDigits") is not None


# ------------------------------------------------------- XML details Plivo sees

def test_otp_question_xml(client):
    xml = post_xml(client, "/otp/ask")
    get_digits = xml.find("GetDigits")
    assert get_digits.get("action") == f"{PUBLIC}/otp/check"
    assert get_digits.get("method") == "POST"
    assert get_digits.get("numDigits") == "4"
    assert get_digits.find("Speak").text == EN["otp_ask"]
    assert xml.find("Redirect").text == f"{PUBLIC}/otp/ask?silence=1"


def test_otp_digits_are_kept_out_of_plivo_logs(client):
    assert post_xml(client, "/otp/ask").find("GetDigits").get("log") == "false"
    assert post_xml(client, "/menu/ask?lang=en").find("GetDigits").get("log") == "true"


def test_urls_with_two_parameters_are_sorted(client):
    # Plivo's signature check sorts query parameters, so we send them sorted already.
    xml = post_xml(client, "/menu/ask?lang=es")
    assert xml.find("Redirect").text == f"{PUBLIC}/menu/ask?lang=es&silence=1"


def test_signature_header_with_spaces_after_commas_is_accepted(client, monkeypatch):
    monkeypatch.setattr(config, "VALIDATE_SIGNATURES", True)
    form = {"CallUUID": "u1"}
    good = get_signature_v3(b"test-auth-token", construct_post_url(PUBLIC + "/answer", dict(form)).decode(),
                            b"42").decode()
    response = client.post("/answer", data=form, headers={
        "X-Plivo-Signature-V3": f"c29tZW90aGVydG9rZW4=, {good}", "X-Plivo-Signature-V3-Nonce": "42"})
    assert response.status_code == 200


def test_language_question_speaks_each_option_in_its_own_language(client):
    speaks = post_xml(client, "/language/ask").findall("GetDigits/Speak")
    assert [(s.text, s.get("language")) for s in speaks] == [
        (EN["language_ask"], "en-US"), (ES["language_ask"], "es-ES")]


def test_spanish_menu_xml(client):
    xml = post_xml(client, "/menu/ask?lang=es")
    get_digits = xml.find("GetDigits")
    assert get_digits.get("action") == f"{PUBLIC}/menu/check?lang=es"
    assert get_digits.get("numDigits") == "1"
    speak = get_digits.find("Speak")
    assert speak.text == ES["menu_ask"]
    assert speak.get("language") == "es-ES"


def test_audio_option_plays_the_mp3_then_returns_to_menu(client):
    xml = post_xml(client, "/menu/check?lang=en", Digits="1")
    assert [child.tag for child in xml] == ["Speak", "Play", "Redirect"]
    assert xml.find("Play").text == f"{PUBLIC}/static/audio/jingle.mp3"
    assert xml.find("Redirect").text == f"{PUBLIC}/menu/ask?lang=en"


def test_audio_url_can_be_overridden(client, monkeypatch):
    monkeypatch.setattr(config, "AUDIO_URL", "https://s3.amazonaws.com/plivocloud/Trumpet.mp3")
    xml = post_xml(client, "/menu/check?lang=en", Digits="1")
    assert xml.find("Play").text == "https://s3.amazonaws.com/plivocloud/Trumpet.mp3"


def test_associate_option_dials_with_our_caller_id(client):
    xml = post_xml(client, "/menu/check?lang=es", Digits="2")
    dial = xml.find("Dial")
    assert dial.get("callerId") == "+918035454161"
    assert dial.get("action") == f"{PUBLIC}/dial/status?lang=es"
    assert dial.find("Number").text == "+912264236412"


@pytest.mark.parametrize("status", ["busy", "no-answer", "failed", "timeout", "cancel"])
def test_associate_unreachable_statuses(client, status):
    xml = post_xml(client, "/dial/status?lang=en", DialStatus=status)
    assert xml.find("Speak").text == EN["associate_unavailable"]
    assert xml.find("Redirect").text == f"{PUBLIC}/menu/ask?lang=en"


def test_jingle_is_served_publicly(client):
    response = client.get("/static/audio/jingle.mp3", headers={"Cf-Connecting-Ip": "1.2.3.4"})
    assert response.status_code == 200
    assert response.mimetype in ("audio/mpeg", "audio/mp3")


def test_otp_digits_are_never_logged(client):
    make_call(client, ["4321", "1204", "1", "2"])
    texts = " ".join(event["text"] for event in timeline.since(0))
    assert "4321" not in texts and "1204" not in texts


# --------------------------------------------------------- Plivo signatures

def signed_post(client, path, form, token="test-auth-token", nonce="12345"):
    signature = get_signature_v3(token.encode(), construct_post_url(PUBLIC + path, dict(form)).decode(),
                                 nonce.encode()).decode()
    return client.post(path, data=form, headers={"X-Plivo-Signature-V3": signature,
                                                  "X-Plivo-Signature-V3-Nonce": nonce})


def test_signed_request_from_plivo_is_accepted(client, monkeypatch):
    monkeypatch.setattr(config, "VALIDATE_SIGNATURES", True)
    response = signed_post(client, "/menu/check?lang=es", {"CallUUID": "u1", "Digits": "1"})
    assert response.status_code == 200


def test_unsigned_request_is_rejected(client, monkeypatch):
    monkeypatch.setattr(config, "VALIDATE_SIGNATURES", True)
    assert client.post("/answer", data={"CallUUID": "u1"}).status_code == 403


def test_request_signed_with_another_token_is_rejected(client, monkeypatch):
    monkeypatch.setattr(config, "VALIDATE_SIGNATURES", True)
    response = signed_post(client, "/otp/check", {"CallUUID": "u1", "Digits": "1204"}, token="wrong")
    assert response.status_code == 403


def test_tampered_digits_are_rejected(client, monkeypatch):
    monkeypatch.setattr(config, "VALIDATE_SIGNATURES", True)
    nonce = "999"
    good = get_signature_v3(b"test-auth-token",
                            construct_post_url(PUBLIC + "/otp/check", {"CallUUID": "u1", "Digits": "0000"}).decode(),
                            nonce.encode()).decode()
    response = client.post("/otp/check", data={"CallUUID": "u1", "Digits": "1204"},
                           headers={"X-Plivo-Signature-V3": good, "X-Plivo-Signature-V3-Nonce": nonce})
    assert response.status_code == 403


# ------------------------------------------------------ dashboard + call API

def test_call_api_places_the_outbound_call(client):
    response = client.post("/api/call", json={"to": "+91 98765 43210"})
    assert response.get_json() == {"ok": True, "to": "+919876543210", "request_uuid": "req-123"}
    call = FakePlivo.created[0]
    assert call["from_"] == "918035454161"
    assert call["to_"] == "919876543210"
    assert call["answer_url"] == f"{PUBLIC}/answer"
    assert call["answer_method"] == "POST"
    assert call["hangup_url"] == f"{PUBLIC}/hangup"
    assert call["ring_url"] == f"{PUBLIC}/ringing"


def test_call_api_uses_target_number_from_config(client, monkeypatch):
    monkeypatch.setattr(config, "TARGET_NUMBER", "+919876543210")
    assert client.post("/api/call", json={}).get_json()["to"] == "+919876543210"


@pytest.mark.parametrize("bad", ["", "9876543210", "+91abc", "+0123456789", "12"])
def test_call_api_rejects_bad_numbers(client, bad):
    response = client.post("/api/call", json={"to": bad})
    assert response.status_code == 400
    assert FakePlivo.created == []


def test_call_api_needs_a_public_url(client, monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_URL", "")
    response = client.post("/api/call", json={"to": "+919876543210"})
    assert response.status_code == 500
    assert FakePlivo.created == []


def test_call_api_reports_plivo_errors(client):
    FakePlivo.error = plivo.exceptions.ValidationError("to_ is not a valid phone number")
    response = client.post("/api/call", json={"to": "+919876543210"})
    assert response.status_code == 502
    assert "not a valid phone number" in response.get_json()["error"]


def test_dashboard_and_call_api_refuse_requests_through_the_tunnel(client):
    tunnel = {"Cf-Connecting-Ip": "203.0.113.9", "X-Forwarded-For": "203.0.113.9"}
    assert client.get("/", headers=tunnel).status_code == 403
    assert client.get("/api/events", headers=tunnel).status_code == 403
    assert client.post("/api/call", json={"to": "+919876543210"}, headers=tunnel).status_code == 403
    assert FakePlivo.created == []


def test_dashboard_opens_locally(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Call me" in response.data


def test_events_api_returns_only_new_events(client):
    first = timeline.add("first").get("id")
    timeline.add("second")
    events = client.get(f"/api/events?after={first}").get_json()["events"]
    assert [e["text"] for e in events][-1] == "second"
    assert all(e["id"] > first for e in events)


def test_call_api_reports_network_failures(client):
    import requests
    FakePlivo.error = requests.exceptions.ConnectionError("Failed to resolve api.plivo.com")
    response = client.post("/api/call", json={"to": "+919876543210"})
    assert response.status_code == 502
    assert response.get_json()["error"].startswith("Could not reach Plivo")


def test_call_api_refuses_a_localhost_public_url(client, monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_URL", "http://localhost:5050")
    assert client.post("/api/call", json={"to": "+919876543210"}).status_code == 500
    assert FakePlivo.created == []


def test_startup_credential_check_explains_each_failure(monkeypatch):
    import requests
    import app as app_module

    class Account:
        def __init__(self, error):
            self.error = error

        def get(self):
            if self.error:
                raise self.error

    def client_raising(error):
        class Client:
            def __init__(self, *args, **kwargs):
                self.account = Account(error)
        return Client

    monkeypatch.setattr(plivo, "RestClient", client_raising(None))
    assert app_module.check_credentials() == "OK"
    monkeypatch.setattr(plivo, "RestClient", client_raising(plivo.exceptions.AuthenticationError("bad")))
    assert app_module.check_credentials().startswith("REJECTED")
    monkeypatch.setattr(plivo, "RestClient", client_raising(requests.exceptions.ConnectionError()))
    assert app_module.check_credentials().startswith("could not reach Plivo")
    monkeypatch.setattr(config, "PLIVO_AUTH_TOKEN", "")
    assert app_module.check_credentials().startswith("MISSING")


def test_hangup_callback_tolerates_missing_or_odd_fields(client):
    for form in [{}, {"Duration": "abc"}, {"Duration": "42", "HangupCauseName": "Normal Hangup"},
                 {"Duration": "0", "HangupCause": "NO_ANSWER"}]:
        assert client.post("/hangup", data=form).status_code == 200
    texts = [e["text"] for e in timeline.since(0)][-4:]
    assert texts[2] == "Call ended after 42s (Normal Hangup)"
    assert texts[3] == "Call was not answered (NO_ANSWER)"


def test_error_messages_never_show_the_auth_id(client):
    FakePlivo.error = plivo.exceptions.ResourceNotFoundError(
        "Resource at /v1/Account/MATESTAUTHID00000000/Call/ could not be found")
    response = client.post("/api/call", json={"to": "+919876543210"})
    assert "MATESTAUTHID00000000" not in response.get_json()["error"]
