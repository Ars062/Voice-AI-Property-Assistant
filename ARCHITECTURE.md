# Architecture

## 1. Components

```
┌──────────────┐   HTTP    ┌──────────────────────────────────────────────┐
│ Streamlit UI │ ────────► │ FastAPI (app.py)                             │
│ text + mic   │           │  /chat /voice /stt /tts /rooms /health /meta │
└──────────────┘           └───────┬──────────────────────┬───────────────┘
                                   │                      │
                     ┌─────────────▼──────────┐   ┌───────▼──────────────┐
                     │ agent/                 │   │ voice/               │
                     │ context (sessions)     │   │ stt (faster-whisper) │
                     │ prompts (versioned)    │   │ tts (Piper / SAPI)   │
                     │ guardrails             │   │ avatar (puppet /     │
                     │ orchestrator           │   │         MuseTalk)    │
                     └──────┬─────────┬───────┘   │ pipeline             │
                            │         │           └──────────────────────┘
                  plan JSON │         │ answer prompt
                            ▼         ▼
                     ┌──────────┐  ┌──────────┐
                     │ Groq LLM │  │ property/│
                     │ qwen     │  │ plan →   │
                     └──────────┘  │ builder  │
                                   │ validator│
                                   │ repo     │
                                   └────┬─────┘
                                        │ SQL (parameterised)
                              ┌─────────▼──────────┐
                              │ PostgreSQL 16      │
                              │ voice_readonly role│
                              │ (read-only txn)    │
                              └────────────────────┘
```

## 2. Turn lifecycle (text)

1. `POST /chat` validates the request and runs `VoicePipeline.process_text`
   in a worker thread.
2. `Assistant.handle` loads the session (`agent/context.py`), appends the user
   turn and decides between the booking branch and the search branch.
3. Search branch:
   - `_extract_plan` asks Groq for JSON matching `PropertyQueryPlan`
     (`property/query_plan.py`). Pydantic rejects wrong types, negative rent,
     invalid sort keys, and `limit > QUERY_MAX_ROWS`.
   - `_merge_plan` combines the new plan with the previous plan. Scalar fields
     override only when present; amenities are unioned; a "cheapest/largest/
     newest" hint overrides the sort; "start over"/"reset" drops history.
   - `property/sql_builder.py` compiles the plan into a single `SELECT` with
     bind parameters. No user text is interpolated into SQL; the only
     interpolated strings are allow-listed column names and the sort clause.
   - `property/repository.py` executes it on `DATABASE_READONLY_URL`.
4. Answering:
   - Broad searches (not a question) return a deterministic, counted summary so
     the model cannot mis-state how many rooms matched.
   - Specific questions go to the LLM with the exact records as JSON. The reply
     is checked by `guardrails.grounding_issues`; if it mentions a price or room
     id that is not in the records, it is discarded and the deterministic
     summary is used instead.
5. `VoicePipeline._finish` optionally synthesizes the reply and animates the
   avatar, returning base64 WAV/GIF alongside the JSON.

## 3. Why plan-to-SQL instead of text-to-SQL

Text-to-SQL makes the model the security boundary. Here the model only chooses
values for a fixed query shape. That gives:

- guaranteed parameterisation and a stable `EXPLAIN` plan;
- a schema that cannot leak tables the model invents;
- a small, testable validation surface;
- deterministic follow-up behaviour independent of model quality.

`property/validator.py` still exists for a future "advanced query" feature. It
allows only `SELECT`/`WITH`, rejects comments and multiple statements, blocks
DDL/DML and dangerous tokens (`pg_`, `information_schema`, `pg_catalog`), and
requires every non-CTE table reference to be in `ALLOWED_TABLES`.

## 4. Database and safety model

- `properties`, `rooms`, `amenities`, `room_amenities`, `policies`,
  `bookings`, `room_blocks`.
- `bookings_no_overlap` is a GiST exclusion constraint on
  `(room_id WITH =, daterange(check_in, check_out, '[)') WITH &&)`
  for confirmed bookings. Two concurrent requests for overlapping dates cannot
  both commit.
- `bookings.idempotency_key` is unique, so retrying a confirmed voice turn
  returns the original booking instead of creating a second one.
- `room_blocked_ranges` is a view exposing only date ranges (bookings + blocks),
  with no guest PII. It is the only booking-derived object granted to
  `voice_readonly`.
- `voice_readonly` has `default_transaction_read_only=on`,
  `statement_timeout=8s`, `idle_in_transaction_session_timeout=15s`, and no
  `SELECT` on `bookings`.
- `scripts/init_db.py` applies `sql/001_schema.sql`, `002_roles.sql`,
  `003_seed.sql` in order; Docker applies the same files on first boot.

## 5. Booking flow

```
user: "book the cheapest one for Jane Doe from 2027-03-01 to 2027-09-01"
  → BOOKING_PROMPT extracts {room_id, guest_name, check_in, check_out}
  → resolve room from the current result set (never from thin air)
  → validate dates and availability
  → pending_booking = {token, ...}  (no database write)
  → "Please confirm: ... Reply yes to confirm."

user: "yes"
  → create_booking(..., idempotency_key=session:token)
  → INSERT ... RETURNING
  → exclusion constraint or unique key decides races
  → "Booked. Your booking id is N ..."
```

Anything other than an explicit yes/no keeps the pending booking and asks for a
clear confirmation. "No" clears it without writing.

## 6. Voice stack

### STT

`voice/stt.py` wraps faster-whisper (`WhisperModel`, CPU, `int8`, VAD on,
`beam_size=1`). Models download to `WHISPER_MODEL_DIR` on first use. Browser
uploads (`webm/opus`) are decoded through PyAV; WAV is parsed with the standard
library.

### TTS

`voice/tts.py` has two providers:

- **SAPI** (default on Windows): renders through `System.Speech` in a PowerShell
  subprocess. This avoids COM/thread issues that make `pyttsx3` unreliable in a
  server process, and needs no download.
- **Piper** (optional): ONNX neural voice, loaded lazily.

`auto` picks Piper when its `.onnx` file exists and the package imports,
otherwise SAPI.

### Avatar

Both engines share `voice/avatar/base.py` (`AvatarClip`, GIF encoding).

- **puppet** (default): draws a portrait if `assets/portrait.png` is missing,
  pre-renders 8 mouth shapes, and picks one per video frame from the smoothed
  RMS of that frame's audio. It renders faster than real time.
- **musetalk_cpu** (optional): the real MuseTalk 1.5 UNet + SD-VAE pipeline.

## 7. CPU MuseTalk port

`voice/avatar/musetalk_cpu.py` re-implements MuseTalk inference without
`triton`, mmpose, face-parsing or librosa:

1. whisper features are extracted for the utterance;
2. features are reshaped into one prompt per rendered frame;
3. the MuseTalk UNet denoises the cached portrait latents once per frame;
4. SD-VAE decodes the lower-face crop, which is feathered back onto the portrait.

CPU-specific changes:

- device falls back to CPU and dtype to `float32` (float16 is GPU-only);
- only `AVATAR_CPU_RENDER_FPS` unique frames are generated, then repeated to
  `AVATAR_FPS` (e.g. 6 → 25) — the dominant cost saving;
- optional int8 dynamic quantization of UNet `Linear` layers;
- `torch.inference_mode()` everywhere, no autograd;
- `AVATAR_CPU_THREADS` can pin `torch.set_num_threads`;
- lazy imports so the core install never needs torch.

Expected speed on a modern laptop CPU is roughly 1–3 s per generated frame, so
`puppet` remains the interactive default. `AVATAR_MAX_SECONDS` caps the animated
portion of a reply.

## 8. Failure behaviour

| Failure | Behaviour |
| --- | --- |
| Groq unreachable / rate limited | retries with backoff, then `503`; the API never fabricates an answer |
| LLM returns invalid JSON | one repair attempt, then the previous plan (or empty plan) |
| Answer mentions unknown data | discarded, deterministic records summary used |
| Postgres down | `/health` → `503`, `/rooms` → `503`, `/chat` returns an LLM error only if the LLM fails |
| STT failure/empty audio | friendly spoken prompt, `error=stt_failed` / `empty_transcript` |
| TTS failure | text reply still returned, `speech_error` set |
| Avatar failure | text/audio still returned, `avatar.available=false` with a reason |
| Booking conflict | pending cleared, user asked to choose another room |
| API restart | in-memory sessions are lost; the user starts a new conversation |

## 9. Test matrix

`tests/` covers:

- guardrail classification, ordinal/cheapest selection, grounding checks;
- plan validation, parameterisation, allow-listed SQL, blocked injections;
- seeded inventory counts, city/rent/amenity filters, availability windows,
  policies;
- two-step booking, cancellation, missing details, idempotency, overlapping
  conflict, back-to-back dates;
- follow-up filter retention even when the model drops constraints;
- WAV round-trip, resampling, puppet frames, GIF encoding;
- API wiring, health, inventory, portrait, session reset;
- repository-wide assertion that no OpenAI/LangChain imports or retired Groq
  models are used.
