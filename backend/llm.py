import time

import openai
from openai import OpenAI

from .config import settings

_client: OpenAI | None = None

_MAX_ATTEMPTS_PER_MODEL = 2
_RETRY_BACKOFF_SECONDS = 3.0

# Models found to burn max_tokens on reasoning — skip reasoning on sight for them.
_REASONING_OFF_MODELS: set[str] = set()


def get_client() -> OpenAI:
    global _client
    if _client is None:
        if not settings.llm_api_key:
            raise RuntimeError(
                "LLM_API_KEY is not set. Copy .env.example to .env and add your key."
            )
        _client = OpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout_seconds,
            max_retries=0,  # our loop owns retries
        )
    return _client


def _model_chain() -> list[str]:
    chain = [settings.llm_model]
    for part in settings.llm_fallback_model.split(","):
        model = part.strip()
        if model and model not in chain:
            chain.append(model)
    return chain


def _one_call(
    client: OpenAI,
    model: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    disable_reasoning: bool,
) -> str:
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if disable_reasoning or model in _REASONING_OFF_MODELS:
        # Reasoning models can burn the whole max_tokens budget on thinking
        # and return an empty message — ask the provider to skip reasoning.
        kwargs["extra_body"] = {"reasoning": {"enabled": False}}
    response = client.chat.completions.create(**kwargs)
    choice = response.choices[0].message if response.choices else None
    content = (choice.content if choice else None) or ""
    return content.strip()


def chat_completion(messages: list[dict], temperature: float = 0.9, max_tokens: int = 600) -> str:
    """Chat completion with retry, reasoning-model rescue, and model fallback."""
    client = get_client()
    errors: list[str] = []

    for model in _model_chain():
        for attempt in range(_MAX_ATTEMPTS_PER_MODEL):
            try:
                content = _one_call(client, model, messages, temperature, max_tokens, False)
                if content:
                    return content
                content = _one_call(client, model, messages, temperature, max_tokens, True)
                if content:
                    _REASONING_OFF_MODELS.add(model)  # remember: skip reasoning from now on
                    return content
                errors.append(f"{model}: empty completion")
                break  # model responds but yields nothing — try fallback model
            except openai.RateLimitError:
                errors.append(f"{model}: rate limited")
                time.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
            except openai.APIConnectionError:
                errors.append(f"{model}: connection error")
                time.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
            except openai.NotFoundError as exc:
                errors.append(f"{model}: not found ({exc})")
                break  # model removed from provider — try fallback model
            except openai.APIError as exc:
                errors.append(f"{model}: {exc}")
                break

    raise RuntimeError("LLM request failed: " + ("; ".join(errors) or "no models configured"))


def extract_json_prompt(prompt: str) -> str:
    return chat_completion(
        [
            {
                "role": "system",
                "content": "You extract structured data. Reply only with valid JSON, no markdown fences, no commentary.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=500,
    )
