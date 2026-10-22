# 🏨 Voice Hotel Agent

An end-to-end **voice AI hotel concierge** built entirely with free / open-source
tools. It demonstrates a real-time voice conversation backed by a stateful
agent with business logic and a database.

```
User (Voice)
   │
   ▼
LiveKit  ──►  Pipecat pipeline
                   │
   ┌───────────────┼──────────────────────┐
   ▼               ▼                      ▼
Faster-Whisper   LangGraph (state machine)   Kokoro TTS
 (STT)                │
                  LangChain tools
                       │
                  SQLite database
```

## Tech stack

| Purpose            | Tool                                   |
|--------------------|----------------------------------------|
| Voice transport    | LiveKit                                |
| Voice pipeline     | Pipecat                                |
| STT                | Faster Whisper (local)                 |
| Agent orchestration| LangGraph                              |
| Tool calling       | LangChain                              |
| LLM                | **Groq** (free tier, llama-3.3-70b)    |
| DB                 | SQLite + SQLAlchemy                    |
| TTS                | Kokoro (local, free)                   |
| Backend            | FastAPI                                |
| Frontend (demo)    | Streamlit                             |

> You can swap the LLM to OpenAI / Gemini / local Ollama by changing
> `LLM_PROVIDER` in `.env`.

## Project structure

```
voice-hotel-agent/
├── app.py                  # FastAPI backend + CLI entry point
├── config.py               # settings from .env
├── llm.py                  # LLM factory (Groq/OpenAI/Gemini/Ollama)
├── graph.py                # LangGraph state machine
├── livekit_token.py        # LiveKit token generation
├── pipecat_pipeline.py     # LiveKit + Pipecat voice pipeline
├── prompts/
│   ├── __init__.py
│   └── hotel_agent.txt
├── tools/
│   ├── __init__.py
│   └── hotel_tools.py      # search/book/cancel/history/price
├── database/
│   ├── models.py
│   └── db.py
├── stt/
│   └── faster_whisper.py
├── tts/
│   └── kokoro.py
└── frontend/
    └── streamlit_app.py
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt

cp .env.example .env          # then edit: set GROQ_API_KEY, LIVEKIT_*
```

### LLM (Groq)
1. Get a free key at https://console.groq.com
2. Put it in `.env` as `GROQ_API_KEY` (already selected via `LLM_PROVIDER=groq`).

### LiveKit (only needed for the real-time voice path)
1. Create a project at https://cloud.livekit.io (free).
2. Copy the URL, API key and secret into `.env`.

## Run

### 1. Seed the database
```bash
python app.py --seed
```

### 2. Start the text backend + UI (easiest demo)
```bash
python app.py                 # FastAPI on :8000
streamlit run frontend/streamlit_app.py
```
Open the Streamlit UI and chat: *"Book a deluxe room for tomorrow"* → the
agent searches, asks to confirm, then books.

### 3. Real-time voice (LiveKit + Pipecat)
```bash
python app.py --voice
```
A browser/client that joins the LiveKit room with a token from `GET /token`
will be able to speak to the agent and hear Kokoro's voice reply.

## How the agent works (LangGraph)

```
START → greet → classify intent
                    ├─ search/book → search rooms → ask confirmation → (END, wait)
                    │                                      next turn → book
                    ├─ history → list bookings → END
                    ├─ cancel  → cancel by ID   → END
                    └─ other   → friendly reply  → END
```

State (intent, `awaiting_confirmation`, `pending`, `finished`) is checkpointed
with `MemorySaver`, so the agent pauses while waiting for the user's "yes/no"
and resumes correctly on the next utterance.

## Notes
- Kokoro outputs 24 kHz WAV. Faster Whisper runs fully offline.
- To point at a different LLM, just change `LLM_PROVIDER` — no code changes.
- The same voice pipeline can be repurposed for restaurants, hospitals, etc.
