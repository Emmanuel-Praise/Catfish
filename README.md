# Kile — AI Conversational Companion

Kile is a witty, confident, flirtatious, intellectually curious conversational companion.
Basic HTML/CSS/JS frontend · FastAPI backend · SQLite memory · any OpenAI-compatible LLM · WhatsApp Cloud API delivery.

## Setup

```bash
pip install -r requirements.txt
copy .env.example .env      # add your keys (LLM + WhatsApp)
python run_server.py        # or: python -m uvicorn backend.main:app --port 8000
```

Open http://127.0.0.1:8000 — logs go to `kile.log`.

## Configure (.env)

**LLM** — NVIDIA API is primary when `NVIDIA_*` is set (build.nvidia.com);
otherwise any OpenAI-compatible API via `LLM_*`:

```env
NVIDIA_API_KEY=nvapi-...
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_MODEL=nvidia/nemotron-3.5-super-vl-120b-a12b
NVIDIA_FALLBACK_MODEL=nvidia/nemotron-3.5-lightning-30b-a3b
NVIDIA_TIMEOUT_SECONDS=40

# OpenRouter fallback config (used only when NVIDIA_* are unset)
LLM_API_KEY=...
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=nvidia/nemotron-3.5-lightning:free
LLM_FALLBACK_MODEL=openrouter/free, baidu/ernie-5.5-flash-preview:free
```

**WhatsApp / Meta Cloud API:**

```env
WHATSAPP_ACCESS_TOKEN=...
WHATSAPP_PHONE_ID=...
WHATSAPP_VERIFY_TOKEN=...
WHATSAPP_API_VERSION=v25.0
MESSAGE_CHANNEL=whatsapp      # whatsapp = real delivery, log = simulator
```

## Features

- **Chat UI** — sidebar of participants, message bubbles, typing indicator, polling for live updates
- **Humanized pacing** — Kile never replies instantly: a randomized 3–9s "reading" pause
  (plus a little extra for long messages) before he responds — tunable via `REPLY_DELAY_MIN/MAX`
- **Kile's background** — Cameroonian, lives in Bamenda (Northwest), studies at CATUC;
  location/campus references stay scoped to Bamenda/NW Cameroon (see `backend/persona.py`)
- **Multiple participants** — separate conversation histories per person
- **Contextual memory** — facts/preferences/summaries extracted after each chat and
  injected into future conversations (view via the *Memories* button)
- **Kile initiates** — *Kile initiates* button has him message an opted-in participant
  (quiet hours 22:00–08:00 + 12h cooldown enforced; participants need a `contact_ref`
  for WhatsApp delivery)
- **WhatsApp integration** — inbound messages auto-create participants, Kile replies
  and delivers via Meta Cloud API; all replies route through `backend/channels/`
- **Bulk contact add** — *Add numbers* button pastes many WhatsApp numbers at once
  (newline/comma separated; duplicates skipped) → `POST /api/participants/bulk`
- **Cover protection** — replies that would reveal Kile as an AI are regenerated once,
  with a safe deflection as last resort (`_guard_reply` in `backend/chat_service.py`)
- **24-hour window guard** — proactive WhatsApp messages are refused unless the
  contact messaged within the last 24h (Meta free-form policy; protects the number)
- **Webhook** — `GET/POST /api/whatsapp/webhook` ready for the Meta console

## WhatsApp webhook setup (when you configure Meta)

1. **Callback URL:** `https://<your-public-domain>/api/whatsapp/webhook`
2. **Verify token:** the `WHATSAPP_VERIFY_TOKEN` value in `.env` (handshake tested — returns the challenge)
3. **Subscribe to:** `messages` webhook field
4. Inbound flow: Meta → webhook → participant auto-created/lookup → Kile replies → Graph API delivery (runs async, responds 200 to Meta immediately)

Check status: `GET /api/whatsapp/status`
Verify credentials without sending: `python -c "import asyncio; from whatsapp.adapter import WhatsAppAdapter; print(asyncio.run(WhatsAppAdapter().verify_number()))"`

## Deploy on Render

1. Push the repo to GitHub.
2. Render → **New → Blueprint** → pick the repo (`render.yaml` is read automatically).
3. After the first deploy, set the secrets in the service's **Environment** tab:
   `LLM_API_KEY`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_ID`,
   `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET` (from the Meta app dashboard).
4. Your public base URL is `https://<app>.onrender.com` — point the Meta webhook
   callback at `https://<app>.onrender.com/api/whatsapp/webhook`.
5. Re-run the handshake test and `GET /api/whatsapp/status`.

Caveats:

- **Free tier sleeps** after idle → first reply after a cold start is slow; Meta
  retries webhook delivery, but expect ~30s+ wake-up delay.
- **SQLite is ephemeral** on free instances — conversations/memories are lost on
  redeploy. Attach a Render disk and set `DATABASE_PATH` to keep them.
- `WHATSAPP_APP_SECRET` enables webhook signature verification — fill it in;
  leaving it empty means anyone can POST fake inbound messages.

## API overview

| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/api/participants` | list / create |
| POST | `/api/participants/bulk` | add many numbers at once |
| PATCH/DELETE | `/api/participants/{id}` | update / remove |
| GET | `/api/participants/{id}/conversation` | get active conversation |
| GET/POST | `/api/conversations/{id}/messages` | history / send (Kile replies + delivers) |
| GET | `/api/participants/{id}/memories` | what Kile remembers |
| POST | `/api/proactive/trigger` | Kile initiates |
| GET | `/api/proactive/log` | proactive message log |
| GET/POST | `/api/whatsapp/webhook` | Meta verification / inbound messages |
| GET | `/api/whatsapp/status` | WhatsApp config status |

## Adding more channels later

Implement `backend/channels/base.py`'s `ChannelAdapter` and call
`register_channel(...)` at startup — chat/memory logic never changes.

## Notes

- Quiet hours use the server's local clock — adjust `PROACTIVE_QUIET_START/END`.
- `MESSAGE_CHANNEL=log` disables real WhatsApp sends (simulator) while keeping the webhook active.
- Never commit `.env` — it holds live API keys.
