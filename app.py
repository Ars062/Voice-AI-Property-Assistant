"""FastAPI backend.

Endpoints:
  GET  /                 -> health
  POST /chat             -> text in, agent reply out (runs LangGraph)
  POST /stt              -> audio file in, transcript out (Faster Whisper)
  POST /tts              -> text in, WAV audio out (Kokoro)
  GET  /rooms            -> current room inventory
  GET  /token?identity=  -> LiveKit join token for the voice client
"""
from __future__ import annotations

import io

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from config import settings
from database import db as db_mod
from database.models import Room, get_sessionmaker
from graph import run_agent
from livekit_token import generate_token
from stt.faster_whisper import transcribe_file
from tts.kokoro import synthesize


class ChatRequest(BaseModel):
    text: str
    thread_id: str = "default"


class ChatResponse(BaseModel):
    reply: str


app = FastAPI(title="Voice Hotel Agent")


@app.on_event("startup")
def _startup():
    db_mod.init_db()
    db_mod.seed_db()


@app.get("/")
def health():
    return {"status": "ok", "llm": settings.llm_provider}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    import asyncio
    reply = await asyncio.get_event_loop().run_in_executor(
        None, run_agent, req.text, req.thread_id
    )
    return {"reply": reply}


@app.post("/stt")
async def speech_to_text(audio: UploadFile = File(...)):
    import asyncio, os
    suffix = audio.filename.rsplit(".", 1)[-1] if audio.filename else "wav"
    tmp = f"tmp_upload.{suffix}"
    with open(tmp, "wb") as f:
        f.write(await audio.read())
    text = await asyncio.get_event_loop().run_in_executor(
        None, transcribe_file, tmp
    )
    try:
        os.remove(tmp)
    except OSError:
        pass
    return {"text": text}


@app.post("/tts")
async def text_to_speech(req: ChatRequest):
    import asyncio
    audio = await asyncio.get_event_loop().run_in_executor(
        None, synthesize, req.text
    )
    return Response(content=audio, media_type="audio/wav")


@app.get("/rooms")
def rooms():
    Session = get_sessionmaker(settings.database_url)
    with Session() as s:
        rows = [
            {
                "room_number": r.room_number,
                "room_type": r.room_type,
                "price_per_night": r.price_per_night,
                "available": r.available,
            }
            for r in s.query(Room).all()
        ]
    return {"rooms": rows}


@app.get("/token")
def token(identity: str = "guest"):
    return {"token": generate_token(identity), "url": settings.livekit_url,
            "room": settings.livekit_room}


def _cli():
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="Voice Hotel Agent")
    parser.add_argument("--voice", action="store_true",
                        help="Run the LiveKit + Pipecat voice pipeline")
    parser.add_argument("--seed", action="store_true",
                        help="Initialize and seed the database, then exit")
    args = parser.parse_args()

    if args.seed:
        db_mod.init_db()
        db_mod.seed_db()
        print("Database initialized and seeded.")
        return

    if args.voice:
        from pipecat_pipeline import run_voice_agent

        print("Starting LiveKit + Pipecat voice agent...")
        asyncio.run(run_voice_agent())
        return

    # default: start the FastAPI server
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8001, reload=False)


if __name__ == "__main__":
    _cli()
