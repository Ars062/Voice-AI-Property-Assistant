# API

Base URL: `http://127.0.0.1:8000` (interactive docs at `/docs`).

All endpoints return JSON unless noted. Errors use FastAPI's standard
`{"detail": "..."}` body.

## GET /

```json
{
  "service": "Voice AI Property Assistant",
  "version": "1.0.0",
  "docs": "/docs",
  "model": "qwen/qwen3.8-27b"
}
```

## GET /health

`200` when the database is reachable, `503` otherwise.

```json
{
  "status": "ok",
  "database": {
    "ok": true,
    "database": "voice_property",
    "counts": {"properties": 3, "rooms": 12, "amenities": 10, "policies": 9}
  },
  "llm": {"provider": "groq", "model": "qwen/qwen3.8-27b", "configured": true},
  "tts": {
    "configured": "auto",
    "piper_available": false,
    "piper_model": "D:\\AI-VOICE\\models\\piper\\en_US-lessac-medium.onnx",
    "sapi_available": true
  },
  "avatar": {
    "configured": "auto",
    "cpu_render_fps": 6,
    "fps": 25,
    "musetalk_ready": false,
    "musetalk_reason": "MuseTalk weights missing: ..."
  }
}
```

## GET /meta

Non-secret runtime configuration (model, TTS/avatar availability, limits).

## POST /chat

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/chat -ContentType application/json -Body (@{
  message = "2 bedroom with parking in Austin under 1800"
  session_id = "demo-1"
  speak = $true
  avatar = $true
} | ConvertTo-Json)
```

Body:

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `message` | string | required | 1–2000 chars |
| `session_id` | string | `null` | omit to start a new session; reuse to keep context |
| `speak` | bool | `true` | include base64 WAV |
| `avatar` | bool | `true` | include base64 animated GIF |

Response:

```json
{
  "session_id": "demo-1",
  "reply": "I found 2 matching rooms. Room 3 at Maple Court Apartments ...",
  "rooms": [
    {
      "room_id": 3,
      "unit": "2A",
      "room_type": "2 Bedroom",
      "rent": 1650.0,
      "deposit": 1650.0,
      "size_sqm": 68.0,
      "max_occupants": 3,
      "available_from": "2026-10-22",
      "description": "...",
      "property_id": 1,
      "property_name": "Maple Court Apartments",
      "city": "Austin",
      "region": "TX",
      "address": "...",
      "amenities": ["balcony", "dishwasher", "gym", "parking", "wifi"]
    }
  ],
  "selected_room_id": 3,
  "plan": {
    "city": "Austin",
    "property_name": null,
    "property_type": null,
    "room_type": "2 bedroom",
    "min_rent": null,
    "max_rent": "1800",
    "min_size_sqm": null,
    "min_occupants": null,
    "amenities": ["parking"],
    "available_from": null,
    "available_to": null,
    "sort_by": "rent_asc",
    "limit": 10
  },
  "pending_booking": null,
  "booking": null,
  "error": null,
  "audio": {
    "wav_b64": "UklGRi...",
    "sample_rate": 22050,
    "provider": "sapi"
  },
  "avatar": {
    "available": true,
    "engine": "puppet",
    "gif_b64": "R0lGOD...",
    "fps": 25,
    "frames": 150
  }
}
```

Booking turn:

```json
{
  "reply": "Please confirm: book room 3 at Maple Court Apartments for Jane Doe, from 2027-03-01 to 2027-09-01, at $1650 per month. Reply yes to confirm.",
  "pending_booking": {
    "token": "…",
    "room_id": 3,
    "guest_name": "Jane Doe",
    "check_in": "2027-03-01",
    "check_out": "2027-09-01",
    "property_name": "Maple Court Apartments",
    "rent": 1650.0
  },
  "booking": null
}
```

After `"yes"`:

```json
{
  "reply": "Booked. Your booking id is 4 for room 3 ...",
  "pending_booking": null,
  "booking": {
    "booking_id": 4,
    "room_id": 3,
    "guest_name": "Jane Doe",
    "check_in": "2027-03-01",
    "check_out": "2027-09-01",
    "status": "confirmed",
    "idempotency_key": "demo-1:…",
    "duplicate": false
  }
}
```

## POST /voice

`multipart/form-data`:

| Field | Type | Default |
| --- | --- | --- |
| `audio` | file | required (wav/webm/opus/mp3, ≤15 MB) |
| `session_id` | text | empty |
| `speak` | text bool | `true` |
| `avatar` | text bool | `true` |

```powershell
curl.exe -X POST http://127.0.0.1:8000/voice `
  -F "audio=@question.wav" -F "session_id=demo-1" -F "speak=true" -F "avatar=true"
```

Response is the `/chat` shape plus `transcript`.

Errors: `422` for empty/undecodable audio, `413` for oversize, `503` for LLM
failure.

## POST /stt

`multipart/form-data` with `audio`. Response:

```json
{"text": "two bedroom with parking in austin"}
```

## POST /tts

```json
{"text": "Room 3 is 1650 dollars per month."}
```

Returns `audio/wav` with header `X-TTS-Provider: sapi|piper`. `503` if no TTS is
available.

## GET /rooms

```json
{"count": 12, "plan": {...}, "rooms": [...]}
```

Uses the read-only role and `QUERY_MAX_ROWS`.

## GET /avatar/portrait

Returns `image/png` of the idle puppet portrait (generating
`assets/portrait.png` if missing).

## DELETE /sessions/{session_id}

```json
{"status": "reset", "session_id": "demo-1"}
```

Forgets conversation history, pending bookings and last results.

## Error codes

| Status | Meaning |
| --- | --- |
| `413` | audio upload exceeds 15 MB |
| `422` | validation error or undecodable audio |
| `503` | database, Groq or TTS unavailable |
