from __future__ import annotations

from abc import ABC
from datetime import UTC, datetime
from decimal import Decimal
import json
from pathlib import Path
import sys

from celery.schedules import crontab
import httpx
import pytest
from sqlalchemy import select


API_ROOT = Path(__file__).resolve().parents[1]

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.celery_app import celery_app
from app.config import Settings
from app.models import EventTag, NewsItem, SentimentScore
from app.services.llm_analysis import (
    AnalysisResult,
    AnalyzerInterface,
    EventTagResult,
    LLMAnalyzer,
    RuleBasedAnalyzer,
    analyze_news_items,
)
from app.tasks.analysis import task_analyze_news


def _news_item(**overrides) -> NewsItem:
    payload = {
        "title": "Gold steady on mixed headlines",
        "summary": None,
        "content": None,
        "published_at": datetime(2026, 4, 1, 10, 0, tzinfo=UTC),
        "title_hash": overrides.pop("title_hash", "a" * 64),
    }
    payload.update(overrides)
    return NewsItem(**payload)


class FakeLLMClient:
    def __init__(
        self,
        *,
        payload: dict[str, object] | None = None,
        exc: Exception | None = None,
        status_code: int = 200,
    ) -> None:
        self.payload = payload or {}
        self.exc = exc
        self.status_code = status_code
        self.requests: list[dict[str, object]] = []

    def post(self, url: str, **kwargs) -> httpx.Response:
        self.requests.append({"url": url, "kwargs": kwargs})
        if self.exc is not None:
            raise self.exc
        request = httpx.Request("POST", url)
        return httpx.Response(self.status_code, json=self.payload, request=request)


class SequenceLLMClient:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, object]] = []

    def post(self, url: str, **kwargs) -> httpx.Response:
        self.requests.append({"url": url, "kwargs": kwargs})
        request = httpx.Request("POST", url)
        payload = self.responses.pop(0)
        return httpx.Response(200, json=payload, request=request)


def _settings_with_llm(**overrides) -> Settings:
    payload = {
        "llm_analysis_enabled": True,
        "llm_provider": "openai",
        "llm_api_key": "test-key",
        "llm_model": "test-model",
        "llm_timeout_seconds": 0.1,
        "llm_endpoint_url": "https://llm.test/v1/chat/completions",
    }
    payload.update(overrides)
    return Settings(**payload)


def _openai_payload(content: str | dict[str, object]) -> dict[str, object]:
    if isinstance(content, dict):
        content = json.dumps(content)
    return {"choices": [{"message": {"content": content}}]}


def _batch_openai_payload(results: list[dict[str, object]]) -> dict[str, object]:
    return _openai_payload({"results": results})


def _disable_follow_on_signals(monkeypatch) -> None:
    monkeypatch.setattr("app.services.llm_analysis.service._generate_follow_on_signals", lambda session, signal_timestamp: 0)


def test_analyzer_interface_exists_for_future_pluggability() -> None:
    assert issubclass(AnalyzerInterface, ABC)
    assert hasattr(RuleBasedAnalyzer, "analyze")


def test_rule_based_analyzer_emits_positive_sentiment_and_multiple_event_tags() -> None:
    analyzer = RuleBasedAnalyzer()
    item = _news_item(
        title="Fed rate cut talk grows as inflation cools amid war fears",
        content="The Fed may signal a rate cut while war risk supports safe haven demand.",
    )

    result = analyzer.analyze(item)

    assert result.analyzer_type == "rule_based"
    assert result.sentiment == "positive"
    assert result.score > Decimal("0")
    assert {tag.tag_value for tag in result.event_tags} >= {"fed_policy", "fed_rate_cut", "inflation_watch", "war_escalation"}


def test_rule_based_analyzer_emits_negative_sentiment() -> None:
    analyzer = RuleBasedAnalyzer()
    item = _news_item(
        title="Strong dollar rises after hawkish Fed comments",
        content="Markets brace for a rate hike as treasury yields rise.",
        title_hash="b" * 64,
    )

    result = analyzer.analyze(item)

    assert result.sentiment == "negative"
    assert result.score < Decimal("0")
    assert "negative keywords" in result.reasoning


def test_rule_based_analyzer_defaults_to_neutral_for_empty_text() -> None:
    analyzer = RuleBasedAnalyzer()
    item = _news_item(title=" ", summary=" ", content=None, title_hash="c" * 64)

    result = analyzer.analyze(item)

    assert result.sentiment == "neutral"
    assert result.score == Decimal("0.0000")
    assert result.event_tags == ()


def test_llm_analyzer_without_api_key_falls_back_to_rule_based_without_client_call() -> None:
    client = FakeLLMClient(payload=_openai_payload({"sentiment": "positive"}))
    analyzer = LLMAnalyzer(settings=_settings_with_llm(llm_api_key=""), client=client)
    item = _news_item(title="Fed rate cut supports gold", content="Safe haven demand rises.", title_hash="ca" * 32)

    result = analyzer.analyze(item)

    assert result.analyzer_type == "rule_based"
    assert result.score > Decimal("0")
    assert result.metadata["fallback_from"] == "llm"
    assert result.metadata["fallback_reason"] == "missing_api_key"
    assert client.requests == []


def test_llm_analyzer_timeout_falls_back_to_rule_based() -> None:
    analyzer = LLMAnalyzer(
        settings=_settings_with_llm(),
        client=FakeLLMClient(exc=httpx.TimeoutException("timed out")),
    )
    item = _news_item(title="Hawkish Fed pressure builds", content="Strong dollar weighs on gold.", title_hash="cb" * 32)

    result = analyzer.analyze(item)

    assert result.analyzer_type == "rule_based"
    assert result.sentiment == "negative"
    assert result.metadata["fallback_reason"] == "llm_analysis_failed"


def test_llm_analyzer_http_error_falls_back_to_rule_based() -> None:
    analyzer = LLMAnalyzer(settings=_settings_with_llm(), client=FakeLLMClient(status_code=500))
    item = _news_item(title="Inflation cools", content="Fed rate cut odds rise.", title_hash="cc" * 32)

    result = analyzer.analyze(item)

    assert result.analyzer_type == "rule_based"
    assert result.metadata["fallback_from"] == "llm"


def test_llm_analyzer_invalid_json_falls_back_to_rule_based() -> None:
    analyzer = LLMAnalyzer(settings=_settings_with_llm(), client=FakeLLMClient(payload=_openai_payload("not json")))
    item = _news_item(title="CPI due later", content="Inflation watch continues.", title_hash="cd" * 32)

    result = analyzer.analyze(item)

    assert result.analyzer_type == "rule_based"
    assert result.metadata["fallback_reason"] == "llm_analysis_failed"


def test_llm_analyzer_invalid_schema_falls_back_to_rule_based() -> None:
    analyzer = LLMAnalyzer(
        settings=_settings_with_llm(),
        client=FakeLLMClient(
            payload=_openai_payload(
                {
                    "sentiment": "positive",
                    "score": "1.5000",
                    "confidence": "0.7000",
                    "reasoning": "Out-of-range score should be rejected.",
                    "event_tags": [],
                }
            )
        ),
    )
    item = _news_item(title="Fed rate cut talk grows", content="Dovish comments support gold.", title_hash="ce" * 32)

    result = analyzer.analyze(item)

    assert result.analyzer_type == "rule_based"
    assert result.metadata["fallback_reason"] == "llm_analysis_failed"
    assert result.metadata["fallback_error_type"] == "ValueError"
    assert result.metadata["fallback_error_message"] == "Decimal field is out of range."


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("sentiment", {"value": "positive"}),
        ("reasoning", ["non-string reasoning"]),
    ],
)
def test_llm_analyzer_non_string_top_level_string_fields_fall_back_to_rule_based(
    field_name: str,
    field_value: object,
) -> None:
    payload: dict[str, object] = {
        "sentiment": "positive",
        "score": "0.7000",
        "confidence": "0.8000",
        "reasoning": "Dovish comments support gold.",
        "event_tags": [],
    }
    payload[field_name] = field_value
    analyzer = LLMAnalyzer(
        settings=_settings_with_llm(),
        client=FakeLLMClient(payload=_openai_payload(payload)),
    )
    item = _news_item(
        title="Fed rate cut talk grows",
        content="Dovish comments support gold.",
        title_hash="c1" * 32,
    )

    result = analyzer.analyze(item)

    assert result.analyzer_type == "rule_based"
    assert result.metadata["fallback_from"] == "llm"
    assert result.metadata["fallback_reason"] == "llm_analysis_failed"


@pytest.mark.parametrize(
    "tag_patch",
    [
        {"tag_type": 123},
        {"tag_value": ["fed_rate_cut"]},
    ],
)
def test_llm_analyzer_non_string_event_tag_fields_fall_back_to_rule_based(tag_patch: dict[str, object]) -> None:
    event_tag: dict[str, object] = {
        "tag_type": "monetary_policy",
        "tag_value": "fed_rate_cut",
        "relevance_score": "0.9000",
    }
    event_tag.update(tag_patch)
    analyzer = LLMAnalyzer(
        settings=_settings_with_llm(),
        client=FakeLLMClient(
            payload=_openai_payload(
                {
                    "sentiment": "positive",
                    "score": "0.7000",
                    "confidence": "0.8000",
                    "reasoning": "Dovish comments support gold.",
                    "event_tags": [event_tag],
                }
            )
        ),
    )
    item = _news_item(
        title="Fed rate cut talk grows",
        content="Dovish comments support gold.",
        title_hash="c2" * 32,
    )

    result = analyzer.analyze(item)

    assert result.analyzer_type == "rule_based"
    assert result.metadata["fallback_from"] == "llm"
    assert result.metadata["fallback_reason"] == "llm_analysis_failed"


def test_llm_analyzer_success_returns_decimal_result_and_event_tags() -> None:
    client = FakeLLMClient(
        payload=_openai_payload(
            {
                "sentiment": "positive",
                "score": "0.62555",
                "confidence": "0.80123",
                "reasoning": "Dovish policy expectations are supportive for gold.",
                "event_tags": [
                    {
                        "tag_type": "monetary_policy",
                        "tag_value": "fed_rate_cut",
                        "relevance_score": "0.91234",
                    }
                ],
            }
        )
    )
    analyzer = LLMAnalyzer(settings=_settings_with_llm(), client=client)
    item = _news_item(title="Fed rate cut talk grows", content="Dovish comments support gold.", title_hash="cf" * 32)

    result = analyzer.analyze(item)

    assert result.analyzer_type == "llm_openai"
    assert result.sentiment == "positive"
    assert result.score == Decimal("0.6256")
    assert result.confidence == Decimal("0.8012")
    assert result.event_tags[0].relevance_score == Decimal("0.9123")
    assert client.requests[0]["url"] == "https://llm.test/v1/chat/completions"
    assert client.requests[0]["kwargs"]["json"]["response_format"] == {"type": "json_object"}


def test_llm_analyzer_retries_transient_empty_choices_before_fallback() -> None:
    client = SequenceLLMClient(
        [
            {"choices": []},
            _openai_payload(
                {
                    "sentiment": "positive",
                    "score": "0.6200",
                    "confidence": "0.8200",
                    "reasoning": "Retry recovered after an empty provider response.",
                    "event_tags": [],
                }
            ),
        ]
    )
    analyzer = LLMAnalyzer(settings=_settings_with_llm(llm_max_retries=1), client=client)
    item = _news_item(title="Fed rate cut supports gold", content="Dollar slips.", title_hash="c0" * 32)

    result = analyzer.analyze(item)

    assert result.analyzer_type == "llm_openai"
    assert result.sentiment == "positive"
    assert len(client.requests) == 2


def test_llm_analyzer_omits_response_format_for_modelscope_endpoint() -> None:
    client = FakeLLMClient(
        payload=_openai_payload(
            {
                "sentiment": "positive",
                "score": "0.5000",
                "confidence": "0.7500",
                "reasoning": "Dollar weakness supports gold.",
                "event_tags": [],
            }
        )
    )
    analyzer = LLMAnalyzer(
        settings=_settings_with_llm(
            llm_endpoint_url="https://api-inference.modelscope.cn/v1/chat/completions",
        ),
        client=client,
    )
    item = _news_item(title="Dollar slips and gold rises", title_hash="cd" * 32)

    result = analyzer.analyze(item)

    assert result.analyzer_type == "llm_openai"
    assert "response_format" not in client.requests[0]["kwargs"]["json"]


def test_llm_analyzer_reuses_cached_result_for_equivalent_normalized_news_text() -> None:
    client = FakeLLMClient(
        payload=_openai_payload(
            {
                "sentiment": "positive",
                "score": "0.7000",
                "confidence": "0.9000",
                "reasoning": "Equivalent text should reuse cached LLM output.",
                "event_tags": [],
            }
        )
    )
    analyzer = LLMAnalyzer(
        settings=_settings_with_llm(
            llm_cache_enabled=True,
        ),
        client=client,
    )
    first_item = _news_item(
        title="Fed rate cut supports gold",
        content="Safe haven demand rises.",
        title_hash="c3" * 32,
    )
    second_item = _news_item(
        title="  FED rate cut supports   gold ",
        content="Safe haven demand rises.",
        title_hash="c4" * 32,
    )

    first_result = analyzer.analyze(first_item)
    second_result = analyzer.analyze(second_item)

    assert first_result.analyzer_type == "llm_openai"
    assert second_result.analyzer_type == "llm_openai"
    assert second_result.metadata["llm_cache_hit"] is True
    assert len(client.requests) == 1


def test_llm_analyzer_budget_exhaustion_falls_back_without_provider_call() -> None:
    client = FakeLLMClient(payload=_openai_payload({"sentiment": "positive"}))
    analyzer = LLMAnalyzer(
        settings=_settings_with_llm(
            llm_daily_budget_usd=Decimal("0.0000"),
        ),
        client=client,
    )
    item = _news_item(
        title="Fed rate cut supports gold",
        content="Safe haven demand rises.",
        title_hash="c5" * 32,
    )

    result = analyzer.analyze(item)

    assert result.analyzer_type == "rule_based"
    assert result.metadata["fallback_reason"] == "daily_budget_exceeded"
    assert result.metadata["llm_fallback_reason_counts"]["daily_budget_exceeded"] == 1
    assert client.requests == []


def test_llm_analyzer_fallback_metadata_tracks_reason_counts() -> None:
    analyzer = LLMAnalyzer(
        settings=_settings_with_llm(),
        client=FakeLLMClient(payload=_openai_payload("not json")),
    )
    first_item = _news_item(title="CPI due later", content="Inflation watch continues.", title_hash="c6" * 32)
    second_item = _news_item(title="Yields rise", content="Dollar strength hurts gold.", title_hash="c7" * 32)

    first_result = analyzer.analyze(first_item)
    second_result = analyzer.analyze(second_item)

    assert first_result.metadata["llm_fallback_reason_counts"]["llm_analysis_failed"] == 1
    assert second_result.metadata["llm_fallback_reason_counts"]["llm_analysis_failed"] == 2


def test_llm_analyzer_batch_path_returns_partial_fallbacks_per_item() -> None:
    client = FakeLLMClient(
        payload=_batch_openai_payload(
            [
                {
                    "sentiment": "positive",
                    "score": "0.7000",
                    "confidence": "0.9000",
                    "reasoning": "Dovish policy expectations support gold.",
                    "event_tags": [],
                },
                {
                    "sentiment": "positive",
                },
            ]
        )
    )
    analyzer = LLMAnalyzer(
        settings=_settings_with_llm(
            llm_batch_enabled=True,
            llm_batch_max_items=4,
        ),
        client=client,
    )
    items = [
        _news_item(title="Fed rate cut supports gold", content="Safe haven demand rises.", title_hash="c8" * 32),
        _news_item(title="Dollar rises", content="Yields pressure bullion.", title_hash="c9" * 32),
    ]

    results = analyzer.analyze_batch(items)

    assert len(results) == 2
    assert results[0].analyzer_type == "llm_openai"
    assert results[1].analyzer_type == "rule_based"
    assert results[1].metadata["fallback_reason"] == "llm_analysis_failed"
    assert len(client.requests) == 1



def test_analyze_news_items_persists_sentiment_tags_and_updates_status(db_session, monkeypatch) -> None:
    _disable_follow_on_signals(monkeypatch)
    item = _news_item(
        title="Fed rate cut talk grows as inflation cools",
        content="Fed officials lean dovish and inflation slows.",
        title_hash="d" * 64,
    )
    db_session.add(item)
    db_session.commit()

    summary = analyze_news_items(db_session)

    db_session.refresh(item)
    sentiments = db_session.execute(select(SentimentScore)).scalars().all()
    event_tags = db_session.execute(select(EventTag)).scalars().all()

    assert summary.items_seen == 1
    assert summary.items_analyzed == 1
    assert summary.items_failed == 0
    assert summary.sentiments_created == 1
    assert summary.event_tags_created >= 2
    assert item.status == "analyzed"
    assert sentiments[0].analyzer_type == "rule_based"
    assert isinstance(sentiments[0].score, Decimal)
    assert sentiments[0].created_at.tzinfo == UTC
    assert all(isinstance(tag.relevance_score, Decimal) for tag in event_tags)


def test_analyze_news_items_with_llm_success_persists_decimal_sentiment_and_tags(db_session, monkeypatch) -> None:
    _disable_follow_on_signals(monkeypatch)
    item = _news_item(
        title="Fed rate cut talk grows as inflation cools",
        content="Fed officials lean dovish and inflation slows.",
        title_hash="d1" * 32,
    )
    db_session.add(item)
    db_session.commit()
    analyzer = LLMAnalyzer(
        settings=_settings_with_llm(),
        client=FakeLLMClient(
            payload=_openai_payload(
                {
                    "sentiment": "positive",
                    "score": "0.7000",
                    "confidence": "0.9000",
                    "reasoning": "The headline points to easier policy expectations.",
                    "event_tags": [
                        {
                            "tag_type": "monetary_policy",
                            "tag_value": "fed_rate_cut",
                            "relevance_score": "0.9500",
                        }
                    ],
                }
            )
        ),
    )

    summary = analyze_news_items(db_session, analyzer=analyzer)

    db_session.refresh(item)
    sentiment = db_session.execute(select(SentimentScore)).scalar_one()
    event_tag = db_session.execute(select(EventTag)).scalar_one()

    assert summary.items_analyzed == 1
    assert summary.items_failed == 0
    assert item.status == "analyzed"
    assert sentiment.analyzer_type == "llm_openai"
    assert sentiment.score == Decimal("0.7000")
    assert sentiment.confidence == Decimal("0.9000")
    assert event_tag.relevance_score == Decimal("0.9500")


def test_analyze_news_items_with_llm_failure_uses_fallback_without_marking_failed(db_session, monkeypatch) -> None:
    _disable_follow_on_signals(monkeypatch)
    item = _news_item(
        title="Strong dollar rises after hawkish Fed comments",
        content="Markets brace for a rate hike as treasury yields rise.",
        title_hash="d2" * 32,
    )
    db_session.add(item)
    db_session.commit()
    analyzer = LLMAnalyzer(settings=_settings_with_llm(), client=FakeLLMClient(payload=_openai_payload("not json")))

    summary = analyze_news_items(db_session, analyzer=analyzer)

    db_session.refresh(item)
    sentiment = db_session.execute(select(SentimentScore)).scalar_one()

    assert summary.items_analyzed == 1
    assert summary.items_failed == 0
    assert item.status == "analyzed"
    assert sentiment.analyzer_type == "rule_based"
    assert sentiment.metadata_json["fallback_from"] == "llm"


def test_batch_results_if_supported_prefers_analyze_batch() -> None:
    from app.services.llm_analysis.service import _batch_results_if_supported

    class BatchAnalyzer(AnalyzerInterface):
        analyzer_type = "batch_stub"

        def __init__(self) -> None:
            self.batch_calls = 0
            self.single_calls = 0

        def analyze(self, item: NewsItem) -> AnalysisResult:
            self.single_calls += 1
            raise AssertionError("single-item path should not be used")

        def analyze_batch(self, items: list[NewsItem]) -> tuple[AnalysisResult, ...]:
            self.batch_calls += 1
            return tuple(
                AnalysisResult(
                    analyzer_type=self.analyzer_type,
                    sentiment="neutral",
                    score=Decimal("0.0000"),
                    confidence=Decimal("0.5000"),
                    reasoning=f"batch:{index}",
                    metadata={"mode": "batch"},
                    event_tags=(),
                )
                for index, _item in enumerate(items)
            )

    items = [
        _news_item(title="Item one", content="Fed holds rates.", title_hash="da" * 32),
        _news_item(title="Item two", content="Gold trades sideways.", title_hash="db" * 32),
    ]
    analyzer = BatchAnalyzer()

    results = _batch_results_if_supported(analyzer, items)

    assert results is not None
    assert len(results) == 2
    assert analyzer.batch_calls == 1
    assert analyzer.single_calls == 0
    assert [result.metadata["mode"] for result in results] == ["batch", "batch"]


def test_analyze_news_items_marks_failure_and_preserves_status_machine(db_session, monkeypatch) -> None:
    _disable_follow_on_signals(monkeypatch)
    class BrokenAnalyzer(AnalyzerInterface):
        analyzer_type = "broken"

        def analyze(self, item: NewsItem) -> AnalysisResult:
            raise RuntimeError("boom")

    item = _news_item(title="Inflation watch", content="CPI due", title_hash="e" * 64)
    db_session.add(item)
    db_session.commit()

    summary = analyze_news_items(db_session, analyzer=BrokenAnalyzer())

    db_session.refresh(item)

    assert summary.items_seen == 1
    assert summary.items_analyzed == 0
    assert summary.items_failed == 1
    assert item.status == "failed"
    assert db_session.execute(select(SentimentScore)).scalars().all() == []

    retry_summary = analyze_news_items(db_session, analyzer=BrokenAnalyzer())

    db_session.refresh(item)
    assert retry_summary.items_seen == 0
    assert retry_summary.items_analyzed == 0
    assert retry_summary.items_failed == 0
    assert item.status == "failed"


def test_analyze_news_items_accepts_custom_analyzer_for_pluggability(db_session, monkeypatch) -> None:
    _disable_follow_on_signals(monkeypatch)
    class StubAnalyzer(AnalyzerInterface):
        analyzer_type = "stub_rule"

        def analyze(self, item: NewsItem) -> AnalysisResult:
            return AnalysisResult(
                analyzer_type=self.analyzer_type,
                sentiment="neutral",
                score=Decimal("0.1000"),
                confidence=Decimal("0.7000"),
                reasoning="Injected analyzer output.",
                metadata={"source": "stub"},
                event_tags=(
                    EventTagResult(
                        tag_type="economic_data",
                        tag_value="cpi_release",
                        relevance_score=Decimal("0.8000"),
                        metadata={"matched_keyword": "cpi"},
                    ),
                ),
            )

    item = _news_item(title="CPI due later today", content="CPI release ahead.", title_hash="f" * 64)
    db_session.add(item)
    db_session.commit()

    summary = analyze_news_items(db_session, analyzer=StubAnalyzer())

    db_session.refresh(item)
    sentiment = db_session.execute(select(SentimentScore)).scalar_one()
    event_tag = db_session.execute(select(EventTag)).scalar_one()

    assert summary.items_analyzed == 1
    assert item.status == "analyzed"
    assert sentiment.analyzer_type == "stub_rule"
    assert sentiment.metadata_json["source"] == "stub"
    assert event_tag.tag_value == "cpi_release"
    assert event_tag.metadata_json["matched_keyword"] == "cpi"


def test_analyze_news_items_skips_already_analyzed_rows(db_session, monkeypatch) -> None:
    _disable_follow_on_signals(monkeypatch)
    class CountingAnalyzer(AnalyzerInterface):
        analyzer_type = "counting"

        def __init__(self) -> None:
            self.calls = 0

        def analyze(self, item: NewsItem) -> AnalysisResult:
            self.calls += 1
            return AnalysisResult(
                analyzer_type=self.analyzer_type,
                sentiment="neutral",
                score=Decimal("0.0000"),
                confidence=Decimal("0.5000"),
                reasoning="Should not be used for analyzed rows.",
                metadata={},
                event_tags=(),
            )

    item = _news_item(
        title="Already analyzed item",
        content="Fed pricing is unchanged.",
        title_hash="fa" * 32,
        status="analyzed",
    )
    db_session.add(item)
    db_session.commit()

    analyzer = CountingAnalyzer()
    summary = analyze_news_items(db_session, analyzer=analyzer)

    db_session.refresh(item)

    assert summary.items_seen == 0
    assert summary.items_analyzed == 0
    assert summary.items_failed == 0
    assert analyzer.calls == 0
    assert item.status == "analyzed"
    assert db_session.execute(select(SentimentScore)).scalars().all() == []
    assert db_session.execute(select(EventTag)).scalars().all() == []


def test_task_analyze_news_runs_without_real_broker(monkeypatch) -> None:
    class FakeSession:
        def close(self) -> None:
            return None

    class FakeSessionFactory:
        def configure(self, **kwargs) -> None:
            return None

        def __call__(self) -> FakeSession:
            return FakeSession()

    class FakeEngine:
        def dispose(self) -> None:
            return None

    captured = {}
    analyzer = object()

    monkeypatch.setattr("app.tasks.analysis.get_engine", lambda: FakeEngine())
    monkeypatch.setattr("app.tasks.analysis.SessionLocal", FakeSessionFactory())
    monkeypatch.setattr("app.tasks.analysis.get_settings", lambda: _settings_with_llm())
    monkeypatch.setattr("app.tasks.analysis.build_default_analyzer", lambda settings: analyzer)

    def fake_analyze_news_items(session, *, analyzer=None, limit=100):
        captured["analyzer"] = analyzer
        captured["limit"] = limit
        return type(
            "Summary",
            (),
            {
                "items_seen": 2,
                "items_analyzed": 1,
                "items_failed": 1,
                "sentiments_created": 1,
                "event_tags_created": 2,
            },
        )()

    monkeypatch.setattr(
        "app.tasks.analysis.analyze_news_items",
        fake_analyze_news_items,
    )

    result = task_analyze_news(limit=50)

    assert result["items_seen"] == 2
    assert result["items_failed"] == 1
    assert result["event_tags_created"] == 2
    assert captured["analyzer"] is analyzer
    assert captured["limit"] == 50


def test_celery_beat_schedule_wires_analysis_tasks_in_utc() -> None:
    schedule = celery_app.conf.beat_schedule

    assert schedule["analyze-pending-news-every-10min"]["task"] == "app.tasks.analysis.task_analyze_news"
    assert schedule["analyze-pending-news-every-10min"]["schedule"] == crontab(minute="*/10")
    assert "retry-failed-news-analysis-hourly" not in schedule
    assert celery_app.conf.enable_utc is True
    assert celery_app.conf.timezone == "UTC"
