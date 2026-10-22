"""Streamlit UI: talk or type to the property assistant, see the avatar answer.

Start the backend first:
    python app.py                 # http://127.0.0.1:8000
Then:
    streamlit run frontend/streamlit_app.py
"""
from __future__ import annotations

import base64
import io
import os
import uuid

import requests
import streamlit as st

API = os.getenv("API_URL", "http://127.0.0.1:8000").rstrip("/")

st.set_page_config(page_title="Voice AI Property Assistant", page_icon="🏠", layout="wide")

if "session_id" not in st.session_state:
    st.session_state.session_id = uuid.uuid4().hex
if "messages" not in st.session_state:
    st.session_state.messages = []
if "audio_key" not in st.session_state:
    st.session_state.audio_key = 0


def api_get(path: str, timeout: float = 5.0):
    return requests.get(f"{API}{path}", timeout=timeout)


def api_post_json(path: str, payload: dict, timeout: float = 120.0):
    return requests.post(f"{API}{path}", json=payload, timeout=timeout)


def render_payload(payload: dict) -> None:
    reply = payload.get("reply") or "(no reply)"
    with st.chat_message("assistant", avatar="🏠"):
        st.markdown(reply)

        avatar = payload.get("avatar") or {}
        if avatar.get("gif_b64"):
            st.image(
                io.BytesIO(base64.b64decode(avatar["gif_b64"])),
                caption=f"avatar: {avatar.get('engine', 'unknown')}",
                width=320,
            )
        elif avatar.get("reason"):
            st.caption(f"Avatar unavailable: {avatar['reason']}")

        audio = payload.get("audio") or {}
        if audio.get("wav_b64"):
            st.audio(base64.b64decode(audio["wav_b64"]), format="audio/wav")
            st.caption(f"voice: {audio.get('provider', 'tts')}")

        transcript = payload.get("transcript")
        if transcript:
            st.caption(f"You said: {transcript}")

        rooms = payload.get("rooms") or []
        if rooms:
            with st.expander(f"Matching rooms ({len(rooms)})", expanded=False):
                for room in rooms:
                    amenities = ", ".join(room.get("amenities", [])) or "—"
                    st.markdown(
                        f"**Room {room['room_id']}** · {room['property_name']} "
                        f"({room['unit']}) · {room['room_type']} · "
                        f"**${room['rent']:,.0f}/mo** · {room['size_sqm']:.0f} m² · "
                        f"up to {room['max_occupants']} · from {room['available_from']}  \n"
                        f"{amenities}"
                    )

        if payload.get("booking"):
            booking = payload["booking"]
            st.success(
                f"Booking #{booking['booking_id']} confirmed for room "
                f"{booking['room_id']} ({booking['check_in']} → {booking['check_out']})"
            )
        elif payload.get("pending_booking"):
            st.info("Waiting for your confirmation. Say or type **yes** to book.")

        if payload.get("error"):
            st.warning(f"({payload['error']})")


with st.sidebar:
    st.header("Property Assistant")
    try:
        health = api_get("/health", timeout=3).json()
        ok = health.get("database", {}).get("ok")
        st.success("Backend online") if ok else st.warning("Backend degraded")
        st.caption(f"Model: {health.get('llm', {}).get('model', '?')}")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Backend offline: {exc}")
        health = {}

    st.divider()
    speak = st.toggle("Speak replies", value=True)
    show_avatar = st.toggle("Show talking avatar", value=True)
    st.caption("CPU only. The default avatar is the fast 'puppet' engine.")

    if st.button("New conversation", use_container_width=True):
        try:
            requests.delete(f"{API}/sessions/{st.session_state.session_id}", timeout=5)
        except Exception:  # noqa: BLE001
            pass
        st.session_state.session_id = uuid.uuid4().hex
        st.session_state.messages = []
        st.session_state.audio_key += 1
        st.rerun()

    st.divider()
    st.subheader("Inventory")
    try:
        rooms = api_get("/rooms").json().get("rooms", [])
        st.caption(f"{len(rooms)} rooms available")
        for room in rooms[:12]:
            st.write(f"#{room['room_id']} · {room['property_name']} {room['unit']} · ${room['rent']:,.0f}")
    except Exception:  # noqa: BLE001
        st.caption("Inventory unavailable")

st.title("🏠 Voice AI Property Assistant")
st.caption("Ask about rent, amenities, availability or policies — then book with a spoken yes.")

for message in st.session_state.messages:
    if message["role"] == "user":
        with st.chat_message("user"):
            st.markdown(message["text"])
    else:
        render_payload(message["payload"])

with st.container():
    left, right = st.columns([3, 2])
    with left:
        typed = st.chat_input("Type a question, e.g. '2 bedroom with parking under $1800'")
    with right:
        recorded = st.audio_input("Or record a question", key=f"mic-{st.session_state.audio_key}")

payload = None
user_text = None

if typed:
    user_text = typed
    with st.spinner("Thinking…"):
        try:
            response = api_post_json(
                "/chat",
                {
                    "message": typed,
                    "session_id": st.session_state.session_id,
                    "speak": speak,
                    "avatar": show_avatar,
                },
            )
        except Exception as exc:  # noqa: BLE001
            st.error(f"Request failed: {exc}")
        else:
            if response.status_code >= 400:
                st.error(f"{response.status_code}: {response.text[:400]}")
            else:
                payload = response.json()

elif recorded is not None:
    data = recorded.getvalue() if hasattr(recorded, "getvalue") else recorded.read()
    with st.spinner("Listening… then thinking…"):
        try:
            response = requests.post(
                f"{API}/voice",
                files={"audio": ("speech.wav", data, "audio/wav")},
                data={
                    "session_id": st.session_state.session_id,
                    "speak": str(speak).lower(),
                    "avatar": str(show_avatar).lower(),
                },
                timeout=300,
            )
        except Exception as exc:  # noqa: BLE001
            st.error(f"Request failed: {exc}")
        else:
            if response.status_code >= 400:
                st.error(f"{response.status_code}: {response.text[:400]}")
            else:
                payload = response.json()
                user_text = payload.get("transcript") or "(voice question)"
    st.session_state.audio_key += 1

if payload is not None:
    if user_text:
        st.session_state.messages.append({"role": "user", "text": user_text})
        with st.chat_message("user"):
            st.markdown(user_text)
    st.session_state.messages.append({"role": "assistant", "payload": payload})
    render_payload(payload)
    st.rerun()
