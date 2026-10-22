"""Pipecat voice pipeline connected to LiveKit.

Pipeline frames:
    LiveKitTransport  ->  FasterWhisperSTT  ->  HotelAgent (our LangGraph)
                      ->  KokoroTTS  ->  LiveKitTransport (speaker)

NOTE: This file requires LiveKit credentials in .env to actually run.
It is structured to match Pipecat's frame-based pipeline API. Import paths
may shift slightly between Pipecat releases; pin the version in requirements.
"""
from __future__ import annotations

import os

from config import settings
from graph import run_agent


class HotelAgentProcessor:
    """Custom Pipecat processor that routes user text through our LangGraph.

    Receives a user's transcribed `TextFrame`, calls the agent, and emits a
    new `TextFrame` with the assistant reply (which flows to TTS).
    """

    def __init__(self):
        self._contexts: dict[str, list] = {}

    async def process_frame(self, frame, direction):
        from pipecat.frames.frames import TextFrame, EndFrame, LLMMessagesFrame

        if isinstance(frame, EndFrame):
            return frame

        if isinstance(frame, TextFrame):
            text = frame.text.strip()
            if not text:
                return None
            thread_id = getattr(frame, "participant_id", "default") or "default"
            reply = run_agent(text, thread_id=thread_id)
            return TextFrame(text=reply)

        return frame


def build_pipeline():
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.pipeline.task import PipelineParams, PipelineTask
    from pipecat.services.faster_whisper.stt import FasterWhisperSTTService
    from pipecat.services.kokoro.tts import KokoroTTSService
    from pipecat.transports.services.livekit.transport import LiveKitTransport

    if not (settings.livekit_url and settings.livekit_api_key
            and settings.livekit_api_secret):
        raise RuntimeError(
            "LiveKit credentials are missing. Set LIVEKIT_URL, "
            "LIVEKIT_API_KEY and LIVEKIT_API_SECRET in .env"
        )

    transport = LiveKitTransport(
        url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
        room=settings.livekit_room,
        audio_out_enabled=True,
        audio_in_enabled=True,
    )

    stt = FasterWhisperSTTService(model_size=settings.whisper_model_size)
    agent = HotelAgentProcessor()
    tts = KokoroTTSService(voice=settings.kokoro_voice)

    pipeline = Pipeline([transport.input(), stt, agent, tts, transport.output()])
    task = PipelineTask(pipeline, params=PipelineParams(allow_interruptions=True))
    runner = PipelineRunner()

    return runner, task


async def run_voice_agent():
    runner, task = build_pipeline()
    await runner.run(task)
