# Setup

Tested on Windows 11 with Python 3.12 and Docker Desktop 29.x (WSL 2 backend).

## 1. Prerequisites

| Requirement | Notes |
| --- | --- |
| Python 3.11 or 3.12 | `py -3.12 --version` |
| Docker Desktop | Windows containers are not needed; use the WSL 2 backend |
| Groq API key | <https://console.groq.com/keys> |
| Microphone (optional) | only for the voice UI; text works without it |

Verify Docker:

```powershell
docker version --format '{{.Server.Version}}'
docker compose version
```

If Docker says the daemon is unavailable, open Docker Desktop and wait for
"Engine running". On a fresh machine also run `wsl --install` once and reboot.

## 2. Clone and install

```powershell
git clone https://github.com/Ars062/Voice-AI-Property-Assistant.git
cd Voice-AI-Property-Assistant

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks activation:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

## 3. Configure

```powershell
Copy-Item .env.example .env
notepad .env
```

Set at minimum:

```dotenv
GROQ_API_KEY=gsk_...
GROQ_MODEL=qwen/qwen3.8-27b
```

`qwen/qwen3.8-27b` is the verified model for the development account. Groq
accounts expose different model lists; if you get `404 model_not_found`, list
what your key can use:

```powershell
.\.venv\Scripts\python.exe -c "from groq import Groq; from config import settings; [print(m.id) for m in Groq(api_key=settings.groq_api_key).models.list().data]"
```

Pick a chat-capable model from that list and set `GROQ_MODEL`.

## 4. Start PostgreSQL

```powershell
docker compose up -d
docker compose ps
```

The container is `voice_property_pg`, exposed on host port **5433** to avoid
clashing with a local PostgreSQL on 5432. On first boot the files in `sql/` are
applied automatically (schema, read-only role, seed data).

Wait until it is healthy:

```powershell
.\.venv\Scripts\python.exe scripts\wait_for_db.py
```

## 5. Verify the installation

```powershell
.\.venv\Scripts\python.exe scripts\init_db.py --check
.\.venv\Scripts\python.exe app.py --check
```

Expected: 3 properties, 12 rooms, database and Groq ping OK, SAPI available,
MuseTalk reported as missing (that is fine).

Run the tests:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## 6. Run

Two terminals:

```powershell
# API
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000

# UI
.\.venv\Scripts\python.exe -m streamlit run frontend\streamlit_app.py --server.port 8501
```

Or `scripts\run_windows.cmd`, which creates the venv, installs dependencies,
starts Docker, waits for the database, and launches both processes.

- API docs: <http://127.0.0.1:8000/docs>
- UI: <http://127.0.0.1:8501>

## 7. Optional models

### Whisper

`faster-whisper` downloads the model on the first transcription. To pre-download:

```powershell
.\.venv\Scripts\python.exe scripts\fetch_assets.py --whisper
```

### Piper voice

```powershell
pip install -r requirements-piper.txt
.\.venv\Scripts\python.exe scripts\fetch_assets.py --piper
```

Set `TTS_PROVIDER=auto` (default) or `piper`. If Piper is unavailable the app
uses Windows SAPI. List installed SAPI voices:

```powershell
Add-Type -AssemblyName System.Speech
(New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices() |
  ForEach-Object { $_.VoiceInfo.Name }
```

### MuseTalk avatar (CPU, best effort)

```powershell
pip install -r requirements-avatar.txt
.\.venv\Scripts\python.exe scripts\fetch_assets.py --musetalk
```

The download is large and the resulting layout must match:

```
models/musetalk/
  musetalkV15/unet.pth
  musetalkV15/musetalk.json
  sd-vae-ft-mse/config.json
  sd-vae-ft-mse/diffusion_pytorch_model.bin
  whisper/config.json
  whisper/pytorch_model.bin
  whisper/preprocessor_config.json
```

Place a portrait at `assets/portrait.png` (a real, front-facing photo works
best). Set `AVATAR_ENGINE=musetalk` to force it. Expect 1–3 seconds per rendered
frame on CPU; lower `AVATAR_CPU_RENDER_FPS` (e.g. 4) or `AVATAR_MAX_SECONDS` to
keep replies responsive.

## 8. Moving to another computer

1. Push/pull the repository.
2. Copy your `.env` separately (it is gitignored) or recreate it from
   `.env.example`.
3. `pip install -r requirements.txt`.
4. `docker compose up -d` — the named volume `pgdata` is local to each machine,
   so the database is initialised fresh from `sql/` on first boot.
5. `python scripts\init_db.py --check` then `python app.py --check`.

Do not copy `.venv` between machines; create a new one.

## 9. Reset the database

```powershell
.\.venv\Scripts\python.exe scripts\init_db.py --reset
```

This drops and recreates the application schema and re-seeds it. To remove the
volume entirely:

```powershell
docker compose down -v
docker compose up -d
```

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `docker: error during connect` | Start Docker Desktop; if it hangs, `wsl --shutdown` then relaunch. |
| Docker says "no distros" | `wsl --install`, reboot, then start Docker Desktop. |
| Port 5433 already in use | Change `POSTGRES_PORT` and the port in both database URLs. |
| `404 model_not_found` from Groq | The model is not enabled for your key; list models and update `GROQ_MODEL`. |
| `403 error code: 1010` | Cloudflare rejected a non-browser user agent. The Groq SDK sends a normal one; upgrade `groq` or use the SDK rather than raw `urllib`. |
| Groq `401` | Wrong/expired `GROQ_API_KEY`. |
| First voice request is slow | Whisper downloads the model and loads it once. Pre-download with `fetch_assets.py --whisper`. |
| No microphone in the UI | Streamlit needs a secure context; `localhost` works. Allow microphone permission in the browser. |
| SAPI produces silence | The configured voice is missing; set `TTS_SAPI_VOICE` to an installed voice or leave it blank. |
| Avatar GIF missing | Check `avatar.reason` in the response and `/health`; it is optional and never blocks the text answer. |
| Database tests skipped | Postgres is not running: `docker compose up -d`. |
