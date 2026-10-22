"""LLM factory. Supports Groq (default), OpenAI, Gemini, Ollama."""
from __future__ import annotations

from config import settings


def get_llm(temperature: float = 0.2):
    """Return a LangChain chat model based on LLM_PROVIDER."""
    provider = settings.llm_provider.lower()

    if provider == "groq":
        from langchain_openai import ChatOpenAI

        if not settings.groq_api_key:
            raise RuntimeError("GROQ_API_KEY is not set in .env")
        return ChatOpenAI(
            model="llama-3.3-70b-versatile",
            temperature=temperature,
            api_key=settings.groq_api_key,
            base_url="https://api.groq.com/openai/v1",
        )

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set in .env")
        return ChatOpenAI(model="gpt-4o-mini", temperature=temperature,
                          api_key=settings.openai_api_key)

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not set in .env")
        return ChatGoogleGenerativeAI(model="gemini-1.5-flash",
                                      temperature=temperature,
                                      google_api_key=settings.gemini_api_key)

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(model=settings.ollama_model,
                          base_url=settings.ollama_base_url,
                          temperature=temperature)

    raise ValueError(f"Unknown LLM_PROVIDER: {provider}")
