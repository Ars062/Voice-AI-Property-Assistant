"""FastAPI backend for the Voice AI Property Assistant.

Endpoints
  GET  /                     service metadata
  GET  /health               database + LLM + voice component status
  POST /chat                 text turn -> grounded reply (+ speech / avatar)
  POST /voice                audio upload -> transcript + reply (+ speech / avatar)
  POST /stt                  audio upload -> transcript
  POST /tts                  text -> WAV
  GET  /rooms                current inventory (read-only connection)
  GET  /avatar/portrait      idle portrait PNG
  DELETE /sessions/{id}      forget a conversation
  GET  /meta                 non-secret voice configuration
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from agent.context import store
from config import settings
from database.db import health as db_health
from llm import LLMError, get_llm
from property.tools import search_properties
from voice.avatar.base import to_png_bytes
from voice.avatar.engine import build_avatar, describe as describe_avatar
from voice.pipeline import get_pipeline
from voice.stt import STTError
from voice.tts import TTSError, describe as describe_tts

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("app")

MAX_UPLOAD_BYTES = 15 * 1024 * 1024


@asynccontextmanager
async def lifespan(_app: FastAPI):
    status = db_health()
    if not status.get("ok"):
        logger.warning("database not ready at startup: %s", status.get("error"))
    else:
        logger.info("database ready (%s)", status.get("database"))
    logger.info("llm model: %s", settings.groq_model)
    yield


app = FastAPI(
    title="Voice AI Property Assistant",
    version="1.0.0",
    description="Grounded, read-only property search with local CPU speech and avatar.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None
    speak: bool = True
    avatar: bool = True


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "service": "Voice AI Property Assistant",
        "version": app.version,
        "docs": "/docs",
        "model": settings.groq_model,
    }


@app.get("/health")
def health() -> JSONResponse:
    database = db_health()
    payload: dict[str, Any] = {
        "status": "ok" if database.get("ok") else "degraded",
        "database": database,
        "llm": {
            "provider": "groq",
            "model": settings.groq_model,
            "configured": bool(settings.groq_api_key),
        },
        "tts": describe_tts(),
        "avatar": describe_avatar(),
    }
    code = 200 if database.get("ok") else 503
    return JSONResponse(payload, status_code=code)


@app.get("/meta")
def meta() -> dict[str, Any]:
    return {
        "model": settings.groq_model,
        "tts": describe_tts(),
        "avatar": describe_avatar(),
        "limits": {
            "max_rows": settings.query_max_rows,
            "avatar_max_seconds": settings.avatar_max_seconds,
            "max_upload_bytes": MAX_UPLOAD_BYTES,
        },
    }


@app.post("/chat")
async def chat(request: ChatRequest) -> dict[str, Any]:
    try:
        return await run_in_threadpool(
            get_pipeline().process_text,
            request.message,
            request.session_id or None,
            speak=request.speak,
            with_avatar=request.avatar,
        )
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/voice")
async def voice(
    audio: UploadFile = File(...),
    session_id: str | None = Form(default=None),
    speak: bool = Form(default=True),
    avatar: bool = Form(default=True),
) -> dict[str, Any]:
    data = await audio.read()
    if not data:
        raise HTTPException(status_code=422, detail="empty audio upload")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="audio upload too large")
    try:
        return await run_in_threadpool(
            get_pipeline().process_audio,
            data,
            session_id or None,
            speak=speak,
            with_avatar=avatar,
        )
    except STTError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/stt")
async def speech_to_text(audio: UploadFile = File(...)) -> dict[str, Any]:
    data = await audio.read()
    if not data:
        raise HTTPException(status_code=422, detail="empty audio upload")
    from voice.stt import get_stt

    try:
        text = await run_in_threadpool(get_stt().transcribe, data)
    except STTError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"text": text}


@app.post("/tts")
async def text_to_speech(request: TTSRequest) -> Response:
    from voice.tts import get_tts

    try:
        result = await run_in_threadpool(get_tts().synthesize, request.text)
    except TTSError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(
        content=result.audio,
        media_type="audio/wav",
        headers={"X-TTS-Provider": result.provider},
    )


@app.get("/rooms")
async def rooms() -> dict[str, Any]:
    try:
        return await run_in_threadpool(search_properties, {"limit": settings.query_max_rows})
    except Exception as exc:  # noqa: BLE001 - database failure
        raise HTTPException(status_code=503, detail=f"database unavailable: {exc}") from exc


@app.get("/avatar/portrait")
async def portrait() -> Response:
    try:
        engine = await run_in_threadpool(build_avatar, "puppet")
        frame = engine.idle_frame(blinking=False)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(content=to_png_bytes(frame), media_type="image/png")


@app.delete("/sessions/{session_id}")
def reset_session(session_id: str) -> dict[str, str]:
    store.reset(session_id)
    return {"status": "reset", "session_id": session_id}


def _check() -> None:
    print("== Voice AI Property Assistant ==")
    print(f"Groq key configured : {bool(settings.groq_api_key)}")
    print(f"Groq model          : {settings.groq_model}")
    print(f"Database            : {db_health()}")
    print(f"TTS                 : {describe_tts()}")
    print(f"Avatar              : {describe_avatar()}")
    try:
        print(f"LLM ping            : {get_llm().ping()}")
    except LLMError as exc:
        print(f"LLM ping            : FAILED ({exc})")


def _cli() -> None:
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="Voice AI Property Assistant API")
    parser.add_argument("--check", action="store_true", help="check config and exit")
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    args = parser.parse_args()

    if args.check:
        _check()
        return

    uvicorn.run("app:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    _cli()
