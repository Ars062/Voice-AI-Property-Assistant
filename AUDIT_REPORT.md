# Audit Report

Date: 2026-10-22
Repository: `Ars062/Voice-AI-Property-Assistant`
Baseline: the legacy implementation is preserved in the first commit
(`chore: import legacy Voice Hotel Agent baseline`) and is no longer in the
working tree.

## 1. Scope

The starting point was a small "hotel voice agent" demo: FastAPI + LangGraph +
LangChain + SQLite, with Faster-Whisper, Kokoro TTS and a LiveKit/Pipecat voice
path. The goal was to turn it into a working, CPU-only, grounded property
assistant backed by PostgreSQL with Groq only.

Audited areas:

- LLM configuration and provider usage;
- speech-to-text and text-to-speech wiring;
- database schema, availability logic and booking correctness;
- API/UI consistency and configuration;
- security boundaries (SQL, roles, secrets, PII);
- whether the voice/avatar path can run without a GPU.

## 2. Findings in the legacy code

| # | Severity | Finding | Evidence / effect |
| --- | --- | --- | --- |
| 1 | Critical | STT was unusable | `stt/faster_whisper.py` imported `Whisper`; the class is `WhisperModel`. Every import of the module raised `ImportError`. |
| 2 | Critical | Double-booking was guaranteed | `tools/hotel_tools.py::book_room` set `room.available = False` permanently, so a room could never be booked twice and no date range was stored. |
| 3 | Critical | Date filters were ignored | `tools/hotel_tools.py::search_rooms` accepted `check_in`/`check_out` but never used them; availability was a single boolean. |
| 4 | High | Retired Groq model hard-coded | `llm.py` used `llama-3.3-70b-versatile` via `langchain_openai.ChatOpenAI`, which returns `404 model_not_found` on the current account. |
| 5 | High | Wrong abstraction for the provider | The Groq endpoint was driven through the OpenAI client, adding an unnecessary dependency and obscuring the actual provider. |
| 6 | High | Money stored as an integer | `database/models.py` used `price_per_night: Integer`. Rounding and currency are ambiguous; the new schema uses `numeric(10,2)`. |
| 7 | High | No property/amenity/policy model | Rooms had no amenities, policies, address or property grouping, so most realistic questions could not be answered. |
| 8 | Medium | Broken session factory | `database/models.py::get_sessionmaker` was truncated/misbehaving (returned a session or lost the engine), making call sites fragile. |
| 9 | Medium | TTS dependency missing | `tts/kokoro.py` imported `KPipeline`, but Kokoro was not in `requirements.txt` and is not an offline-CPU-safe default. |
| 10 | Medium | Voice path required LiveKit | LiveKit keys were empty; `app.py --voice` could not start, and Pipecat/LiveKit were not installed. |
| 11 | Medium | Port inconsistency | The CLI served on `8001`, the Streamlit app called `8001`, and the docs used `8000`. |
| 12 | Medium | SQLite file committed | `hotel.db` was in the tree; the database had no roles, no read-only boundary and no constraints. |
| 13 | Low | No tests | Nothing verified filtering, booking or the voice path. |
| 14 | Low | Secret handling | A real `GROQ_API_KEY` sat in `.env`. It was preserved locally and `.env` is now gitignored; `.env.example` is the committed template. |

## 3. Groq audit

Verified directly against the provided key:

- The key is valid (56 characters) and `GET /models` returns 11 models for this
  account: `allam-2-7b`, two `canopylabs/orpheus-*` TTS voices,
  two `meta-llama/llama-prompt-guard-2-*` classifiers,
  `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `openai/gpt-oss-safeguard-20b`,
  `qwen/qwen3.8-27b`, `whisper-large-v3`, `whisper-large-v3-turbo`.
- `llama-3.3-70b-versatile`, `llama-3.1-8b-instant` and
  `meta-llama/llama-4-scout-17b-16e-instruct` return `404 model_not_found`.
- An initial `403 error code: 1010` was Cloudflare blocking a bare `urllib`
  user agent, not an auth failure. The Groq SDK sends a normal user agent and
  works.
- Selected `qwen/qwen3.8-27b`: it is chat-capable, fast, returns clean JSON with
  `response_format={"type":"json_object"}`, and is not OpenAI-branded.

`llm.py` now uses the `groq` SDK only, with retries/backoff, a strict JSON
helper and a `ping()` used by `python app.py --check`.

## 4. Database and security redesign

Implemented in `sql/`:

- normalised schema (`properties`, `rooms`, `amenities`, `room_amenities`,
  `policies`, `bookings`, `room_blocks`);
- `bookings_no_overlap` GiST exclusion constraint on room + `daterange` for
  confirmed bookings — concurrency safety at the database, not in Python;
- unique `idempotency_key` for retry safety;
- `room_blocked_ranges` view exposing only dates (no guest PII);
- `voice_readonly` role with `default_transaction_read_only=on`,
  `statement_timeout=8s`, `idle_in_transaction_session_timeout=15s`, and no
  access to `bookings`;
- synthetic seed data: 3 properties, 12 rooms, 10 amenities, 9 policies,
  3 bookings, 1 maintenance block.

Verified by direct SQL:

- `current_user = voice_readonly`, `transaction_read_only = on`;
- `SELECT` on `rooms` and `room_blocked_ranges` succeeds;
- `SELECT` on `bookings`, `INSERT`, and `UPDATE` are denied.

The search path never receives model-written SQL. `PropertyQueryPlan` is
validated with Pydantic, compiled by `sql_builder` with bind parameters, and
executed through the read-only role. `validator.py` is retained as
defense-in-depth for any future raw-SQL feature and rejects non-SELECT
statements, comments, multiple statements, system schemas/functions, and any
table outside the allow-list (including CTE handling).

## 5. Voice and avatar

- STT: faster-whisper `WhisperModel`, CPU, `int8`, VAD.
- TTS: Windows `System.Speech` via PowerShell by default (no dependency,
  reliable from a server thread); optional Piper for a neural voice.
- Avatar: `puppet` is the CPU default and renders faster than real time.
- MuseTalk 1.5 was ported to CPU in `voice/avatar/musetalk_cpu.py`:
  - no `triton`, no mmpose/face-parsing/librosa;
  - CPU/float32 fallback, `torch.inference_mode`, optional int8 dynamic
    quantization, optional thread pinning;
  - renders at `AVATAR_CPU_RENDER_FPS` and repeats frames to `AVATAR_FPS`,
    which is the main CPU saving;
  - lazy imports so torch is never required for the core install.
- The MuseTalk port is implemented but **not yet validated with weights on this
  machine** (weights are not present). Until they are, `auto` correctly selects
  the puppet engine and `/health` reports the missing files.

## 6. Verification performed

| Check | Result |
| --- | --- |
| `python -m pytest` | **56 passed** |
| Inventory filters (Austin ≤1500 + wifi) | rooms 1, 2, 5, 6 |
| Amenity filter (2BR + pet friendly) | rooms 4, 11 |
| Availability window excludes seeded booking/block | rooms 2 and 12 absent |
| SQL injection attempts | parameterised; validator rejects 9 classes of unsafe SQL |
| Booking overlap | `BookingConflict` raised by the exclusion constraint |
| Booking idempotency | second call returns the same id with `duplicate=true` |
| Back-to-back dates | allowed |
| Read-only role | writes denied; `bookings` unreadable |
| Real Groq search + follow-up | filters retained after "which is cheapest?" |
| Real voice turn | SAPI WAV produced; puppet GIF produced (375 frames) |
| `python app.py --check` | database OK, Groq ping OK, TTS `sapi`, MuseTalk reported missing |

## 7. Residual risks and next steps

1. **In-memory sessions** — state is lost on restart and not shared across
   workers. A Redis-backed store is the natural next step if scaled.
2. **No authentication** — the API is local-only by default (`127.0.0.1`).
   Before exposing it, add auth and restrict CORS (currently `*` for local UI).
3. **Booking trust** — a booking is created from a spoken name and dates, with
   no identity or payment verification. This is a demo flow, not a contract.
4. **Model variability** — qwen is constrained by prompts, schema validation,
   deterministic summaries and grounding checks, but a different model may
   require prompt tuning. The test suite pins the behavioural contracts.
5. **MuseTalk CPU** — needs real weights and a real portrait to validate quality
   and speed. Keep `puppet` as the default until then.
6. **Windows-only TTS default** — Linux deployments should install Piper
   (`requirements-piper.txt`); the code already prefers Piper when available.
7. **Audio privacy** — audio is processed in-process and not persisted, but
   transcripts and replies live in memory for the session TTL (2 hours).
