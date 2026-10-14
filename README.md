# InspireWorks IVR Demo (Plivo Voice API)

A small web app that calls your phone from a Plivo number, checks who you are with a 4-digit OTP, and then walks you through a two-level voice menu. All of the bot's speech is generated live by Plivo's text-to-speech, and the whole call flow is driven by Plivo XML.

Here's what happens on a call:

1. You click **Call me** on the dashboard and your phone rings, from +91 80354 54161.
2. The bot asks for a 4-digit OTP. The OTP is my birthdate in DDMM format, hardcoded in `config.py`. A wrong code gets "that passcode is incorrect", and the bot asks again until it gets the right one.
3. **Level 1:** press 1 for English or 2 for Spanish.
4. **Level 2**, in the language you picked: press 1 to hear a short audio message (an MP3 played with `<Play>`), press 2 to be connected to a live associate (forwarded with `<Dial>`), or press 9 to go back and change the language.

If you press a key that isn't on the menu, the bot says so and repeats the question. If you press nothing, it tells you it didn't hear anything and asks again. After three silent prompts in a row it says goodbye, so a forgotten call doesn't stay open forever.

While the call is running, the dashboard shows a live timeline of each step, including the exact Plivo XML the server sent back.

## What you need

- Python 3.10 or newer
- A Plivo account: your **Auth ID** and **Auth Token** (from the overview page of the Plivo console) and a voice-enabled Plivo number
- `cloudflared`, so Plivo can reach the app running on your laptop: `brew install cloudflared` on macOS, `winget install Cloudflare.cloudflared` on Windows, or the package from Cloudflare's downloads page on Linux. If you'd rather use ngrok or a deployed server, that works too; see "Using your own public URL" below.

## Setup

```bash
git clone <this repo> && cd plivo-ivr-demo
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Then open `.env` and fill in your values:

```
PLIVO_AUTH_ID=...          # from the Plivo console
PLIVO_AUTH_TOKEN=...
PLIVO_NUMBER=+918035454161 # the number the call comes from
ASSOCIATE_NUMBER=+912264236412
TARGET_NUMBER=+91XXXXXXXXXX # your phone; you can also type it on the dashboard
```

The `.env` file is ignored by git, so your credentials stay on your machine.

## Run it

```bash
python app.py
```

The app opens a free Cloudflare tunnel, checks your Plivo credentials, and prints something like this:

```
  InspireWorks IVR demo
  Dashboard (open this):  http://localhost:5050
  Public URL for Plivo:   https://some-random-words.trycloudflare.com
  Plivo credentials:      OK
```

Open http://localhost:5050, check the phone number, and press **Call me**. Pick up, and follow along on the timeline.

You can also start a call from the terminal while the app is running:

```bash
curl -X POST http://localhost:5050/api/call -H "Content-Type: application/json" -d '{"to": "+91XXXXXXXXXX"}'
```

## Testing

You don't need a phone to try the call flow. `simulate.py` plays the part of Plivo: it sends the same requests Plivo would, reads the XML the app sends back, prints what the caller would hear, and asks you which keys to press.

```bash
python simulate.py
```

```
    bot | Welcome to InspireWorks.
    bot | To verify your identity, please enter your 4 digit passcode.
   keys | 1111
    bot | Sorry, that passcode is incorrect. Please try again.
    ...
```

The automated tests use the same simulator to make complete calls: a wrong OTP and then the right one, both languages, the audio message, the forward to the associate, an associate who doesn't answer, invalid keys at every level, silence, and requests with good, bad or missing Plivo signatures. No real calls are made.

```bash
pytest -v
```

For everything we checked (the Plivo research, every edge case, and the environments we ran it in), see [REPORT.md](REPORT.md).

To test with a real phone, run the app and press **Call me**. A good run-through is: wrong OTP, correct OTP, Spanish, 1 for the audio message, then 2 for the associate.

## How it works

Plivo drives the call by asking the server what to do next. When you answer, Plivo sends a request to `/answer` and the server replies with a few lines of Plivo XML: "say this, then wait for keys". When you press keys, Plivo sends them to the URL named in that XML, and the server replies with the next instructions. That back-and-forth is the whole IVR.

Every question in the IVR has two endpoints: one that asks (`/otp/ask`) and one that checks the answer (`/otp/check`). The check either moves the call forward or speaks an error and sends the call back to the question:

```
/answer --> /otp/ask <--> /otp/check              wrong OTP: say so, ask again
              |
              v
          /language/ask <--> /language/check      1 = English, 2 = Spanish
              |
              v
          /menu/ask?lang=es <--> /menu/check      1 = <Play> MP3, then back to the menu
                                                  2 = <Dial> the associate
                                                  9 = back to /language/ask
```

The chosen language travels in the URL (`?lang=es`), so the server doesn't need a database or any session state.

For example, this is what the server sends when it asks for the OTP:

```xml
<Response>
  <GetDigits action="https://.../otp/check" method="POST" timeout="7" digitTimeout="4" numDigits="4" retries="1" log="false">
    <Speak voice="WOMAN" language="en-US">To verify your identity, please enter your 4 digit passcode.</Speak>
  </GetDigits>
  <Speak voice="WOMAN" language="en-US">Sorry, I did not hear any key press.</Speak>
  <Redirect method="POST">https://.../otp/ask?silence=1</Redirect>
</Response>
```

The prompt plays inside `<GetDigits>`, so you can press keys before it finishes. If you press nothing, Plivo moves on to the lines after `<GetDigits>`: the bot says it didn't hear anything and the `<Redirect>` asks again.

### The files

| File | What's in it |
| --- | --- |
| `ivr.py` | The call flow: every step of the IVR, top to bottom. Start reading here. |
| `app.py` | The dashboard, the "Call me" API that asks Plivo to place the call, and startup. |
| `prompts.py` | Everything the bot says, in English and Spanish, plus the voices. |
| `config.py` | Settings from `.env`, and the hardcoded OTP. |
| `timeline.py` | The in-memory event log behind the dashboard's live timeline. |
| `tunnel.py` | Starts the Cloudflare tunnel and finds its public URL. |
| `simulate.py` | The terminal phone simulator. |
| `templates/index.html` | The dashboard. |
| `static/audio/jingle.mp3` | The audio message for "press 1". |
| `tests/` | The automated tests. |

## A few details worth knowing

**Security.** The tunnel puts the app on the internet, so there are two safeguards. The Plivo webhooks only accept requests carrying a valid `X-Plivo-Signature-V3` signature made with your Auth Token, so nobody else can drive the IVR. The dashboard and the call API only work from the computer running the app; requests that come in through the tunnel get a 403, so strangers can't spend your Plivo credit. OTP digits are never written to the logs or the timeline.

**The audio message.** "Press 1" plays `static/audio/jingle.mp3`, a short chime with no voice, introduced by Plivo's text-to-speech in the caller's language. To play something else, set `AUDIO_URL` in `.env` to any public MP3. Plivo's own sample `https://s3.amazonaws.com/plivocloud/Trumpet.mp3` works.

**Using your own public URL.** If you set `PUBLIC_URL` in `.env` (an ngrok address, or a deployed server), the app uses it and skips the Cloudflare tunnel.

**Changing what the bot says.** All the text is in `prompts.py`. Edit a sentence there and the call flow picks it up.

**India calling.** The Plivo number is an Indian local number, so it's meant for calling Indian phone numbers. Use the full international format, for example `+91XXXXXXXXXX`.

## Troubleshooting

- **The dashboard says "No public URL".** `cloudflared` isn't installed or couldn't connect. Install it, or set `PUBLIC_URL`.
- **"Plivo credentials: NOT WORKING".** The Auth ID or Auth Token in `.env` is wrong.
- **The phone rings, you answer, and the call drops straight away.** Plivo couldn't load `/answer`. Check that the app is still running and look at the timeline for a rejected request.
- **Port 5050 is busy.** Set `PORT=5051` in `.env`. (Port 5000 is avoided on purpose: macOS uses it for AirPlay.)
