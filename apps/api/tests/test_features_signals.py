from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
import sys

import pytest
from sqlalchemy import select


API_ROOT = Path(__file__).resolve().parents[1]

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.models import EconomicEvent, EventTag, MarketBar, NewsItem, SentimentScore, Signal, StrategyRun
from app.services.feature_engine import FeatureVector, compute_features
from app.services.feature_engine.sentiment_features import sentiment_std, sentiment_velocity
from app.services.feature_engine.technical_indicators import (
    atr,
    bollinger_bands,
    bollinger_position,
    bollinger_width,
    ema,
    macd,
    price_distance,
    rsi,
    sma,
    volume_ratio,
)
from app.services.llm_analysis import analyze_news_items
from app.services.llm_analysis import service as analysis_service
from app.services.signal_engine import generate_signal, generate_signals_for_timestamp


def _market_bar(hours: int, close: str) -> MarketBar:
    base = Decimal(close)
    return MarketBar(
        timeframe="1h",
        bar_time=datetime(2026, 4, 1, hours, 0, tzinfo=UTC),
        open=base,
        high=base + Decimal("1.00000000"),
        low=base - Decimal("1.00000000"),
        close=base,
        volume=Decimal("10.00000000"),
    )


def _analyzed_news_item(
    *,
    published_at: datetime,
    title_hash: str,
    score: str,
    tag_type: str = "monetary_policy",
    tag_value: str = "fed_rate_cut",
) -> tuple[NewsItem, SentimentScore, EventTag]:
    item = NewsItem(
        title=f"News {title_hash[:8]}",
        content="Fed rate cut and safe haven demand support gold.",
        published_at=published_at,
        title_hash=title_hash,
        status="analyzed",
    )
    sentiment = SentimentScore(
        news_item=item,
        analyzer_type="rule_based",
        sentiment="positive" if Decimal(score) > 0 else "negative",
        score=Decimal(score),
        confidence=Decimal("0.8000"),
        reasoning="Prepared fixture sentiment.",
    )
    event_tag = EventTag(
        news_item=item,
        tag_type=tag_type,
        tag_value=tag_value,
        relevance_score=Decimal("0.9000"),
        metadata_json={"fixture": True},
    )
    return item, sentiment, event_tag


def test_compute_features_excludes_data_at_or_after_timestamp(db_session) -> None:
    before_item, before_sentiment, before_tag = _analyzed_news_item(
        published_at=datetime(2026, 4, 1, 2, 30, tzinfo=UTC),
        title_hash="1" * 64,
        score="0.7000",
        tag_type="geopolitical",
        tag_value="war_escalation",
    )
    at_item, at_sentiment, at_tag = _analyzed_news_item(
        published_at=datetime(2026, 4, 1, 6, 0, tzinfo=UTC),
        title_hash="2" * 64,
        score="-0.9000",
    )
    before_sentiment.created_at = datetime(2026, 4, 1, 2, 35, tzinfo=UTC)
    before_tag.created_at = datetime(2026, 4, 1, 2, 35, tzinfo=UTC)
    at_sentiment.created_at = datetime(2026, 4, 1, 6, 0, tzinfo=UTC)
    at_tag.created_at = datetime(2026, 4, 1, 6, 0, tzinfo=UTC)

    db_session.add_all(
        [
            before_item,
            before_sentiment,
            before_tag,
            at_item,
            at_sentiment,
            at_tag,
            _market_bar(1, "2300.00000000"),
            _market_bar(2, "2302.00000000"),
            _market_bar(3, "2304.00000000"),
            _market_bar(4, "2306.00000000"),
            _market_bar(5, "2308.00000000"),
            _market_bar(6, "2400.00000000"),
        ]
    )
    db_session.commit()

    features = compute_features(db_session, "XAUUSD", datetime(2026, 4, 1, 6, 0, tzinfo=UTC), 24)

    assert features.sentiment_count == 1
    assert features.sentiment_mean == Decimal("0.7000")
    assert features.event_count == 1
    assert features.geopolitical_event_count == 1
    assert features.latest_price == Decimal("2308.00000000")
    assert features.price_momentum_4h == Decimal("0.0035")
    assert features.has_insufficient_data is False
    assert features.snapshot()["sentiment_std"] == "0.0000"


def test_compute_features_excludes_delayed_sentiment_and_event_availability(db_session) -> None:
    included_item, included_sentiment, included_tag = _analyzed_news_item(
        published_at=datetime(2026, 4, 1, 2, 0, tzinfo=UTC),
        title_hash="11" * 32,
        score="0.6000",
        tag_type="geopolitical",
        tag_value="war_escalation",
    )
    delayed_item, delayed_sentiment, delayed_tag = _analyzed_news_item(
        published_at=datetime(2026, 4, 1, 3, 0, tzinfo=UTC),
        title_hash="12" * 32,
        score="-0.9000",
        tag_type="economic_data",
        tag_value="cpi_release",
    )
    included_sentiment.created_at = datetime(2026, 4, 1, 2, 5, tzinfo=UTC)
    included_tag.created_at = datetime(2026, 4, 1, 2, 5, tzinfo=UTC)
    delayed_sentiment.created_at = datetime(2026, 4, 1, 6, 5, tzinfo=UTC)
    delayed_tag.created_at = datetime(2026, 4, 1, 6, 5, tzinfo=UTC)

    db_session.add_all(
        [
            included_item,
            included_sentiment,
            included_tag,
            delayed_item,
            delayed_sentiment,
            delayed_tag,
            _market_bar(1, "2300.00000000"),
            _market_bar(2, "2302.00000000"),
            _market_bar(3, "2304.00000000"),
            _market_bar(4, "2306.00000000"),
            _market_bar(5, "2308.00000000"),
        ]
    )
    db_session.commit()

    features = compute_features(db_session, "XAUUSD", datetime(2026, 4, 1, 6, 0, tzinfo=UTC), 24)

    assert features.sentiment_count == 1
    assert features.sentiment_mean == Decimal("0.6000")
    assert features.event_count == 1
    assert features.geopolitical_event_count == 1


def test_compute_features_includes_only_available_economic_events_before_timestamp(db_session) -> None:
    included_event = EconomicEvent(
        event_time=datetime(2026, 4, 1, 5, 0, tzinfo=UTC),
        event_type="inflation",
        name="US CPI",
        importance="high",
        currency="USD",
        actual_value=Decimal("3.4000"),
        forecast_value=Decimal("3.0000"),
        previous_value=Decimal("3.1000"),
        source="fixture",
        created_at=datetime(2026, 4, 1, 5, 1, tzinfo=UTC),
    )
    at_timestamp_event = EconomicEvent(
        event_time=datetime(2026, 4, 1, 6, 0, tzinfo=UTC),
        event_type="monetary_policy",
        name="Fed decision",
        importance="high",
        currency="USD",
        source="fixture",
        created_at=datetime(2026, 4, 1, 5, 55, tzinfo=UTC),
    )
    delayed_event = EconomicEvent(
        event_time=datetime(2026, 4, 1, 4, 0, tzinfo=UTC),
        event_type="monetary_policy",
        name="Fed speakers",
        importance="medium",
        currency="USD",
        source="fixture",
        created_at=datetime(2026, 4, 1, 6, 5, tzinfo=UTC),
    )
    db_session.add_all(
        [
            included_event,
            at_timestamp_event,
            delayed_event,
            _market_bar(1, "2300.00000000"),
            _market_bar(2, "2302.00000000"),
            _market_bar(3, "2304.00000000"),
            _market_bar(4, "2306.00000000"),
            _market_bar(5, "2308.00000000"),
        ]
    )
    db_session.commit()

    features = compute_features(db_session, "XAUUSD", datetime(2026, 4, 1, 6, 0, tzinfo=UTC), 24)

    assert features.economic_event_count == 1
    assert features.high_importance_event_count == 1
    assert features.fed_event_count == 0
    assert features.inflation_event_count == 1
    assert features.economic_surprise_mean == Decimal("0.1333")
    assert features.snapshot()["economic_surprise_mean"] == "0.1333"


def test_feature_snapshot_contains_at_least_25_decimal_safe_phase1_features(db_session) -> None:
    db_session.add_all(
        [
            _market_bar(1, "2300.00000000"),
            _market_bar(2, "2302.00000000"),
            _market_bar(3, "2304.00000000"),
            _market_bar(4, "2306.00000000"),
            _market_bar(5, "2308.00000000"),
        ]
    )
    db_session.commit()

    features = compute_features(db_session, "XAUUSD", datetime(2026, 4, 1, 6, 0, tzinfo=UTC), 24)
    snapshot = features.snapshot()
    decimal_feature_names = [
        name
        for name, value in snapshot.items()
        if isinstance(value, str) and name not in {"symbol", "timestamp"}
    ]

    assert len(decimal_feature_names) >= 25
    assert all(isinstance(getattr(features, name), Decimal) for name in decimal_feature_names)


def test_indicator_helpers_and_sentiment_features_return_decimal_values() -> None:
    closes = [Decimal(value) for value in ("10", "11", "12", "13", "14", "15", "16", "17", "18", "19", "20", "21", "22", "23", "24", "25", "26", "27", "28", "29", "30", "31", "32", "33", "34", "35", "36", "37", "38", "39", "40", "41", "42", "43", "44")]
    highs = [value + Decimal("1") for value in closes]
    lows = [value - Decimal("1") for value in closes]
    volumes = [Decimal(value) for value in ("10", "11", "12", "13", "14", "15", "16", "17", "18", "19", "20", "21", "22", "23", "24", "25", "26", "27", "28", "29")]
    scores = [Decimal("0.1000"), Decimal("0.3000"), Decimal("0.7000")]
    timestamps = [
        datetime(2026, 4, 1, 1, 0, tzinfo=UTC),
        datetime(2026, 4, 1, 2, 0, tzinfo=UTC),
        datetime(2026, 4, 1, 4, 0, tzinfo=UTC),
    ]

    sma_value = sma(closes, 5)
    ema_value = ema(closes, 12)
    rsi_value = rsi(closes, 14)
    macd_line, macd_signal, macd_histogram = macd(closes)
    upper, middle, lower = bollinger_bands(closes, 20, 2)
    position = bollinger_position(closes[-1], upper, lower)
    width = bollinger_width(upper, lower, middle)
    atr_value = atr(highs, lows, closes, 14)
    distance = price_distance(Decimal("105"), Decimal("100"))
    volume_ratio_value = volume_ratio(volumes, 20)
    std_value = sentiment_std(scores)
    velocity_value = sentiment_velocity(scores, timestamps)

    assert sma_value == Decimal("42.0000")
    assert isinstance(ema_value, Decimal)
    assert rsi_value > Decimal("50.0000")
    assert isinstance(macd_line, Decimal)
    assert isinstance(macd_signal, Decimal)
    assert isinstance(macd_histogram, Decimal)
    assert upper > middle > lower
    assert Decimal("0.0000") <= position <= Decimal("1.0000")
    assert width > Decimal("0.0000")
    assert atr_value > Decimal("0.0000")
    assert distance == Decimal("0.0500")
    assert volume_ratio_value == Decimal("1.4872")
    assert std_value == Decimal("0.2494")
    assert velocity_value == Decimal("0.2000")


def test_indicator_helpers_return_safe_defaults_for_insufficient_data() -> None:
    closes = [Decimal("10"), Decimal("11")]
    timestamp = datetime(2026, 4, 1, 1, 0, tzinfo=UTC)

    assert sma(closes, 5) == Decimal("0.0000")
    assert ema(closes, 5) == Decimal("0.0000")
    assert rsi(closes, 14) == Decimal("0.0000")
    assert macd(closes) == (Decimal("0.0000"), Decimal("0.0000"), Decimal("0.0000"))
    assert bollinger_bands(closes) == (Decimal("0.0000"), Decimal("0.0000"), Decimal("0.0000"))
    assert atr(closes, closes, closes, 14) == Decimal("0.0000")
    assert volume_ratio(closes, 20) == Decimal("0.0000")
    assert sentiment_std([Decimal("0.1000")]) == Decimal("0.0000")
    assert sentiment_velocity([Decimal("0.1000")], [timestamp]) == Decimal("0.0000")


def test_generate_signal_returns_buy_sell_and_hold() -> None:
    strategy = StrategyRun(
        strategy_name="sentiment_momentum_v1",
        version="1.0.0",
        parameters={
            "positive_sentiment_threshold": "0.5000",
            "negative_sentiment_threshold": "-0.5000",
            "positive_momentum_threshold": "0.0001",
            "negative_momentum_threshold": "-0.0001",
        },
    )

    buy_features = FeatureVector(
        symbol="XAUUSD",
        timestamp=datetime(2026, 4, 1, 6, 0, tzinfo=UTC),
        lookback_hours=24,
        sentiment_mean=Decimal("0.7000"),
        sentiment_count=2,
        event_count=2,
        geopolitical_event_count=1,
        price_momentum_4h=Decimal("0.0040"),
        latest_price=Decimal("2310.00000000"),
        has_insufficient_data=False,
    )
    sell_features = FeatureVector(
        symbol="XAUUSD",
        timestamp=datetime(2026, 4, 1, 6, 0, tzinfo=UTC),
        lookback_hours=24,
        sentiment_mean=Decimal("-0.8000"),
        sentiment_count=2,
        event_count=1,
        geopolitical_event_count=0,
        price_momentum_4h=Decimal("-0.0040"),
        latest_price=Decimal("2290.00000000"),
        has_insufficient_data=False,
    )
    hold_features = FeatureVector(
        symbol="XAUUSD",
        timestamp=datetime(2026, 4, 1, 6, 0, tzinfo=UTC),
        lookback_hours=24,
        sentiment_mean=Decimal("0.0000"),
        sentiment_count=0,
        event_count=0,
        geopolitical_event_count=0,
        price_momentum_4h=Decimal("0.0000"),
        latest_price=None,
        has_insufficient_data=True,
    )

    buy_decision = generate_signal(buy_features, strategy)
    sell_decision = generate_signal(sell_features, strategy)
    hold_decision = generate_signal(hold_features, strategy)

    assert buy_decision.direction == "BUY"
    assert sell_decision.direction == "SELL"
    assert hold_decision.direction == "HOLD"
    assert hold_decision.reasoning == "insufficient_data"


def test_signal_generation_timestamp_tracks_analysis_availability_time() -> None:
    published_at = datetime(2026, 4, 1, 5, 30, tzinfo=UTC)
    item = NewsItem(title="Backlog news item", published_at=published_at, title_hash="5" * 64)
    item.updated_at = datetime(2026, 4, 1, 5, 31, tzinfo=UTC)
    sentiment = SentimentScore(
        news_item=item,
        analyzer_type="rule_based",
        sentiment="positive",
        score=Decimal("0.5000"),
        confidence=Decimal("0.8000"),
        reasoning="Fixture sentiment.",
        created_at=datetime(2026, 4, 1, 5, 31, tzinfo=UTC),
    )
    event_tag = EventTag(
        news_item=item,
        tag_type="geopolitical",
        tag_value="war_escalation",
        relevance_score=Decimal("0.9000"),
        metadata_json={},
        created_at=datetime(2026, 4, 1, 5, 32, tzinfo=UTC),
    )

    timestamp = analysis_service._signal_generation_timestamp(item, sentiment, [event_tag])

    assert timestamp == datetime(2026, 4, 1, 5, 32, 0, 1, tzinfo=UTC)


def test_generate_signals_persists_features_snapshot_and_reuses_strategy_config(db_session) -> None:
    strategy = StrategyRun(
        strategy_name="custom_sentiment_momentum",
        version="2.0.0",
        parameters={
            "lookback_hours": 24,
            "momentum_bars": 4,
            "positive_sentiment_threshold": "0.4000",
            "negative_sentiment_threshold": "-0.4000",
            "positive_momentum_threshold": "0.0001",
            "negative_momentum_threshold": "-0.0001",
        },
        is_active=True,
    )
    item, sentiment, event_tag = _analyzed_news_item(
        published_at=datetime(2026, 4, 1, 2, 0, tzinfo=UTC),
        title_hash="3" * 64,
        score="0.6500",
    )
    sentiment.created_at = datetime(2026, 4, 1, 2, 5, tzinfo=UTC)
    event_tag.created_at = datetime(2026, 4, 1, 2, 5, tzinfo=UTC)

    db_session.add(strategy)
    db_session.add_all(
        [
            item,
            sentiment,
            event_tag,
            _market_bar(1, "2300.00000000"),
            _market_bar(2, "2302.00000000"),
            _market_bar(3, "2304.00000000"),
            _market_bar(4, "2306.00000000"),
            _market_bar(5, "2310.00000000"),
        ]
    )
    db_session.commit()

    signals = generate_signals_for_timestamp(
        db_session,
        symbol="XAUUSD",
        timestamp=datetime(2026, 4, 1, 6, 0, tzinfo=UTC),
    )
    db_session.commit()

    persisted = db_session.execute(select(Signal)).scalars().all()

    assert len(signals) == 1
    assert len(persisted) == 1
    assert persisted[0].strategy_run_id == strategy.id
    assert persisted[0].features_used == signals[0].features_used
    assert persisted[0].features_used["sentiment_mean"] == "0.6500"
    assert persisted[0].features_used["macd_line"] == signals[0].features_used["macd_line"]
    assert persisted[0].price_at_signal == Decimal("2310.00000000")
    assert isinstance(persisted[0].strength, Decimal)
    assert isinstance(persisted[0].confidence, Decimal)
    assert persisted[0].signal_time.tzinfo == UTC


def test_generate_signals_persists_ensemble_signal_through_shared_entry(db_session) -> None:
    strategy = StrategyRun(
        strategy_name="ensemble_v1",
        version="0.1.0",
        parameters={
            "lookback_hours": 24,
            "momentum_bars": 4,
            "members": [
                {
                    "strategy_name": "sentiment_momentum_v1",
                    "version": "1.0.0",
                    "weight": "1.0000",
                    "parameters": {
                        "positive_sentiment_threshold": "0.4000",
                        "negative_sentiment_threshold": "-0.4000",
                        "positive_momentum_threshold": "0.0001",
                        "negative_momentum_threshold": "-0.0001",
                    },
                }
            ],
        },
        is_active=True,
    )
    item, sentiment, event_tag = _analyzed_news_item(
        published_at=datetime(2026, 4, 1, 2, 0, tzinfo=UTC),
        title_hash="33" * 32,
        score="0.6500",
    )
    sentiment.created_at = datetime(2026, 4, 1, 2, 5, tzinfo=UTC)
    event_tag.created_at = datetime(2026, 4, 1, 2, 5, tzinfo=UTC)

    db_session.add(strategy)
    db_session.add_all(
        [
            item,
            sentiment,
            event_tag,
            _market_bar(1, "2300.00000000"),
            _market_bar(2, "2302.00000000"),
            _market_bar(3, "2304.00000000"),
            _market_bar(4, "2306.00000000"),
            _market_bar(5, "2310.00000000"),
        ]
    )
    db_session.commit()

    signals = generate_signals_for_timestamp(
        db_session,
        symbol="XAUUSD",
        timestamp=datetime(2026, 4, 1, 6, 0, tzinfo=UTC),
    )
    db_session.commit()

    persisted = db_session.execute(select(Signal)).scalars().all()

    assert len(signals) == 1
    assert len(persisted) == 1
    assert persisted[0].strategy_run_id == strategy.id
    assert persisted[0].direction == "BUY"
    assert "ensemble_v1" in persisted[0].reasoning
    assert persisted[0].features_used == signals[0].features_used
    assert persisted[0].features_used["sentiment_mean"] == "0.6500"
    assert persisted[0].signal_time.tzinfo == UTC
    assert isinstance(persisted[0].strength, Decimal)
    assert isinstance(persisted[0].confidence, Decimal)


def test_generate_signals_for_timestamp_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="UTC-aware"):
        generate_signals_for_timestamp(None, timestamp=datetime(2026, 4, 1, 6, 0))  # type: ignore[arg-type]


def test_analyze_news_items_generates_signal_automatically(db_session) -> None:
    published_at = datetime(2026, 4, 1, 5, 30, tzinfo=UTC)
    db_session.add_all(
        [
            _market_bar(1, "2300.00000000"),
            _market_bar(2, "2301.00000000"),
            _market_bar(3, "2302.00000000"),
            _market_bar(4, "2304.00000000"),
            _market_bar(5, "2308.00000000"),
        ]
    )
    db_session.add(
        NewsItem(
            title="Fed rate cut boosts gold demand",
            content="Fed rate cut and safe haven demand support gold while conflict risk rises.",
            published_at=published_at,
            title_hash="4" * 64,
        )
    )
    db_session.commit()

    summary = analyze_news_items(db_session)

    signals = db_session.execute(select(Signal).order_by(Signal.created_at.asc())).scalars().all()
    strategies = db_session.execute(select(StrategyRun)).scalars().all()
    item = db_session.execute(select(NewsItem)).scalar_one()
    sentiment = db_session.execute(select(SentimentScore)).scalar_one()
    event_tags = db_session.execute(select(EventTag).order_by(EventTag.created_at.asc())).scalars().all()

    assert summary.items_seen == 1
    assert summary.items_analyzed == 1
    assert len(strategies) == 1
    assert strategies[0].is_active is True
    assert len(signals) == 1
    assert signals[0].source_type == "live"
    assert signals[0].signal_time == analysis_service._signal_generation_timestamp(item, sentiment, event_tags)
    assert signals[0].features_used["has_insufficient_data"] is True
    assert signals[0].features_used["sentiment_count"] == 0
    assert signals[0].direction == "HOLD"
