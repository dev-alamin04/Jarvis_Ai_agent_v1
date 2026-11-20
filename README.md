# Jarvis Voice-Controlled Desktop AI Agent

Jarvis is a private, voice-controlled desktop AI agent built for Linux laptops. It runs continuously, listens via wake word ("Hey Jarvis") or push-to-talk, interprets natural language commands using OpenAI models with tool calling, and controls the system through a secure Permission Gate.

---

## ⚠️ Important Terms of Service & Automation Advisory

> [!CAUTION]
> **Account Safety & Terms of Service Notice:**
> Automating user actions on **WhatsApp, Facebook Messenger, and Telegram** via browser automation or client scripts can go against their official Terms of Service (e.g. WhatsApp Terms of Service § Acceptable Use, Meta Platform Terms, Telegram Terms of Service).
> 
> - **Potential Risks**: Accounts may be temporarily rate-limited, flagged by anti-bot heuristics, or subject to account restrictions/suspension if automated excessively.
> - **Jarvis Safeguards**: Jarvis incorporates strict built-in safeguards to minimize risk:
>   - **Daily Send Limit**: Hard cap per platform (default: 20 messages/day).
>   - **Human-like Delays**: Random jitter and keystroke cadence (35–75ms per character).
>   - **Dedicated Profiles**: Uses persistent local user data directories rather than scraping session tokens.
>   - **Mandatory Confirmation**: Every single message must be explicitly confirmed by your spoken voice before anything is sent.
> 
> Use automated messaging responsibly and only for personal communication.

---

## Features

- **Hands-Free Wake Word**: Offline `openWakeWord` ("Hey Jarvis") + `webrtcvad` silence detection + fallback push-to-talk.
- **Fast Voice Pipeline**: Sentence-level streaming TTS and latency profiler (<350ms to first audio byte).
- **Intelligent Model Routing**: Instant local routing of simple tasks to `gpt-4o-mini` and complex/coding/vision tasks to `gpt-4o`.
- **Persistent Long-Term Memory**: SQLite store for facts, preferences, and project contexts, with secret redaction and 3-minute sliding conversational memory.
- **Screen Vision & Computer Control**: In-memory RAM-only screenshot analysis (`take_screenshot`, `fix_screen_error`), mouse and keyboard control, file management, and browser automation.
- **Unified Multi-Platform Messaging**: Send messages on **WhatsApp**, **Facebook Messenger**, and **Telegram** using your own logged-in browser sessions.

---

## Unified Messaging Tool: `send_message`

Send messages on WhatsApp, Facebook Messenger, or Telegram using a single voice command:

> *"Hey Jarvis, send Rahim a WhatsApp message: I will call you tonight."*

### How It Works

1. **Natural Voice Input**: You state the platform, contact name, and message. If you forget the platform, Jarvis asks: *"Which platform would you like to use: WhatsApp, Messenger, or Telegram?"*
2. **Dedicated Persistent Profile**: Jarvis launches a dedicated Chromium profile (`data/browser_profiles/<platform>`). You log in or scan the QR code **by hand once**. Jarvis never handles, asks for, or stores your passwords.
3. **Contact Disambiguation**: Searches for the recipient. If multiple people share a similar name (e.g. *Rahim Uddin* vs *Rahim Khan*), Jarvis reads the candidate names aloud and asks you which one to message. It **never guesses**.
4. **Mandatory Spoken Confirmation**: Jarvis reads the complete message aloud:
   > *"Send on WhatsApp to Rahim Uddin: I will call you tonight. Shall I send?"*
   
   It waits for your spoken **"yes"**. If you say "no", it cancels immediately. This check is enforced by the Permission Gate and cannot be bypassed.
5. **Human-like Send & Verification**: Types the message with realistic keystroke intervals, submits, verifies that the message bubble appears in the chat thread, and confirms: *"Message sent on WhatsApp to Rahim Uddin and verified."*

---

## Platform Setup & First-Time Login

Each platform maintains its own isolated profile in `data/browser_profiles/` without copying cookies from your personal browser.

### 1. WhatsApp Web
1. Say *"Send a WhatsApp message to [Name]: [Message]"*.
2. A visible browser window will open to `https://web.whatsapp.com`.
3. The first time, scan the on-screen QR code using WhatsApp on your phone (**Linked Devices**).
4. Once scanned, your session remains permanently active in `data/browser_profiles/whatsapp`.

### 2. Telegram Web A
1. Say *"Send a Telegram message to [Name]: [Message]"*.
2. A visible browser window will open to `https://web.telegram.org/a/`.
3. Log in once using your phone number or the Telegram QR code.
4. Your session is saved in `data/browser_profiles/telegram`.

#### Telegram Web vs Telethon (MTProto API)
- **Telegram Web A (Default)**: Zero API setup needed; you log in through the visible UI once. You can observe the chat and watch the verification in real time.
- **Telethon (Optional MTProto Backend)**:
  - *Reliability*: Communicates directly via Telegram's MTProto protocol, completely immune to web UI/HTML changes.
  - *Speed*: Extremely fast and headless.
  - *Setup*: Requires registering an application at [my.telegram.org](https://my.telegram.org) to obtain `api_id` and `api_hash`.
  - *Configuration*: In `config/config.yaml`, set `messaging.telegram.backend: "telethon"`.

### 3. Facebook Messenger
1. Say *"Send a Messenger message to [Name]: [Message]"*.
2. A visible browser window opens to `https://www.messenger.com`.
3. Log in by hand once. Jarvis never touches or asks for your password.
4. If a two-factor authentication or security checkpoint appears, complete it in the browser.
5. Your session is saved in `data/browser_profiles/messenger`.

---

## Privacy & Safety Invariants

- **Zero Message Logging**: Audit records in `logs/messaging_audit.log` record only:
  `[Timestamp] | PLATFORM: whatsapp | RECIPIENT: Rahim Uddin | LENGTH: 24 chars | STATUS: SENT`
  **The message text itself is never written to disk or logs.**
- **No Private Chat Reading**: Jarvis never reads or summarizes your message history unless explicitly requested.
- **Daily Rate Limiting**: Capped at 20 messages per platform per day (configurable via `messaging.daily_limit` in `config/config.yaml`).
- **Human Typing Speed**: Realistic typing simulation (35–75ms per keystroke) with random jitter to prevent bot detection.

---

## Linux Installation Steps

### 1. System Packages (Debian/Ubuntu/Kali)
```bash
sudo apt update && sudo apt install -y xclip xdotool google-chrome-stable
```

### 2. Python Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configuration (`config/config.yaml`)
Export your OpenAI API key:
```bash
export OPENAI_API_KEY="sk-..."
```

---

## Test Checklist per Platform

Run the automated messaging test suite:
```bash
PYTHONPATH=. ./venv/bin/python tests/test_messaging.py
```

### Manual Verification Checklist

#### WhatsApp Web
- [ ] Say: *"Send Rahim a WhatsApp message: I am testing Jarvis"*
- [ ] Confirm browser opens with WhatsApp profile (`data/browser_profiles/whatsapp`).
- [ ] Verify Jarvis reads aloud: *"Send on WhatsApp to Rahim: I am testing Jarvis. Shall I send?"*
- [ ] Reply *"no"* $\rightarrow$ Verify message is cancelled.
- [ ] Say command again and reply *"yes"* $\rightarrow$ Verify message is typed with natural delays, sent, and verified.
- [ ] Check `logs/messaging_audit.log` contains recipient and length, but **no message text**.

#### Telegram
- [ ] Say: *"Send John a Telegram message: Meeting at 5pm"*
- [ ] Confirm recipient search and readback aloud.
- [ ] Verify outgoing message verification in chat bubbles.

#### Facebook Messenger
- [ ] Say: *"Send Sarah a Messenger message: Hello Sarah"*
- [ ] Confirm contact search in search dropdown.
- [ ] Verify spoken confirmation gate intercepts before typing.
