from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = {".venv", ".git", "models", "__pycache__", ".pytest_cache", "assets", "tests"}
IMPORT_RE = re.compile(
    r"^\s*(?:from|import)\s+(openai|langchain|langchain_openai|langgraph)\b",
    re.MULTILINE,
)


def _python_files():
    for path in ROOT.rglob("*.py"):
        if any(part in SKIP for part in path.parts):
            continue
        yield path


def test_no_openai_or_langchain_imports():
    offenders = []
    for path in _python_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if IMPORT_RE.search(text):
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"forbidden LLM imports in: {offenders}"


def test_requirements_are_groq_only():
    lines = [
        line.strip().lower()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    text = "\n".join(lines)
    for forbidden in ("openai", "langchain", "langgraph"):
        assert forbidden not in text
    assert "groq" in text


def test_retired_groq_model_is_not_referenced():
    offenders = []
    for path in _python_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "llama-3.3-70b" in text or "llama-3.1-8b" in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"retired Groq models referenced in: {offenders}"
