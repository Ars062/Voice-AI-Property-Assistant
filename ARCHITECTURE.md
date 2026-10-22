# Architecture & "What Each Part Is Actually Doing"

> Status: the FastAPI backend is **running locally** at `http://localhost:8001`
> (started with `python app.py`). SQLite is seeded. The LangGraph agent,
> LangChain tools and Faster-Whisper/Kokoro modules are wired in. The only
> thing not yet exercised is the live voice path (needs LiveKit keys + mic).

---

## 1. Big picture

```
                         ┌──────────────────────────────────────────────┐
   Browser / Streamlit   │                YOUR MACHINE                   │
   (localhost:8501)      │                                              │
        │  HTTP          │   FastAPI (:8001)  ──►  graph.run_agent()    │
        ├───────────────►│        │                    │                │
        │                │        │                    ▼                │
        │                │        │            LangGraph state machine  │
        │  ◄─────────────┤        │                    │                │
        │   JSON reply   │        │                    ▼                │
        │                │        │            LangChain tools (.invoke)│
        │                │        │                    │                │
        │                │        │                    ▼                │
        │                │        │            SQLite (SQLAlchemy)      │
        │                │        │                                     │
   (Voice mode only)     │        │   Pipecat pipeline ─► LiveKit room   │
        │  WebRTC        │        │     STT → agent → TTS               │
        └───────────────►└────────┴────────────────────────────────────┘
```

The **same brain** (`graph.run_agent`) is used by both the text UI and the
voice pipeline. Only the outer transport differs.

---

## 2. File-by-file: what it does and where it sits

### Entry / config
| File | Role | "Where it's doing its job" |
|------|------|----------------------------|
| `app.py` | FastAPI app + CLI. Exposes `/chat`, `/stt`, `/tts`, `/rooms`, `/token`. `python app.py` starts the server on `:8001`; `--voice` starts Pipecat; `--seed` seeds DB. | The **front door**. All HTTP requests land here. |
| `config.py` | Loads `.env` into a `Settings` object (`LLM_PROVIDER`, DB URL, LiveKit keys, Whisper/Kokoro settings). | Read at import time by every other module. |
| `llm.py` | `get_llm()` factory. Returns Groq (default) / OpenAI / Gemini / Ollama chat model. | Called whenever the agent needs to "think". |
| `livekit_token.py` | `generate_token()` mints a LiveKit JWT for a client to join a room. | Called by `GET /token` for the voice client. |
| `.env.example` | Template for secrets. Copy to `.env`. | Config source. |

### Brain (agent)
| File | Role | "Where it's doing its job" |
|------|------|----------------------------|
| `graph.py` | **LangGraph state machine.** Nodes: `greet → classify → (search/book/history/cancel/respond)`. Uses `MemorySaver` to remember state across turns (e.g. "waiting for confirmation"). `run_agent(text, thread_id)` runs one turn. | The **brain**. Receives text, decides intent, calls tools, returns reply. |
| `prompts/hotel_agent.txt` | System prompt for the LLM (tone, rules, never invent prices). | Loaded by `graph.py` and used in every LLM call. |
| `prompts/__init__.py` | Reads the txt file into `HOTEL_SYSTEM_PROMPT`. | Import helper. |

### Hands (tools / DB)
| File | Role | "Where it's doing its job" |
|------|------|----------------------------|
| `tools/hotel_tools.py` | LangChain `@tool` functions: `search_rooms`, `check_price`, `book_room`, `cancel_booking`, `booking_history`. Each talks to SQLite. | Called **by the nodes in `graph.py`** to do real work. |
| `tools/__init__.py` | Re-exports the tools. | Import helper. |
| `database/models.py` | SQLAlchemy `Room` + `Booking` tables. | Defines the schema. |
| `database/db.py` | `init_db()`, `seed_db()` (creates tables + sample data). | Runs on FastAPI startup and via `python app.py --seed`. |

### Voice (optional / not yet live)
| File | Role | "Where it's doing its job" |
|------|------|----------------------------|
| `stt/faster_whisper.py` | `WhisperSTT` wrapper — audio file → transcript, runs locally. | Used by `POST /stt` and inside the Pipecat STT service. |
| `tts/kokoro.py` | `KokoroTTS` — text → 24 kHz WAV, runs locally. | Used by `POST /tts` and inside the Pipecat TTS service. |
| `pipecat_pipeline.py` | Builds the Pipecat frame pipeline: `LiveKit → FasterWhisper → HotelAgentProcessor → Kokoro → LiveKit`. `HotelAgentProcessor` is a custom node that calls `run_agent`. | Only active when you run `python app.py --voice` with LiveKit keys set. |

### UI
| File | Role | "Where it's doing its job" |
|------|------|----------------------------|
| `frontend/streamlit_app.py` | Text chat UI that calls `POST /chat` and shows room inventory from `GET /rooms`. | Runs separately on `localhost:8501`. |

---

## 3. Runtime flows (what actually happens)

### A. Text chat (working now)
1. You type in Streamlit → `POST /chat {text, thread_id}` to FastAPI.
2. `app.py` → `graph.run_agent(text)`.
3. `graph.py`: `classify` node asks LLM for intent → routes to a node.
4. That node calls a LangChain tool (e.g. `search_rooms.invoke(...)`).
5. Tool reads/writes SQLite → returns text.
6. LLM phrases a friendly reply → returned to FastAPI → Streamlit shows it.
7. State saved in `MemorySaver` keyed by `thread_id`, so the next message
   continues the same conversation (e.g. confirming a booking).

### B. Voice chat (needs LiveKit keys + mic)
1. Browser joins LiveKit room using token from `GET /token`.
2. Your speech → LiveKit → Pipecat `FasterWhisperSTT` → text.
3. `HotelAgentProcessor` → `run_agent(text)` (same brain as text).
4. Reply text → Pipecat `KokoroTTSService` → audio → LiveKit → your ears.

---

## 4. What is LIVE right now vs. what needs more
- ✅ FastAPI backend on `:8001` (verified responding)
- ✅ SQLite seeded, `/rooms` returns data
- ✅ LangGraph + LangChain tools import and run (verified via smoke test)
- ⚠️ `/chat` needs `GROQ_API_KEY` in `.env` to actually answer (LLM call)
- ⏸️ Voice path needs `LIVEKIT_URL/API_KEY/API_SECRET` + `--voice` to run
- ⏸️ Streamlit UI needs `pip install streamlit` + `streamlit run frontend/streamlit_app.py`

## 5. How to bring the rest online
```bash
pip install -r requirements.txt
cp .env.example .env          # fill GROQ_API_KEY (+ LiveKit keys for voice)
python app.py --seed
python app.py                 # backend :8001  (already running)
streamlit run frontend/streamlit_app.py   # UI :8501
# for voice:
python app.py --voice
```
