"""Simple Streamlit frontend for the hotel agent.

Run the backend first:
    uvicorn app:app --reload --port 8000

Then run this UI:
    streamlit run frontend/streamlit_app.py

It demonstrates the LangGraph + LangChain agent over text. The real-time
voice path (LiveKit + Pipecat) is started separately with `python app.py --voice`.
"""
from __future__ import annotations

import requests
import streamlit as st

API = "http://localhost:8001"

st.set_page_config(page_title="Voice Hotel Agent", page_icon="🏨")
st.title("🏨 Hotel Voice Agent (text demo)")

if "history" not in st.session_state:
    st.session_state.history = []
if "thread_id" not in st.session_state:
    st.session_state.thread_id = "streamlit-user"

with st.sidebar:
    st.subheader("Room inventory")
    try:
        rooms = requests.get(f"{API}/rooms", timeout=5).json()["rooms"]
        for r in rooms:
            status = "✅" if r["available"] else "❌"
            st.write(f"{status} Room {r['room_number']} · {r['room_type']} "
                     f"· ${r['price_per_night']}")
    except Exception as e:
        st.error(f"Backend offline: {e}")

for role, text in st.session_state.history:
    st.chat_message(role).write(text)

user_input = st.chat_input("Say something, e.g. 'Book a deluxe room tomorrow'")
if user_input:
    st.chat_message("user").write(user_input)
    st.session_state.history.append(("user", user_input))
    try:
        resp = requests.post(
            f"{API}/chat",
            json={"text": user_input, "thread_id": st.session_state.thread_id},
            timeout=60,
        ).json()["reply"]
    except Exception as e:
        resp = f"Error contacting backend: {e}"
    st.chat_message("assistant").write(resp)
    st.session_state.history.append(("assistant", resp))
