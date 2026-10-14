from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import EventTag, NewsItem, SentimentScore
from app.services.signal_engine import generate_signals_for_timestamp


POSITIVE_KEYWORDS: dict[str, Decimal] = {
    "rate cut": Decimal("0.6500"),
    "rate cuts": Decimal("0.6500"),
    "dovish": Decimal("0.4500"),
    "stimulus": Decimal("0.3500"),
    "safe haven": Decimal("0.3000"),
    "central bank buying": Decimal("0.5500"),
}
NEGATIVE_KEYWORDS: dict[str, Decimal] = {
    "rate hike": Decimal("-0.6500"),
    "rate hikes": Decimal("-0.6500"),
    "hawkish": Decimal("-0.4500"),
    "strong dollar": Decimal("-0.4000"),
    "yield surge": Decimal("-0.3500"),
    "treasury yields rise": Decimal("-0.3500"),
}
EVENT_RULES: tuple[tuple[str, str, str, Decimal], ...] = (
    ("war", "geopolitical", "war_escalation", Decimal("0.9500")),
    ("conflict", "geopolitical", "conflict_risk", Decimal("0.8500")),
    ("missile", "geopolitical", "missile_strike", Decimal("0.9000")),
    ("fed", "monetary_policy", "fed_policy", Decimal("0.9000")),
    ("rate cut", "monetary_policy", "fed_rate_cut", Decimal("0.9500")),
    ("rate hike", "monetary_policy", "fed_rate_hike", Decimal("0.9500")),
    ("inflation", "economic_data", "inflation_watch", Decimal("0.8500")),
    ("cpi", "economic_data", "cpi_release", Decimal("0.9000")),
    ("recession", "crisis", "recession_risk", Decimal("0.8500")),
    ("bank crisis", "crisis", "banking_stress", Decimal("0.9500")),
)


@dataclass(frozen=True)
class EventTagResult:
    tag_type: str
    tag_value: str
    relevance_score: Decimal
    metadata: dict[str, object]


@dataclass(frozen=True)
class AnalysisResult:
    analyzer_type: str
    sentiment: str
    score: Decimal
    confidence: Decimal
    reasoning: str
    metadata: dict[str, object]
    event_tags: tuple[EventTagResult, ...]


@dataclass(frozen=True)
class AnalysisSummary:
    items_seen: int
    items_analyzed: int
    items_failed: int
    sentiments_created: int
    event_tags_created: int


class AnalyzerInterface(ABC):
    analyzer_type: str

    @abstractmethod
    def analyze(self, item: NewsItem) -> AnalysisResult:
        raise NotImplementedError


class RuleBasedAnalyzer(AnalyzerInterface):
    analyzer_type = "rule_based"

    def analyze(self, item: NewsItem) -> AnalysisResult:
        text = _normalized_text(item)
        if not text:
            return AnalysisResult(
                analyzer_type=self.analyzer_type,
                sentiment="neutral",
                score=Decimal("0.0000"),
                confidence=Decimal("0.2500"),
                reasoning="No analyzable text was available.",
                metadata={"matched_positive_keywords": [], "matched_negative_keywords": []},
                event_tags=(),
            )

        positive_matches = [keyword for keyword in POSITIVE_KEYWORDS if keyword in text]
        negative_matches = [keyword for keyword in NEGATIVE_KEYWORDS if keyword in text]
        raw_score = sum((POSITIVE_KEYWORDS[keyword] for keyword in positive_matches), Decimal("0.0000"))
        raw_score += sum((NEGATIVE_KEYWORDS[keyword] for keyword in negative_matches), Decimal("0.0000"))
        score = max(Decimal("-1.0000"), min(Decimal("1.0000"), raw_score.quantize(Decimal("0.0001"))))

        if score > Decimal("0.1500"):
            sentiment = "positive"
        elif score < Decimal("-0.1500"):
            sentiment = "negative"
        else:
            sentiment = "neutral"

        match_count = len(positive_matches) + len(negative_matches)
        confidence = min(Decimal("0.9900"), Decimal("0.3500") + Decimal("0.1500") * match_count)
        event_tags = _extract_event_tags(text)
        reasoning_parts: list[str] = []
        if positive_matches:
            reasoning_parts.append(f"positive keywords: {', '.join(positive_matches)}")
        if negative_matches:
            reasoning_parts.append(f"negative keywords: {', '.join(negative_matches)}")
        if event_tags:
            reasoning_parts.append(
                "event tags: " + ", ".join(f"{tag.tag_type}:{tag.tag_value}" for tag in event_tags)
            )
        if not reasoning_parts:
            reasoning_parts.append("No matched keywords; defaulted to neutral.")

        return AnalysisResult(
            analyzer_type=self.analyzer_type,
            sentiment=sentiment,
            score=score,
            confidence=confidence.quantize(Decimal("0.0001")),
            reasoning="; ".join(reasoning_parts),
            metadata={
                "matched_positive_keywords": positive_matches,
                "matched_negative_keywords": negative_matches,
            },
            event_tags=event_tags,
        )


def build_default_analyzer(settings: Settings | None = None) -> AnalyzerInterface:
    active_settings = settings or get_settings()
    if not active_settings.llm_analysis_enabled:
        return RuleBasedAnalyzer()

    from app.services.llm_analysis.llm_analyzer import LLMAnalyzer

    return LLMAnalyzer(settings=active_settings)


def _normalized_text(item: NewsItem) -> str:
    parts = [item.title or "", item.summary or "", item.content or ""]
    return " ".join(part.strip().lower() for part in parts if part and part.strip())


def _extract_event_tags(text: str) -> tuple[EventTagResult, ...]:
    tags: list[EventTagResult] = []
    seen: set[tuple[str, str]] = set()
    for keyword, tag_type, tag_value, relevance_score in EVENT_RULES:
        if keyword not in text:
            continue
        identity = (tag_type, tag_value)
        if identity in seen:
            continue
        seen.add(identity)
        tags.append(
            EventTagResult(
                tag_type=tag_type,
                tag_value=tag_value,
                relevance_score=relevance_score,
                metadata={"matched_keyword": keyword},
            )
        )
    return tuple(tags)


def _pending_news_items_statement(limit: int):
    return (
        select(NewsItem)
        .where(NewsItem.status == "pending")
        .order_by(NewsItem.published_at.asc(), NewsItem.created_at.asc())
        .limit(limit)
    )


def _signal_generation_timestamp(
    item: NewsItem,
    sentiment: SentimentScore | None,
    persisted_event_tags: list[EventTag],
) -> datetime:
    available_times = [item.updated_at or item.created_at or item.published_at]
    if sentiment is not None and sentiment.created_at is not None:
        available_times.append(sentiment.created_at)
    for event_tag in persisted_event_tags:
        if event_tag.created_at is not None:
            available_times.append(event_tag.created_at)
    return max(timestamp.astimezone(UTC) for timestamp in available_times) + timedelta(microseconds=1)


def _persist_analysis(session: Session, item: NewsItem, result: AnalysisResult) -> tuple[int, int, datetime]:
    sentiment_created = 0
    event_tags_created = 0
    persisted_event_tags: list[EventTag] = []

    sentiment = session.execute(
        select(SentimentScore).where(
            SentimentScore.news_id == item.id,
            SentimentScore.analyzer_type == result.analyzer_type,
        )
    ).scalar_one_or_none()
    if sentiment is None:
        sentiment = SentimentScore(
            news_id=item.id,
            analyzer_type=result.analyzer_type,
            sentiment=result.sentiment,
            score=result.score,
            confidence=result.confidence,
            reasoning=result.reasoning,
            metadata_json=result.metadata,
        )
        session.add(sentiment)
        sentiment_created += 1

    for event_tag_result in result.event_tags:
        existing = session.execute(
            select(EventTag.id).where(
                EventTag.news_id == item.id,
                EventTag.tag_type == event_tag_result.tag_type,
                EventTag.tag_value == event_tag_result.tag_value,
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        event_tag = EventTag(
            news_id=item.id,
            tag_type=event_tag_result.tag_type,
            tag_value=event_tag_result.tag_value,
            relevance_score=event_tag_result.relevance_score,
            metadata_json=event_tag_result.metadata,
        )
        session.add(event_tag)
        persisted_event_tags.append(event_tag)
        event_tags_created += 1

    item.status = "analyzed"
    session.add(item)
    session.flush()
    return sentiment_created, event_tags_created, _signal_generation_timestamp(item, sentiment, persisted_event_tags)


def _generate_follow_on_signals(session: Session, signal_timestamp: datetime) -> int:
    signals = generate_signals_for_timestamp(
        session,
        symbol="XAUUSD",
        timestamp=signal_timestamp,
    )
    return len(signals)


def _batch_results_if_supported(
    analyzer: AnalyzerInterface,
    items: list[NewsItem],
) -> tuple[AnalysisResult, ...] | None:
    batch_method = getattr(analyzer, "analyze_batch", None)
    if len(items) <= 1 or not callable(batch_method):
        return None

    results = tuple(batch_method(items))
    if len(results) != len(items):
        raise ValueError("Batch analyzer result count mismatch.")
    return results


def analyze_news_items(
    session: Session,
    analyzer: AnalyzerInterface | None = None,
    *,
    limit: int = 100,
) -> AnalysisSummary:
    active_analyzer = analyzer or RuleBasedAnalyzer()
    items = session.execute(_pending_news_items_statement(limit)).scalars().all()

    items_analyzed = 0
    items_failed = 0
    sentiments_created = 0
    event_tags_created = 0

    batch_results = _batch_results_if_supported(active_analyzer, items)
    if batch_results is not None:
        for item, result in zip(items, batch_results):
            try:
                with session.begin_nested():
                    created_sentiments, created_tags, signal_timestamp = _persist_analysis(session, item, result)
                    _generate_follow_on_signals(session, signal_timestamp)
                session.commit()
                items_analyzed += 1
                sentiments_created += created_sentiments
                event_tags_created += created_tags
            except IntegrityError:
                session.rollback()
                failed_item = session.get(NewsItem, item.id)
                if failed_item is not None:
                    failed_item.status = "failed"
                    session.add(failed_item)
                    session.commit()
                items_failed += 1
            except Exception:
                session.rollback()
                failed_item = session.get(NewsItem, item.id)
                if failed_item is not None:
                    failed_item.status = "failed"
                    session.add(failed_item)
                    session.commit()
                items_failed += 1

        return AnalysisSummary(
            items_seen=len(items),
            items_analyzed=items_analyzed,
            items_failed=items_failed,
            sentiments_created=sentiments_created,
            event_tags_created=event_tags_created,
        )

    for item in items:
        try:
            result = active_analyzer.analyze(item)
            with session.begin_nested():
                created_sentiments, created_tags, signal_timestamp = _persist_analysis(session, item, result)
                _generate_follow_on_signals(session, signal_timestamp)
            session.commit()
            items_analyzed += 1
            sentiments_created += created_sentiments
            event_tags_created += created_tags
        except IntegrityError:
            session.rollback()
            failed_item = session.get(NewsItem, item.id)
            if failed_item is not None:
                failed_item.status = "failed"
                session.add(failed_item)
                session.commit()
            items_failed += 1
        except Exception:
            session.rollback()
            failed_item = session.get(NewsItem, item.id)
            if failed_item is not None:
                failed_item.status = "failed"
                session.add(failed_item)
                session.commit()
            items_failed += 1

    return AnalysisSummary(
        items_seen=len(items),
        items_analyzed=items_analyzed,
        items_failed=items_failed,
        sentiments_created=sentiments_created,
        event_tags_created=event_tags_created,
    )
