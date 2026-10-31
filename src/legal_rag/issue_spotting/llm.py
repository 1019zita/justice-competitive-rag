"""Small OpenAI-compatible client with auditable contract retries."""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

import requests

from ..data import REPO_ROOT
from .models import IssueSpottingConfig
from .prompts import PromptRepository


@dataclass
class ModelResponse:
    content: Optional[str]
    payload: Optional[Dict[str, Any]]
    provider: Optional[str]
    model: Optional[str]
    usage: Dict[str, Any]
    latency_ms: int
    http_attempts: int
    error: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "usage": self.usage,
            "latency_ms": self.latency_ms,
            "http_attempts": self.http_attempts,
            "error": self.error,
        }


def sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def extract_json_object(content: str) -> Dict[str, Any]:
    value = (content or "").strip()
    if value.startswith("```"):
        value = value.strip("`")
        if value.lower().startswith("json"):
            value = value[4:]
    start = value.find("{")
    end = value.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("model response has no JSON object")
    raw = value[start : end + 1]
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as json_error:
        try:
            import json5  # type: ignore
            parsed = json5.loads(raw)
        except Exception:
            parsed = _close_brackets(raw)
            if parsed is None:
                raise json_error
    if not isinstance(parsed, dict):
        raise ValueError("model response JSON root must be an object")
    return parsed


def _close_brackets(raw: str) -> Optional[Dict[str, Any]]:
    """Best-effort repair for truncated model output: close open brackets."""
    repaired = raw
    for _ in range(6):
        try:
            value = json.loads(repaired)
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            pass
        open_stack: List[str] = []
        in_string = False
        escape = False
        for char in repaired:
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char in "{[":
                open_stack.append(char)
            elif char in "}]":
                if open_stack:
                    open_stack.pop()
        if in_string:
            repaired += '"'
        repaired = repaired.rstrip().rstrip(",")
        for opener in reversed(open_stack):
            repaired += "}" if opener == "{" else "]"
    return None
    if not isinstance(parsed, dict):
        raise ValueError("model response JSON root must be an object")
    return parsed


class ModelClient:
    def __init__(
        self,
        config: IssueSpottingConfig,
        prompts: Optional[PromptRepository] = None,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.config = config
        self.prompts = prompts or PromptRepository(config.prompt_dir)
        self.session = session or requests.Session()
        self.call_records: List[Dict[str, Any]] = []

    def _api_key(self) -> str:
        env_key = os.environ.get(self.config.api_key_env, "").strip()
        if env_key:
            return env_key
        path = Path(self.config.api_key_path)
        if not path.is_absolute():
            path = REPO_ROOT / path
        if not path.is_file():
            raise RuntimeError(
                f"no API key available: set {self.config.api_key_env} or provide {path}"
            )
        if self.config.provider == "openrouter":
            value = path.read_text(encoding="utf-8").strip()
            if not value:
                raise RuntimeError(f"API key file is empty: {path}")
            return value
        if self.config.provider == "omp-f-wb":
            try:
                import yaml

                payload = yaml.safe_load(path.read_text(encoding="utf-8"))
                value = payload["providers"]["f-wb"]["apiKey"]
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"cannot read OMP provider key from {path}: {exc}") from exc
            if not value:
                raise RuntimeError("OMP provider key is empty")
            return str(value)
        raise RuntimeError(f"unsupported issue spotting provider: {self.config.provider}")

    def complete(self, prompt: str, *, json_mode: bool = True) -> ModelResponse:
        key = self._api_key()
        base = self.config.api_base_url.rstrip("/")
        url = base + "/chat/completions"
        body: Dict[str, Any] = {
            "model": self.config.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        started = time.time()
        last_error: Optional[str] = None
        for attempt in range(1, self.config.http_retries + 1):
            try:
                response = self.session.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                    timeout=self.config.timeout_seconds,
                )
                if response.status_code in (429, 500, 502, 503, 504):
                    last_error = f"HTTP {response.status_code}: {response.text[:300]}"
                    if attempt < self.config.http_retries:
                        time.sleep(min(8, 2 ** (attempt - 1)))
                        continue
                    break
                response.raise_for_status()
                payload = response.json()
                if payload.get("error"):
                    last_error = json.dumps(payload["error"], ensure_ascii=False)[:500]
                    if attempt < self.config.http_retries:
                        time.sleep(min(8, 2 ** (attempt - 1)))
                        continue
                    break
                message = payload.get("choices", [{}])[0].get("message", {})
                content = message.get("content")
                if not isinstance(content, str) or not content.strip():
                    last_error = "provider returned empty message content"
                    if attempt < self.config.http_retries:
                        time.sleep(min(8, 2 ** (attempt - 1)))
                        continue
                    break
                return ModelResponse(
                    content=content,
                    payload=payload,
                    provider=payload.get("provider"),
                    model=payload.get("model"),
                    usage=dict(payload.get("usage") or {}),
                    latency_ms=int((time.time() - started) * 1000),
                    http_attempts=attempt,
                    error=None,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < self.config.http_retries:
                    time.sleep(min(8, 2 ** (attempt - 1)))
                    continue
                break
        return ModelResponse(
            content=None,
            payload=None,
            provider=None,
            model=None,
            usage={},
            latency_ms=int((time.time() - started) * 1000),
            http_attempts=self.config.http_retries,
            error=last_error or "provider call failed",
        )

    def call_json(
        self,
        prompt: str,
        validator: Callable[[Mapping[str, Any]], Any],
        *,
        prompt_version: str,
        stage: str,
    ) -> Tuple[Any, Dict[str, Any], str, Optional[Dict[str, Any]]]:
        """Call the model and return parsed value, provenance, raw content, payload."""
        attempts: List[Dict[str, Any]] = []
        current_prompt = prompt
        final_content = ""
        final_payload: Optional[Dict[str, Any]] = None
        final_response: Optional[ModelResponse] = None
        for contract_attempt in range(1, self.config.contract_retries + 1):
            response = self.complete(current_prompt, json_mode=True)
            final_response = response
            final_content = response.content or ""
            final_payload = response.payload
            record: Dict[str, Any] = {
                "stage": stage,
                "prompt_version": prompt_version,
                "contract_attempt": contract_attempt,
                "prompt_sha256": sha256_text(current_prompt),
                "output_sha256": sha256_text(final_content),
                "provider": response.provider,
                "model": response.model,
                "latency_ms": response.latency_ms,
                "http_attempts": response.http_attempts,
                "usage": response.usage,
                "error": response.error,
                "valid": False,
                "validation_errors": [],
            }
            if response.content is None:
                record["validation_errors"] = [response.error or "empty provider response"]
                attempts.append(record)
                continue
            try:
                parsed = extract_json_object(response.content)
                value = validator(parsed)
                record["valid"] = True
                attempts.append(record)
                provenance = {
                    "stage": stage,
                    "prompt_version": prompt_version,
                    "prompt_sha256": sha256_text(current_prompt),
                    "output_sha256": sha256_text(final_content),
                    "provider": response.provider,
                    "model": response.model,
                    "temperature": self.config.temperature,
                    "latency_ms": response.latency_ms,
                    "usage": response.usage,
                    "contract_attempts": attempts,
                }
                self.call_records.append(
                    {
                        "stage": stage,
                        "prompt_version": prompt_version,
                        "prompt": current_prompt,
                        "raw_content": final_content,
                        "provider_payload": final_payload,
                        "provenance": provenance,
                    }
                )
                return value, provenance, final_content, final_payload
            except Exception as exc:  # noqa: BLE001
                errors = getattr(exc, "errors", None) or [f"{type(exc).__name__}: {exc}"]
                record["validation_errors"] = list(errors)
                attempts.append(record)
                if contract_attempt < self.config.contract_retries:
                    repair = self.prompts.render(
                        "REPAIR_V1",
                        {"ERRORS": "\n".join(f"- {error}" for error in errors[:20])},
                    )
                    current_prompt = prompt + "\n\n" + repair
        details = {
            "stage": stage,
            "prompt_version": prompt_version,
            "prompt_sha256": sha256_text(prompt),
            "output_sha256": sha256_text(final_content),
            "provider": final_response.provider if final_response else None,
            "model": final_response.model if final_response else None,
            "temperature": self.config.temperature,
            "contract_attempts": attempts,
        }
        errors = [
            error
            for attempt in attempts
            for error in attempt.get("validation_errors", [])
        ]
        final_errors = errors or ["unknown model contract failure"]
        raise ContractError(
            f"{stage} model output failed contract after {len(attempts)} attempts: "
            + " | ".join(final_errors[:10]),
            errors=final_errors,
        )


# Local import keeps the exception definition in validators.py while avoiding a
# circular import at module load time.
from .validators import ContractError  # noqa: E402  # isort:skip
