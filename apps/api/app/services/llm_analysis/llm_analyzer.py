from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Any, Protocol

import httpx

from app.config import Settings
from app.models import NewsItem
from app.services.llm_analysis.prompts import LLM_ANALYSIS_SYSTEM_PROMPT, build_analysis_prompt
from app.services.llm_analysis.service import AnalysisResult, AnalyzerInterface, EventTagResult, RuleBasedAnalyzer


DECIMAL_QUANT = Decimal("0.0001")
ALLOWED_SENTIMENTS = {"positive", "negative", "neutral"}
ESTIMATED_COST_PER_1K_CHARS_USD = Decimal("0.0010")
DEFAULT_ENDPOINTS = {
    "openai": "https://api.openai.com/v1/chat/completions",
    "anthropic": "https://api.anthropic.com/v1/messages",
}


class _HttpClient(Protocol):
    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        ...


class _LLMControlState:
    def __init__(self) -> None:
        self.cache: dict[str, AnalysisResult] = {}
        self.fallback_reason_counts: dict[str, int] = {}
        self.daily_spend: dict[str, Decimal] = {}


class LLMAnalyzer(AnalyzerInterface):
    analyzer_type = "llm"

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: _HttpClient | None = None,
        fallback_analyzer: AnalyzerInterface | None = None,
        control_state: _LLMControlState | None = None,
    ) -> None:
        self.settings = settings or Settings()
        self.client = client
        self.fallback_analyzer = fallback_analyzer or RuleBasedAnalyzer()
        self.provider = self.settings.llm_provider.strip().lower() or "openai"
        self.model = self.settings.llm_model.strip()
        self.max_retries = max(0, int(self.settings.llm_max_retries))
        self.cache_enabled = bool(self.settings.llm_cache_enabled)
        self.batch_enabled = bool(self.settings.llm_batch_enabled)
        self.batch_max_items = max(1, int(self.settings.llm_batch_max_items))
        self.daily_budget_usd = max(
            Decimal("0.0000"),
            Decimal(str(self.settings.llm_daily_budget_usd)).quantize(DECIMAL_QUANT),
        )
        self.control_state = control_state or _LLMControlState()
        self.endpoint_url = (
            self.settings.llm_endpoint_url.strip()
            or DEFAULT_ENDPOINTS.get(self.provider)
            or DEFAULT_ENDPOINTS["openai"]
        )
        self.analyzer_type = f"llm_{self.provider}"[:30]

    def analyze(self, item: NewsItem) -> AnalysisResult:
        cached_result = self._cached_result(item, batch_size=1)
        if cached_result is not None:
            return cached_result

        if not self.settings.llm_api_key.strip():
            return self._fallback(item, "missing_api_key")

        payload = self._request_payload(item)
        headers = self._request_headers()
        last_error: BaseException | None = None
        for _attempt in range(self.max_retries + 1):
            try:
                if not self._reserve_daily_budget(payload):
                    return self._fallback(item, "daily_budget_exceeded")
                response = self._post(payload, headers)
                response.raise_for_status()
                content = self._response_content(response.json())
                parsed = _parse_json_object(content)
                result = self._analysis_result(parsed)
                self._store_cached_result(item, result)
                return self._decorate_result(result, cache_hit=False, batch_size=1)
            except (httpx.HTTPError, json.JSONDecodeError, ValueError, TypeError, InvalidOperation) as exc:
                last_error = exc

        return self._fallback(item, "llm_analysis_failed", error=last_error)

    def analyze_batch(self, items: Sequence[NewsItem]) -> tuple[AnalysisResult, ...]:
        if not items:
            return ()
        if not self.batch_enabled or len(items) == 1:
            return tuple(self.analyze(item) for item in items)

        results: list[AnalysisResult | None] = [None] * len(items)
        pending: list[tuple[int, NewsItem]] = []
        for index, item in enumerate(items):
            cached_result = self._cached_result(item, batch_size=len(items))
            if cached_result is not None:
                results[index] = cached_result
                continue
            pending.append((index, item))

        for chunk in _chunked(pending, self.batch_max_items):
            chunk_items = [item for _, item in chunk]
            if not self.settings.llm_api_key.strip():
                for index, item in chunk:
                    results[index] = self._fallback(item, "missing_api_key")
                continue

            try:
                payload = self._batch_request_payload(chunk_items)
                if not self._reserve_daily_budget(payload):
                    for index, item in chunk:
                        results[index] = self._fallback(item, "daily_budget_exceeded")
                    continue

                response = self._post(payload, self._request_headers())
                response.raise_for_status()
                content = self._response_content(response.json())
                parsed_results = self._batch_results_payload(content, expected_count=len(chunk))
            except (httpx.HTTPError, json.JSONDecodeError, ValueError, TypeError, InvalidOperation) as exc:
                for index, item in chunk:
                    results[index] = self._fallback(item, "llm_analysis_failed", error=exc)
                continue

            for (index, item), parsed_result in zip(chunk, parsed_results):
                try:
                    result = self._analysis_result(parsed_result)
                    self._store_cached_result(item, result)
                    results[index] = self._decorate_result(result, cache_hit=False, batch_size=len(chunk))
                except (ValueError, TypeError, InvalidOperation) as exc:
                    results[index] = self._fallback(item, "llm_analysis_failed", error=exc)

        finalized_results = [
            result if result is not None else self._fallback(items[index], "llm_analysis_failed")
            for index, result in enumerate(results)
        ]
        return tuple(finalized_results)

    def _post(self, payload: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
        if self.client is not None:
            return self.client.post(
                self.endpoint_url,
                json=payload,
                headers=headers,
                timeout=self.settings.llm_timeout_seconds,
            )

        with httpx.Client(timeout=self.settings.llm_timeout_seconds, follow_redirects=True) as client:
            return client.post(self.endpoint_url, json=payload, headers=headers)

    def _request_headers(self) -> dict[str, str]:
        if self.provider == "anthropic":
            return {
                "content-type": "application/json",
                "x-api-key": self.settings.llm_api_key,
                "anthropic-version": "2023-06-01",
            }
        return {
            "content-type": "application/json",
            "authorization": f"Bearer {self.settings.llm_api_key}",
        }

    def _request_payload(self, item: NewsItem) -> dict[str, Any]:
        user_prompt = build_analysis_prompt(item)
        if self.provider == "anthropic":
            return {
                "model": self.model,
                "max_tokens": 800,
                "system": LLM_ANALYSIS_SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_prompt}],
            }

        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": LLM_ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        }
        if self._supports_response_format():
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _batch_request_payload(self, items: Sequence[NewsItem]) -> dict[str, Any]:
        batch_prompt = self._batch_prompt(items)
        if self.provider == "anthropic":
            return {
                "model": self.model,
                "max_tokens": 1500,
                "system": LLM_ANALYSIS_SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": batch_prompt}],
            }

        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": LLM_ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": batch_prompt},
            ],
        }
        if self._supports_response_format():
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _response_content(self, payload: dict[str, Any]) -> str | dict[str, Any]:
        if "choices" in payload:
            choices = payload["choices"]
            if not isinstance(choices, list) or not choices:
                raise ValueError("LLM response choices must be a non-empty list.")
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, str):
                raise ValueError("LLM response content must be a string.")
            return content

        if "content" in payload and isinstance(payload["content"], list):
            text_parts = [
                block.get("text", "")
                for block in payload["content"]
                if isinstance(block, dict) and isinstance(block.get("text"), str)
            ]
            if not text_parts:
                raise ValueError("Anthropic response content was empty.")
            return "\n".join(text_parts)

        return payload

    def _supports_response_format(self) -> bool:
        return "modelscope.cn" not in self.endpoint_url.lower()

    def _batch_results_payload(self, content: str | dict[str, Any], *, expected_count: int) -> tuple[dict[str, Any], ...]:
        parsed = _parse_json_value(content)
        if not isinstance(parsed, dict):
            raise ValueError("Batch response JSON must be an object.")

        results = parsed.get("results")
        if not isinstance(results, list):
            raise ValueError("Batch response results must be a list.")
        if len(results) != expected_count:
            raise ValueError("Batch response result count mismatch.")

        normalized_results: list[dict[str, Any]] = []
        for entry in results:
            if not isinstance(entry, dict):
                raise ValueError("Batch response entries must be objects.")
            normalized_results.append(entry)
        return tuple(normalized_results)

    def _analysis_result(self, payload: dict[str, Any]) -> AnalysisResult:
        sentiment = _required_string(payload.get("sentiment"), field_name="sentiment").lower()
        if sentiment not in ALLOWED_SENTIMENTS:
            raise ValueError("Invalid sentiment value.")

        event_tags_payload = payload.get("event_tags")
        if not isinstance(event_tags_payload, list):
            raise ValueError("event_tags must be a list.")

        event_tags: list[EventTagResult] = []
        for tag_payload in event_tags_payload:
            if not isinstance(tag_payload, dict):
                raise ValueError("event tag must be an object.")
            tag_type = _required_string(tag_payload.get("tag_type"), field_name="tag_type")
            tag_value = _required_string(tag_payload.get("tag_value"), field_name="tag_value")
            if not tag_type or not tag_value:
                raise ValueError("event tag fields are required.")
            event_tags.append(
                EventTagResult(
                    tag_type=tag_type[:50],
                    tag_value=tag_value[:200],
                    relevance_score=_decimal_in_range(
                        tag_payload.get("relevance_score"),
                        minimum=Decimal("0.0000"),
                        maximum=Decimal("1.0000"),
                    ),
                    metadata={"source": "llm", "provider": self.provider},
                )
            )

        reasoning = _required_string(payload.get("reasoning"), field_name="reasoning")
        if not reasoning:
            raise ValueError("reasoning is required.")

        return AnalysisResult(
            analyzer_type=self.analyzer_type,
            sentiment=sentiment,
            score=_decimal_in_range(
                payload.get("score"),
                minimum=Decimal("-1.0000"),
                maximum=Decimal("1.0000"),
            ),
            confidence=_decimal_in_range(
                payload.get("confidence"),
                minimum=Decimal("0.0000"),
                maximum=Decimal("1.0000"),
            ),
            reasoning=reasoning,
            metadata={"provider": self.provider, "model": self.model},
            event_tags=tuple(event_tags),
        )

    def _fallback(self, item: NewsItem, reason: str, *, error: BaseException | None = None) -> AnalysisResult:
        self.control_state.fallback_reason_counts[reason] = self.control_state.fallback_reason_counts.get(reason, 0) + 1
        result = self.fallback_analyzer.analyze(item)
        metadata = dict(result.metadata)
        metadata["fallback_from"] = "llm"
        metadata["fallback_reason"] = reason
        if error is not None:
            metadata["fallback_error_type"] = type(error).__name__
            metadata["fallback_error_message"] = str(error)[:300]
        metadata["llm_provider"] = self.provider
        metadata["llm_daily_budget_usd"] = format(self.daily_budget_usd, "f")
        metadata["llm_daily_spend_usd"] = format(self._current_daily_spend(), "f")
        metadata["llm_fallback_reason_counts"] = dict(sorted(self.control_state.fallback_reason_counts.items()))
        return replace(result, metadata=metadata)

    def _cached_result(self, item: NewsItem, *, batch_size: int) -> AnalysisResult | None:
        if not self.cache_enabled:
            return None

        fingerprint = _news_item_fingerprint(item)
        cached_result = self.control_state.cache.get(fingerprint)
        if cached_result is None:
            return None
        return self._decorate_result(cached_result, cache_hit=True, batch_size=batch_size)

    def _store_cached_result(self, item: NewsItem, result: AnalysisResult) -> None:
        if not self.cache_enabled:
            return
        self.control_state.cache[_news_item_fingerprint(item)] = result

    def _decorate_result(self, result: AnalysisResult, *, cache_hit: bool, batch_size: int) -> AnalysisResult:
        metadata = dict(result.metadata)
        metadata["llm_cache_hit"] = cache_hit
        metadata["llm_batch_size"] = batch_size
        metadata["llm_daily_budget_usd"] = format(self.daily_budget_usd, "f")
        metadata["llm_daily_spend_usd"] = format(self._current_daily_spend(), "f")
        return replace(result, metadata=metadata)

    def _reserve_daily_budget(self, payload: dict[str, Any]) -> bool:
        estimated_cost = _estimate_payload_cost(payload)
        day_key = _utc_day_key()
        projected_spend = self.control_state.daily_spend.get(day_key, Decimal("0.0000")) + estimated_cost
        if projected_spend > self.daily_budget_usd:
            return False
        self.control_state.daily_spend[day_key] = projected_spend
        return True

    def _current_daily_spend(self) -> Decimal:
        return self.control_state.daily_spend.get(_utc_day_key(), Decimal("0.0000")).quantize(DECIMAL_QUANT)

    def _batch_prompt(self, items: Sequence[NewsItem]) -> str:
        article_prompts = [
            f"Item {index}:\n{build_analysis_prompt(item)}"
            for index, item in enumerate(items)
        ]
        return (
            "Analyze each news item for expected gold price impact.\n"
            "Return a JSON object with a single top-level field named results.\n"
            "results must be an array in the same order as the input items.\n"
            "Each result object must include sentiment, score, confidence, reasoning, and event_tags.\n\n"
            + "\n\n".join(article_prompts)
        )


def _parse_json_object(content: str | dict[str, Any]) -> dict[str, Any]:
    parsed = _parse_json_value(content)
    if not isinstance(parsed, dict):
        raise ValueError("LLM JSON must be an object.")
    return parsed


def _parse_json_value(content: str | dict[str, Any]) -> Any:
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        raise ValueError("LLM content must be a JSON object or string.")

    candidate = content.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            candidate = "\n".join(lines[1:-1]).strip()
            if candidate.lower().startswith("json\n"):
                candidate = candidate[5:].strip()

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return json.loads(_extract_first_json_object(candidate))


def _extract_first_json_object(value: str) -> str:
    start = value.find("{")
    end = value.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in LLM response.")
    return value[start : end + 1]


def _estimate_payload_cost(payload: dict[str, Any]) -> Decimal:
    serialized_payload = json.dumps(payload, sort_keys=True)
    estimated_cost = (
        Decimal(len(serialized_payload)) / Decimal("1000")
    ) * ESTIMATED_COST_PER_1K_CHARS_USD
    return max(DECIMAL_QUANT, estimated_cost.quantize(DECIMAL_QUANT))


def _utc_day_key() -> str:
    return datetime.now(UTC).date().isoformat()


def _news_item_fingerprint(item: NewsItem) -> str:
    parts = [item.title or "", item.summary or "", item.content or ""]
    normalized = " ".join(" ".join(part.split()).lower() for part in parts if part and part.strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _chunked(items: Sequence[tuple[int, NewsItem]], size: int) -> tuple[tuple[tuple[int, NewsItem], ...], ...]:
    return tuple(
        tuple(items[index : index + size])
        for index in range(0, len(items), size)
    )


def _required_string(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")
    return value.strip()


def _decimal_in_range(value: object, *, minimum: Decimal, maximum: Decimal) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError("Decimal field is required.")
    decimal_value = Decimal(str(value)).quantize(DECIMAL_QUANT)
    if decimal_value < minimum or decimal_value > maximum:
        raise ValueError("Decimal field is out of range.")
    return decimal_value
