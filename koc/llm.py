from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import get_config_value


PostJson = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class LlmHealthCheck:
    ok: bool
    model: str
    base_url: str
    error_type: str | None = None
    message: str | None = None


class LlmClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int = 60,
        post_json: PostJson | None = None,
        max_retries: int = 2,
        backoff_seconds: float = 1.0,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else get_config_value("AI_API_KEY")
        self.base_url = (base_url or get_config_value("AI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.model = model or get_config_value("AI_MODEL") or "gpt-4o-mini"
        self.timeout = timeout
        self._post_json = post_json or self._urlopen_post_json
        self.max_retries = max(0, max_retries)
        self.backoff_seconds = max(0.0, backoff_seconds)
        self._sleep = sleep or time.sleep

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def health_check(self) -> LlmHealthCheck:
        if not self.api_key:
            return LlmHealthCheck(
                ok=False,
                model=self.model,
                base_url=self.base_url,
                error_type="MissingApiKey",
                message="AI_API_KEY is not configured",
            )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": 'Return only this JSON: {"ok": true}'},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": 50,
        }
        try:
            data = self._post_json(payload)
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            if parsed.get("ok") is True:
                return LlmHealthCheck(ok=True, model=self.model, base_url=self.base_url)
            return LlmHealthCheck(
                ok=False,
                model=self.model,
                base_url=self.base_url,
                error_type="InvalidHealthResponse",
                message=str(parsed),
            )
        except Exception as exc:
            return LlmHealthCheck(
                ok=False,
                model=self.model,
                base_url=self.base_url,
                error_type=exc.__class__.__name__,
                message=_error_message(exc),
            )

    def chat_json(self, system_prompt: str, user_prompt: str) -> dict:
        if not self.api_key:
            raise RuntimeError("AI_API_KEY is not configured")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        data = self._post_json_with_retry(payload)
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)

    def _post_json_with_retry(self, payload: dict[str, Any]) -> dict[str, Any]:
        attempts = self.max_retries + 1
        last_exc: Exception | None = None
        for attempt in range(attempts):
            try:
                return self._post_json(payload)
            except Exception as exc:
                last_exc = exc
                if attempt >= attempts - 1 or not _is_transient_error(exc):
                    raise
                delay = self.backoff_seconds * (2 ** attempt)
                if delay > 0:
                    self._sleep(delay)
        assert last_exc is not None
        raise last_exc

    def _urlopen_post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))


def _error_message(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        if body:
            return f"HTTP {exc.code}: {body[:500]}"
        return f"HTTP {exc.code}: {exc.reason}"
    return str(exc)


def _is_transient_error(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, URLError):
        return True
    if isinstance(exc, HTTPError):
        return exc.code in {429, 500, 502, 503, 504}
    text = str(exc).lower()
    return any(token in text for token in ["timeout", "timed out", "429", "503", "502", "504"])
