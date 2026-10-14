"""
Try the IVR in your terminal: no phone, no tunnel, no Plivo credit used.

This script plays the part of Plivo. It sends the same webhook requests Plivo
would, reads the XML the app sends back, prints what the caller would hear,
and asks you which keys to press.

    python simulate.py
"""
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

import config
import timeline


class PhoneSimulator:
    """Follows our Plivo XML the way Plivo does: Speak, Play, GetDigits, Redirect, Dial, Hangup."""

    def __init__(self, client, press, show=print, associate_answers=True):
        self.client = client                        # Flask test client
        self.press = press                          # press(num_digits) -> keys ("" = silence)
        self.show = show
        self.associate_answers = associate_answers  # True, False, or a function asking you
        self.heard = []                             # (kind, text) in the order the caller heard it

    def run(self, max_steps=80):
        address, params = config.PUBLIC_URL + "/answer", {}
        for _ in range(max_steps):
            step = self.execute(self.request(address, params))
            if step is None:
                return self.heard
            address, params = step
        raise RuntimeError("The call never ended. Is there a loop in the IVR?")

    def request(self, address, params):
        parts = urlsplit(address)
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        data = {"CallUUID": "simulated-call", "From": config.PLIVO_NUMBER, "To": "+910000000000", **params}
        response = self.client.post(path, data=data)
        if response.status_code != 200:
            raise RuntimeError(f"{path} answered HTTP {response.status_code}")
        return ET.fromstring(response.data)

    def hear(self, kind, text):
        self.heard.append((kind, text))
        self.show(f"  {kind:>5} | {text}")

    def execute(self, xml):
        """Run one XML reply. Returns (next URL, params) or None when the call is over."""
        for element in xml:
            if element.tag == "Speak":
                self.hear("bot", element.text)
            elif element.tag == "Play":
                self.hear("audio", "plays " + element.text.rsplit("/", 1)[-1])
            elif element.tag == "GetDigits":
                for prompt in element:
                    self.hear("bot", prompt.text)
                keys = self.press(element.get("numDigits"))
                self.hear("keys", keys or "(nothing pressed)")
                if keys:
                    return element.get("action"), {"Digits": keys}
                # Nothing pressed: Plivo carries on with the elements after <GetDigits>.
            elif element.tag == "Redirect":
                return element.text, {}
            elif element.tag == "Dial":
                self.hear("dial", "forwarding to " + element.find("Number").text)
                answers = self.associate_answers
                answered = answers() if callable(answers) else answers
                return element.get("action"), {"DialStatus": "completed" if answered else "no-answer"}
            elif element.tag == "Hangup":
                self.hear("call", "hangs up")
                return None
        return None  # end of the XML: Plivo hangs up


def main():
    from app import app

    config.PUBLIC_URL = "https://simulator.local"
    config.VALIDATE_SIGNATURES = False
    timeline.ECHO = False

    print("Simulated call. Type the keys you'd press and hit Enter (just Enter = silence).")
    print(f"The OTP is {config.OTP}. Try a wrong one first.\n")

    def press(num_digits):
        return input(f"  you   > press {'a key' if num_digits == '1' else 'the code'}: ").strip()

    def associate_answers():
        return input("  (does the associate pick up? Y/n) ").strip().lower() != "n"

    try:
        PhoneSimulator(app.test_client(), press, associate_answers=associate_answers).run()
    except (KeyboardInterrupt, EOFError):
        print("\n  call | you hung up")


if __name__ == "__main__":
    main()
