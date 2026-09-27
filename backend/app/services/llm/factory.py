"""Build the fallback chain from settings. Providers without the required env are skipped."""

import logging

import httpx

from app.core.config import Settings
from app.services.llm.base import LLMProvider
from app.services.llm.fallback import FallbackLLM
from app.services.llm.gemini import GeminiProvider
from app.services.llm.groq import GroqProvider
from app.services.llm.ollama import OllamaProvider
from app.services.llm.retry import RetryPolicy

logger = logging.getLogger(__name__)

KNOWN_PROVIDERS = ("groq", "gemini", "ollama")


def build_providers(settings: Settings, client: httpx.AsyncClient) -> list[LLMProvider]:
    providers: list[LLMProvider] = []
    timeout = settings.llm_timeout_seconds
    for name in settings.llm_provider_order:
        if name == "groq" and settings.groq_api_key and settings.groq_model:
            providers.append(
                GroqProvider(
                    client,
                    api_key=settings.groq_api_key.get_secret_value(),
                    model=settings.groq_model,
                    base_url=settings.groq_base_url,
                    timeout=timeout,
                )
            )
        elif name == "gemini" and settings.gemini_api_key and settings.gemini_model:
            providers.append(
                GeminiProvider(
                    client,
                    api_key=settings.gemini_api_key.get_secret_value(),
                    model=settings.gemini_model,
                    base_url=settings.gemini_base_url,
                    timeout=timeout,
                )
            )
        elif name == "ollama" and settings.ollama_model:
            providers.append(
                OllamaProvider(
                    client,
                    model=settings.ollama_model,
                    base_url=settings.ollama_base_url,
                    timeout=timeout,
                )
            )
        elif name in KNOWN_PROVIDERS:
            logger.info("llm_provider_not_configured", extra={"provider": name})
        else:
            logger.warning("llm_provider_unknown", extra={"provider": name})
    return providers


def build_llm(settings: Settings, client: httpx.AsyncClient) -> FallbackLLM:
    providers = build_providers(settings, client)
    logger.info("llm_chain", extra={"providers": [f"{p.name}:{p.model}" for p in providers]})
    return FallbackLLM(
        providers,
        RetryPolicy(
            attempts=settings.llm_max_attempts,
            base_delay=settings.llm_backoff_base_seconds,
            max_delay=settings.llm_backoff_max_seconds,
        ),
    )
