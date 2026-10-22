# Voice AI Property Assistant

A CPU-only voice assistant for a residential rental agency. It answers questions
about rooms, rent, amenities, availability and policies from a PostgreSQL
database, then optionally speaks the answer with a local voice and animates a
talking-head avatar. Bookings are prepared as a two-step confirmation and are
protected against double-booking in the database.

Everything runs locally except the language model, which is **Groq** (no OpenAI,
no LangChain).

```
browser mic ──► FastAPI /voice ──► faster-whisper ──► grounded agent ──► Windows SAPI / Piper
                                                          │                     │
                                                          ▼                     ▼
                                               read-only PostgreSQL      puppet / MuseTalk avatar
```

## What it guarantees

| Concern | How it is handled |
| --- | --- |
| Invented answers | The LLM only produces a validated `PropertyQueryPlan`; answers are generated from the returned records and rejected if they mention unknown prices or room ids. |
| SQL injection / data exfiltration | Searches use parameterised SQL through a `voice_readonly` role with `default_transaction_read_only=on`; a defense-in-depth validator blocks anything outside an allow-list. |
| Double booking | PostgreSQL `EXCLUDE USING gist` constraint on `(room_id, daterange)` plus a unique idempotency key. |
| Accidental bookings | A booking is created only after the user replies **yes** to a confirmation prompt. |
| Follow-up drift | New plans are merged with the previous plan, so "which is cheapest?" never silently broadens the search. |
| GPU requirement | STT, TTS, avatar and database run on CPU; the neural avatar is optional. |

## Quick start (Windows)

Prerequisites: Python 3.11/3.12, Docker Desktop (WSL 2 backend), and a Groq API key.

```powershell
git clone https://github.com/Ars062/Voice-AI-Property-Assistant.git
cd Voice-AI-Property-Assistant

Copy-Item .env.example .env
# edit .env and set GROQ_API_KEY=...

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

docker compose up -d
python scripts\init_db.py --check
python app.py --check
```

Or run everything with one script:

```powershell
scripts\run_windows.cmd
```

Then open:

- UI: <http://127.0.0.1:8501>
- API docs: <http://127.0.0.1:8000/docs>

Type a question or use the browser microphone. Try:

> I need a two bedroom with parking in Austin under $1800

> Which one is cheapest, and are pets allowed there?

> Book it for Jane Doe from 2027-03-01 to 2027-09-01

## Manual run

```powershell
# terminal 1 — API
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000

# terminal 2 — UI
.\.venv\Scripts\python.exe -m streamlit run frontend\streamlit_app.py --server.port 8501
```

## Configuration

All settings live in `.env` (see `.env.example`). The important ones:

| Variable | Default | Meaning |
| --- | --- | --- |
| `GROQ_API_KEY` | — | required |
| `GROQ_MODEL` | `qwen/qwen3.8-27b` | must exist for your Groq account |
| `DATABASE_URL` | `...localhost:5433/voice_property` | write role (bookings, admin) |
| `DATABASE_READONLY_URL` | `...voice_readonly...` | used by all searches |
| `TTS_PROVIDER` | `auto` | Piper if installed, else Windows SAPI |
| `AVATAR_ENGINE` | `auto` | MuseTalk if weights exist, else puppet |
| `AVATAR_CPU_RENDER_FPS` | `6` | unique MuseTalk frames per second on CPU |
| `PORT` | `8000` | API port (UI defaults to 8501) |

## Optional models

The app works with none of these installed:

```powershell
python scripts\fetch_assets.py --whisper    # pre-download faster-whisper (otherwise first use)
python scripts\fetch_assets.py --piper      # neural TTS +: pip install -r requirements-piper.txt
python scripts\fetch_assets.py --musetalk   # neural avatar +: pip install -r requirements-avatar.txt
```

MuseTalk on CPU is a best-effort port. It is much slower than real time; the
default `puppet` avatar is recommended for interactive use. See
[ARCHITECTURE.md](ARCHITECTURE.md#cpu-musetalk-port).

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | service metadata |
| `GET` | `/health` | database, LLM, TTS and avatar status |
| `POST` | `/chat` | text turn → reply (+ WAV + GIF) |
| `POST` | `/voice` | audio upload → transcript + reply (+ WAV + GIF) |
| `POST` | `/stt` | audio upload → transcript |
| `POST` | `/tts` | text → WAV |
| `GET` | `/rooms` | current inventory |
| `GET` | `/avatar/portrait` | idle portrait PNG |
| `DELETE` | `/sessions/{id}` | forget a conversation |

Full request/response shapes: [API.md](API.md).

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

56 tests cover guardrails, plan validation, SQL safety, inventory filters,
availability, booking idempotency/concurrency, follow-up merging, grounding,
audio conversion, avatar rendering, API wiring and the Groq-only constraint.
Database tests skip automatically when Postgres is not running.

## Project layout

```
agent/            conversation state, prompts, guardrails, orchestrator
property/         query plan, SQL builder, validator, repository, tools
database/         SQLAlchemy models + engines
voice/            STT, TTS, audio helpers, avatar engines, pipeline
frontend/         Streamlit UI (text + browser microphone)
sql/              schema, roles, seed data
scripts/          init_db, fetch_assets, wait_for_db, run_windows
tests/            pytest suite
app.py            FastAPI entry point
config.py         pydantic-settings
llm.py            Groq SDK client
```

## Data

The seed dataset is synthetic: 3 properties, 12 rooms, 10 amenities, 9 policies,
3 bookings and 1 maintenance block. It is defined in `sql/003_seed.sql`.
`scripts/init_db.py` applies `sql/*.sql` in order and can `--reset`.

## Limitations

- Conversation state is in memory (one process); restarting the API clears sessions.
- Booking capture stores a guest name and dates; there is no payment or email step.
- LiveKit/WebRTC is not used. Voice input is the browser microphone via Streamlit.
- The read-only role protects the search path; the booking path intentionally uses the write role.
- MuseTalk CPU speed depends heavily on the machine and is capped by `AVATAR_MAX_SECONDS`.

See [SETUP.md](SETUP.md) for installation and troubleshooting,
[ARCHITECTURE.md](ARCHITECTURE.md) for the design, and
[AUDIT_REPORT.md](AUDIT_REPORT.md) for what was wrong with the legacy code.
