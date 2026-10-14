# Research and Testing Report

This report explains what we checked before and while building the IVR, which edge cases we found, how the code handles each one, and where we ran it to make sure it doesn't break.

The short version: every behaviour the call flow depends on was checked against Plivo's documentation and the source code of the Plivo Python SDK (version 4.63.0). Every edge case we found is covered by an automated test; there are 51 tests, and most of them simulate a complete phone call. The project was run from a fresh clone on four Python versions locally. GitHub Actions runs it on Linux, macOS and Windows with Python 3.10 to 3.14. We also started the app in six broken setups (no credentials, no tunnel, a busy port, and so on), and each time it explained the problem instead of crashing.

## 1. What we researched, and what it changed

We set up four research tracks: how Plivo collects keypresses, how it speaks, plays and forwards calls, how the SDK and webhook signatures work, and what India and the tunnel require. Each claim was checked in Plivo's docs (plivo.com/docs/voice/xml/...), the installed SDK source, or by running code. These are the findings that shaped the code:

| Question | What we found | What the code does |
| --- | --- | --- |
| Which element should collect keypresses? | `<GetDigits>` is not deprecated, though Plivo now suggests `<GetInput>` for new apps. Interrupting the prompt with a keypress ("barge-in") is documented for `GetDigits` but not for `GetInput`. | Uses `GetDigits`, so callers can press a key while the bot is still talking. |
| What happens if the caller presses nothing? | Plivo does not call the `action` URL. It moves on to the next XML element after `<GetDigits>`, and if there is none, the call hangs up. | Every question is followed by "I did not hear any key press" and a `<Redirect>` back to the same question. The call never hangs up by accident. |
| What does `retries` mean? | In Plivo's open-source engine, `retries` is the total number of attempts, and the default of 1 means a single attempt. | `retries="1"`. The app handles repeats itself, so the caller gets a clear message each time. |
| What if only some digits are typed? | After the gap between digits times out, Plivo sends the partial digits (for example `12`). | A short code gets "the passcode has 4 digits" and the OTP is asked again. |
| What if `#` is pressed on its own? | Not documented. Plivo either skips ahead or sends empty digits. | Both cases lead to "I did not hear any key press" and the same question again. |
| Which parameter holds the keys? | `Digits`, sent with the call details (`CallUUID`, `From`, `To`, ...). | Reads `Digits`. Empty or unexpected values are handled. |
| Which voices work for Spanish? | Plivo's basic voices support `es-ES` (WOMAN/MAN), `es-US` (WOMAN/MAN) and `es-MX` (WOMAN). | `es-ES` + `WOMAN` for Spanish, `en-US` + `WOMAN` for English. All speech is Plivo text-to-speech. |
| Are Spanish accents safe in XML? | The SDK escapes text correctly; we checked `¿`, `ñ`, `ó` and `&` in its output. | Spanish prompts use their real accents. |
| Forwarding rules | The `<Dial>` caller ID must be a number rented on the Plivo account, otherwise the call fails with cause 3030. The Dial `action` URL receives `DialStatus` = `completed`, `busy`, `failed`, `timeout`, `no-answer` or `cancel`. | The caller ID is our Plivo number. `completed` ends the call politely. Every other status says "the associate is not available" and goes back to the menu. |
| What if our server answers with an error? | Plivo hangs up: cause 7011 at `/answer`, 7012 for a `GetDigits` action, 7014 for a `Redirect`, 8011 and up for invalid XML. | Every endpoint returns valid XML, and the tests parse every response. Bad input never causes an error response. |
| How long does Plivo wait for our XML? | The docs disagree (15, 40 or 60 seconds). | All replies are built in memory with no outside calls, so they take a few milliseconds. |
| Can Plivo send the same webhook twice? | Yes, it can retry after a timeout. | The handlers keep no per-call state; the chosen language travels in the URL. A repeated request does no harm. |
| How are webhooks signed? | `X-Plivo-Signature-V3`: HMAC-SHA256 with the Auth Token over the URL (query parameters sorted), the sorted POST parameters and a nonce. Plivo's own Flask sample uses `request.url`, which is wrong behind a tunnel (Flask sees `http://localhost`). A missing header makes the SDK raise an error instead of returning False. Several signatures can arrive separated by commas. | The app rebuilds the URL from the public address, checks for missing headers first, ignores spaces after commas, and sends its own URLs with the query parameters already sorted. Multi-parameter signing on Plivo's side isn't documented, so this removes the risk entirely. |
| Does the SDK catch network errors? | No. DNS failures and timeouts come through as `requests` exceptions, not Plivo errors. Its default timeout is 5 seconds. | The app catches Plivo errors and network errors separately, shows a clear message, and uses a 15-second timeout. |
| India-specific rules | An Indian number can call out only if it is rented and its KYC is accepted. A problem comes back as a 400 error with Plivo's explanation. A concurrency or geo-permission problem comes back as a 403. | Plivo's message is shown on the dashboard as-is, so the caller sees the real reason. |
| SDK pitfalls | The string `"false"` becomes `true` for boolean attributes; `add_get_digits()` returns the Response rather than the new element, which puts the prompt outside the `GetDigits`; Plivo's docs sample uses `numDigits=` but the SDK wants `num_digits=`. | Real Python booleans, `.add()` nesting and snake_case arguments, all checked by tests that inspect the generated XML. |
| Keeping the OTP private | `GetDigits` has a `log` attribute; `log="false"` keeps the digits out of Plivo's debug logs. | The OTP question uses `log="false"`, and the app never writes OTP digits to its own logs or the timeline. Both are tested. |

## 2. Edge cases in the call flow

Every row below is covered by an automated test that runs a full simulated call or sends the exact webhook Plivo would send.

| Situation | What the caller hears | Test |
| --- | --- | --- |
| Wrong OTP, any number of times | "That passcode is incorrect", then the question again, until it's right | `test_otp_is_asked_again_until_correct` |
| OTP too short (e.g. `12`) | "The passcode has 4 digits", then the question again | `test_short_otp_is_explained_and_asked_again` |
| OTP containing `*` or `#` | Treated as a wrong code | `test_otp_with_star_or_hash_counts_as_wrong` |
| Trying to reach the menu without the right OTP | Impossible: the menu is only reached from a correct OTP | `test_menu_is_only_reachable_after_the_right_otp` |
| Invalid key at Level 1 (`5`, `*`) | "That is not a valid option", then Level 1 again | `test_invalid_key_at_level_1_repeats_level_1` |
| Invalid key at Level 2 (`7`, `#`) | The same message in the chosen language, then Level 2 again | `test_invalid_key_at_level_2_repeats_level_2_in_the_chosen_language` |
| Silence | "I did not hear any key press", then the question again | `test_silence_repeats_the_question_then_hangs_up_after_three` |
| Silence three times in a row | A polite goodbye and hang-up, so a forgotten call doesn't run forever | same test |
| A keypress after some silence | The silence counter resets | `test_pressing_a_key_resets_the_silence_counter` |
| Silence in the Spanish menu | Handled in Spanish | `test_silence_in_spanish_menu_is_handled_in_spanish` |
| Plivo sends empty `Digits` | The question again | `test_empty_digits_posted_to_a_check_endpoint_asks_again` |
| Tampered URL (`?lang=fr`, `?silence=abc`) | Falls back to English / ignores the bad value | `test_unknown_language_in_url_falls_back_to_english`, `test_garbage_silence_counter_is_ignored` |
| Press 1 (audio) | A short introduction in the caller's language, the MP3, then back to the menu | `test_audio_option_plays_the_mp3_then_returns_to_menu` |
| Press 9 | Back to the language menu | `test_english_audio_returns_to_menu_and_9_goes_back` |
| Press 2, associate busy / no answer / failed / timeout / cancelled | "The associate is not available", then back to the menu | `test_associate_unreachable_statuses` (5 cases) |
| Press 2, associate answers and the call ends | Goodbye and hang-up | `test_wrong_otp_then_spanish_audio_then_associate` |
| Caller hangs up anywhere | Plivo stops the flow, and our hangup callback logs it, even with missing or odd fields | `test_hangup_callback_tolerates_missing_or_odd_fields` |
| Two calls at the same time | Independent, because the call state lives in each call's URLs | by design |

## 3. Security and abuse cases

| Case | Result | How we know |
| --- | --- | --- |
| Someone on the internet calls a webhook without a signature | 403 | test, and a live request through the real tunnel |
| Request signed with the wrong token | 403 | test |
| Valid signature but tampered digits | 403 | test |
| Plivo sends several signatures (spaces after commas) | Accepted | test |
| Someone opens the dashboard or "Call me" through the public tunnel | 403, so strangers can't spend Plivo credit | test, and a live request through the real tunnel |
| Bad phone numbers (`8919...` without `+91`, letters, too short) | Refused before Plivo is called | `test_call_api_rejects_bad_numbers` (5 cases) |
| Credentials or personal data in the repository | None: `.env` is ignored by git, and every commit was scanned before pushing | git checks |

## 4. Where we ran it

**Fresh clone, four Python versions (macOS).** For each version we cloned the repo, created a new virtual environment, installed `requirements.txt`, ran the tests, and made a full simulated call:

| Python | Install | Tests | Simulated call |
| --- | --- | --- | --- |
| 3.10.0 | ok | 51 passed | ok |
| 3.11.15 | ok | 51 passed | ok |
| 3.13.9 | ok | 51 passed | ok |
| 3.14.4 | ok | 51 passed | ok |

**GitHub Actions: Linux, macOS and Windows.** Every push runs the tests on 15 combinations (Ubuntu, macOS and Windows with Python 3.10, 3.11, 3.12, 3.13 and 3.14). It also starts the real app with no credentials and no tunnel, and checks that the dashboard loads. See the Actions tab of the repository for the latest run.

One CI job failed during development, and it was a bug in the CI script, not in the app. `curl ... | grep -q` can fail with "write error" when `grep` stops reading early. The script now saves the page to a file before checking it.

**Broken setups.** We started the real app in each of these situations to make sure it explains the problem instead of crashing:

| Situation | What happened |
| --- | --- |
| Fresh clone with no `.env` and no `cloudflared` | The app started and printed `credentials: MISSING` and `cloudflared is not installed`. The dashboard showed a red banner, and "Call me" answered "Plivo credentials are missing". |
| Port already in use | Stopped straight away with "Port 5050 is already in use ... set PORT=5051". No tunnel was left running. |
| `PORT=abc` | Stopped with "PORT in .env must be a number". |
| Wrong Auth ID / Token | Startup said "REJECTED by Plivo", and "Call me" answered "Plivo rejected the Auth ID / Auth Token". |
| `cloudflared` installed but crashing | Detected within seconds, explained on the dashboard, and the app kept running. |
| Started from a different folder | `.env`, the templates and the audio file were all still found. |
| Network failure, or a localhost `PUBLIC_URL` | Clear "Could not reach Plivo" / "no public URL" messages, covered by tests. |

**The real setup.** With the real tunnel and credentials, the app confirmed the credentials with Plivo at startup, and Plivo-facing pages were reachable through the public URL (`/health` 200, the MP3 200 with `audio/mpeg`). The dashboard, the call API and unsigned webhooks were refused from the internet (403).

## 5. Known limits

- The app uses Flask's built-in server and keeps the timeline in memory. That's right for a demo; in production it would run under a WSGI server such as gunicorn and log to a proper store.
- The free Cloudflare tunnel gets a new address every time the app starts. That's harmless here because the address is sent to Plivo with every call, but a real deployment would use a fixed domain.
- Signatures are checked, but nonces are not remembered, so a captured request could be replayed. The worst a replay could do is repeat one menu step of a call that is already running.
- Two Plivo behaviours are undocumented: a lone `#`, and how Plivo signs URLs with several query parameters. The code is written so that either answer works.
- On Windows the tests and the app run (CI checks both), but the automatic tunnel needs `cloudflared` on the PATH (`winget install Cloudflare.cloudflared`), or set `PUBLIC_URL`.
- The Plivo number is an Indian local number, so it should only be used to call Indian numbers.

## 6. Reproducing these checks

```bash
pytest -v              # all 51 tests, no phone or credit needed
python simulate.py     # walk through a call in the terminal
python app.py          # the real thing: open http://localhost:5050 and press "Call me"
```
