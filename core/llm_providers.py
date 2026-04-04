"""
LLM 프로바이더 추상화 + Gemini 구현.

asyncio 기반. QThread 내부에서 asyncio.run()으로 호출.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMResponse:
    """LLM API 응답."""
    text: str
    model: str
    input_tokens: int
    output_tokens: int


class LLMProvider(ABC):
    """LLM 프로바이더 인터페이스."""

    @abstractmethod
    async def translate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        ...

    @abstractmethod
    async def validate_key(self) -> bool:
        """API 키 유효성 검증. 성공 시 True."""
        ...


class GeminiProvider(LLMProvider):
    """Google Gemini 프로바이더."""

    def __init__(self, api_key: str, model: str = "gemini-3-flash-preview"):
        self._api_key = api_key
        self._model = model
        self._client = None

    def _ensure_client(self):
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self._api_key)

    async def translate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        self._ensure_client()
        from google.genai import types

        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        )

        text = response.text or ""
        usage = response.usage_metadata
        return LLMResponse(
            text=text,
            model=self._model,
            input_tokens=usage.prompt_token_count if usage else 0,
            output_tokens=usage.candidates_token_count if usage else 0,
        )

    async def validate_key(self) -> bool:
        try:
            self._ensure_client()
            from google.genai import types

            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents="Say OK",
                config=types.GenerateContentConfig(max_output_tokens=8),
            )
            return bool(response.text)
        except Exception:
            return False


def create_provider(name: str, api_key: str, model: str) -> LLMProvider:
    """프로바이더 팩토리."""
    if name == "gemini":
        return GeminiProvider(api_key=api_key, model=model)
    raise ValueError(f"지원하지 않는 프로바이더: {name}")
