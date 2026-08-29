from __future__ import annotations

from dataclasses import dataclass, field

from openai import OpenAI


@dataclass
class LLMClient:
    """Thin wrapper around any OpenAI-compatible chat endpoint (Nosana's vLLM
    job exposes exactly this interface, so this same client works whether it's
    pointed at Nosana, a local vLLM/Ollama instance, or a real OpenAI key)."""

    base_url: str
    api_key: str
    model: str
    _client: OpenAI = field(init=False, repr=False)

    def __post_init__(self) -> None:
        base_url = self.base_url.rstrip("/")
        if not base_url.endswith("/v1"):
            base_url += "/v1"
        self._client = OpenAI(base_url=base_url, api_key=self.api_key or "not-needed")

    def complete(self, system: str, user: str, temperature: float = 0.2) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or ""
