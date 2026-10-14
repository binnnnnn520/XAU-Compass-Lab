from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EconomicEvent, EventTag, MarketBar, NewsItem, SentimentScore
from app.services.alt_data import AlternativeDataSnapshot
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


FEATURE_QUANTIZER = Decimal("0.0001")
PERCENT_QUANTIZER = Decimal("0.0001")
DEFAULT_TIMEFRAME = "1h"
DEFAULT_MOMENTUM_BARS = 4


@dataclass(frozen=True)
class FeatureVector:
    symbol: str
    timestamp: datetime
    lookback_hours: int
    sentiment_mean: Decimal
    sentiment_count: int
    event_count: int
    geopolitical_event_count: int
    price_momentum_4h: Decimal
    latest_price: Decimal | None
    has_insufficient_data: bool
    sentiment_std: Decimal = Decimal("0.0000")
    sentiment_velocity: Decimal = Decimal("0.0000")
    price_momentum_1h: Decimal = Decimal("0.0000")
    price_momentum_24h: Decimal = Decimal("0.0000")
    sma_5: Decimal = Decimal("0.0000")
    sma_20: Decimal = Decimal("0.0000")
    ema_12: Decimal = Decimal("0.0000")
    ema_26: Decimal = Decimal("0.0000")
    rsi_14: Decimal = Decimal("0.0000")
    macd_line: Decimal = Decimal("0.0000")
    macd_signal: Decimal = Decimal("0.0000")
    macd_histogram: Decimal = Decimal("0.0000")
    bollinger_upper: Decimal = Decimal("0.0000")
    bollinger_middle: Decimal = Decimal("0.0000")
    bollinger_lower: Decimal = Decimal("0.0000")
    bollinger_position: Decimal = Decimal("0.0000")
    bollinger_width: Decimal = Decimal("0.0000")
    atr_14: Decimal = Decimal("0.0000")
    price_distance_sma_20: Decimal = Decimal("0.0000")
    price_distance_ema_12: Decimal = Decimal("0.0000")
    volume_ratio_20: Decimal = Decimal("0.0000")
    price_momentum_7d: Decimal = Decimal("0.0000")
    high_low_range: Decimal = Decimal("0.0000")
    ema_20_distance: Decimal = Decimal("0.0000")
    ema_50_distance: Decimal = Decimal("0.0000")
    sma_200_distance: Decimal = Decimal("0.0000")
    economic_event_count: int = 0
    high_importance_event_count: int = 0
    fed_event_count: int = 0
    inflation_event_count: int = 0
    economic_surprise_mean: Decimal = Decimal("0.0000")
    cot_net_position_ratio: Decimal = Decimal("0.0000")
    etf_flow_ounces_5d: Decimal = Decimal("0.0000")
    etf_holdings_ounces: Decimal = Decimal("0.0000")
    dxy_momentum_1d: Decimal = Decimal("0.0000")
    hour_of_day: int = 0
    day_of_week: int = 0

    def snapshot(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.astimezone(UTC).isoformat(),
            "lookback_hours": self.lookback_hours,
            "sentiment_mean": format(self.sentiment_mean, "f"),
            "sentiment_count": self.sentiment_count,
            "event_count": self.event_count,
            "geopolitical_event_count": self.geopolitical_event_count,
            "price_momentum_4h": format(self.price_momentum_4h, "f"),
            "latest_price": None if self.latest_price is None else format(self.latest_price, "f"),
            "has_insufficient_data": self.has_insufficient_data,
            "sentiment_std": format(self.sentiment_std, "f"),
            "sentiment_velocity": format(self.sentiment_velocity, "f"),
            "price_momentum_1h": format(self.price_momentum_1h, "f"),
            "price_momentum_24h": format(self.price_momentum_24h, "f"),
            "sma_5": format(self.sma_5, "f"),
            "sma_20": format(self.sma_20, "f"),
            "ema_12": format(self.ema_12, "f"),
            "ema_26": format(self.ema_26, "f"),
            "rsi_14": format(self.rsi_14, "f"),
            "macd_line": format(self.macd_line, "f"),
            "macd_signal": format(self.macd_signal, "f"),
            "macd_histogram": format(self.macd_histogram, "f"),
            "bollinger_upper": format(self.bollinger_upper, "f"),
            "bollinger_middle": format(self.bollinger_middle, "f"),
            "bollinger_lower": format(self.bollinger_lower, "f"),
            "bollinger_position": format(self.bollinger_position, "f"),
            "bollinger_width": format(self.bollinger_width, "f"),
            "atr_14": format(self.atr_14, "f"),
            "price_distance_sma_20": format(self.price_distance_sma_20, "f"),
            "price_distance_ema_12": format(self.price_distance_ema_12, "f"),
            "volume_ratio_20": format(self.volume_ratio_20, "f"),
            "price_momentum_7d": format(self.price_momentum_7d, "f"),
            "high_low_range": format(self.high_low_range, "f"),
            "ema_20_distance": format(self.ema_20_distance, "f"),
            "ema_50_distance": format(self.ema_50_distance, "f"),
            "sma_200_distance": format(self.sma_200_distance, "f"),
            "economic_event_count": self.economic_event_count,
            "high_importance_event_count": self.high_importance_event_count,
            "fed_event_count": self.fed_event_count,
            "inflation_event_count": self.inflation_event_count,
            "economic_surprise_mean": format(self.economic_surprise_mean, "f"),
            "cot_net_position_ratio": format(self.cot_net_position_ratio, "f"),
            "etf_flow_ounces_5d": format(self.etf_flow_ounces_5d, "f"),
            "etf_holdings_ounces": format(self.etf_holdings_ounces, "f"),
            "dxy_momentum_1d": format(self.dxy_momentum_1d, "f"),
            "hour_of_day": self.hour_of_day,
            "day_of_week": self.day_of_week,
        }


def _normalize_timestamp(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None:
        raise ValueError("timestamp must be UTC-aware")
    return timestamp.astimezone(UTC)


def _normalize_lookback(lookback: int | timedelta) -> tuple[timedelta, int]:
    if isinstance(lookback, timedelta):
        if lookback <= timedelta(0):
            raise ValueError("lookback must be positive")
        hours = max(1, int(lookback.total_seconds() // 3600))
        return lookback, hours
    if lookback <= 0:
        raise ValueError("lookback must be positive")
    return timedelta(hours=lookback), lookback


def _as_decimal(value: object) -> Decimal:
    if type(value) is Decimal:
        return value
    return Decimal(str(value))


def _quantize(value: Decimal) -> Decimal:
    value = _as_decimal(value)
    return value.quantize(FEATURE_QUANTIZER, rounding=ROUND_HALF_UP)


def _quantize_percent(value: Decimal) -> Decimal:
    value = _as_decimal(value)
    return value.quantize(PERCENT_QUANTIZER, rounding=ROUND_HALF_UP)


def _price_momentum(latest: Decimal | None, prior: Decimal | None) -> Decimal:
    if latest is None or prior is None or prior == Decimal("0"):
        return Decimal("0.0000")
    latest = _as_decimal(latest)
    prior = _as_decimal(prior)
    return _quantize_percent((latest - prior) / prior)


def _economic_surprise(actual: Decimal | None, forecast: Decimal | None) -> Decimal | None:
    if actual is None or forecast is None:
        return None
    actual = _as_decimal(actual)
    forecast = _as_decimal(forecast)
    if forecast == Decimal("0"):
        return _quantize(actual - forecast)
    return _quantize_percent((actual - forecast) / abs(forecast))


def compute_features(
    session: Session,
    symbol: str,
    timestamp: datetime,
    lookback: int | timedelta,
    *,
    timeframe: str = DEFAULT_TIMEFRAME,
    momentum_bars: int = DEFAULT_MOMENTUM_BARS,
    alternative_data: AlternativeDataSnapshot | None = None,
) -> FeatureVector:
    normalized_timestamp = _normalize_timestamp(timestamp)
    lookback_delta, lookback_hours = _normalize_lookback(lookback)
    window_start = normalized_timestamp - lookback_delta
    market_history_hours = max(lookback_hours, 200)
    market_window_start = normalized_timestamp - timedelta(hours=market_history_hours)
    history_bar_limit = max(momentum_bars + 1, 201)

    sentiment_rows = session.execute(
        select(SentimentScore.score, SentimentScore.created_at)
        .join(NewsItem, NewsItem.id == SentimentScore.news_id)
        .where(
            NewsItem.published_at >= window_start,
            NewsItem.published_at < normalized_timestamp,
            SentimentScore.created_at < normalized_timestamp,
        )
        .order_by(SentimentScore.created_at.asc(), NewsItem.published_at.asc())
    ).all()

    event_tags = session.execute(
        select(EventTag.tag_type, EventTag.relevance_score)
        .join(NewsItem, NewsItem.id == EventTag.news_id)
        .where(
            NewsItem.published_at >= window_start,
            NewsItem.published_at < normalized_timestamp,
            EventTag.created_at < normalized_timestamp,
        )
    ).all()

    economic_events = session.execute(
        select(
            EconomicEvent.event_type,
            EconomicEvent.importance,
            EconomicEvent.actual_value,
            EconomicEvent.forecast_value,
        )
        .where(
            EconomicEvent.event_time >= window_start,
            EconomicEvent.event_time < normalized_timestamp,
            EconomicEvent.created_at < normalized_timestamp,
        )
    ).all()

    bars_desc = session.execute(
        select(MarketBar)
        .where(
            MarketBar.symbol == symbol,
            MarketBar.timeframe == timeframe,
            MarketBar.bar_time >= market_window_start,
            MarketBar.bar_time < normalized_timestamp,
        )
        .order_by(MarketBar.bar_time.desc())
        .limit(history_bar_limit)
    ).scalars().all()
    bars = list(reversed(bars_desc))
    closes = [_as_decimal(bar.close) for bar in bars]
    highs = [_as_decimal(bar.high) for bar in bars]
    lows = [_as_decimal(bar.low) for bar in bars]
    volumes = [_as_decimal(bar.volume) for bar in bars]

    sentiment_scores = [_as_decimal(row.score) for row in sentiment_rows]
    sentiment_timestamps = [row.created_at.astimezone(UTC) for row in sentiment_rows]

    if sentiment_scores:
        sentiment_sum = sum(sentiment_scores, Decimal("0.0000"))
        sentiment_mean = _quantize(sentiment_sum / Decimal(len(sentiment_scores)))
    else:
        sentiment_mean = Decimal("0.0000")

    event_count = len(event_tags)
    geopolitical_event_count = sum(1 for tag_type, _ in event_tags if tag_type == "geopolitical")
    economic_event_count = len(economic_events)
    high_importance_event_count = sum(1 for _event_type, importance, _actual, _forecast in economic_events if importance == "high")
    fed_event_count = sum(
        1
        for event_type, _importance, _actual, _forecast in economic_events
        if event_type in {"fed", "fomc", "monetary_policy"}
    )
    inflation_event_count = sum(
        1
        for event_type, _importance, _actual, _forecast in economic_events
        if event_type in {"inflation", "cpi", "ppi"}
    )
    surprises = [
        surprise
        for _event_type, _importance, actual, forecast in economic_events
        if (surprise := _economic_surprise(actual, forecast)) is not None
    ]
    economic_surprise_mean_value = (
        _quantize(sum(surprises, Decimal("0.0000")) / Decimal(len(surprises)))
        if surprises
        else Decimal("0.0000")
    )

    latest_price = closes[-1] if closes else None
    prior_1h = closes[-2] if len(closes) > 1 else None
    prior_4h = closes[-(momentum_bars + 1)] if len(closes) > momentum_bars else None
    prior_24h = closes[-25] if len(closes) > 24 else None
    prior_7d = closes[-169] if len(closes) > 168 else None

    sentiment_std_value = sentiment_std(sentiment_scores)
    sentiment_velocity_value = sentiment_velocity(sentiment_scores, sentiment_timestamps)
    sma_5_value = sma(closes, 5)
    sma_20_value = sma(closes, 20)
    sma_200_value = sma(closes, 200)
    ema_12_value = ema(closes, 12)
    ema_20_value = ema(closes, 20)
    ema_26_value = ema(closes, 26)
    ema_50_value = ema(closes, 50)
    rsi_14_value = rsi(closes, 14)
    macd_line_value, macd_signal_value, macd_histogram_value = macd(closes)
    bollinger_upper_value, bollinger_middle_value, bollinger_lower_value = bollinger_bands(closes)
    bollinger_position_value = (
        bollinger_position(latest_price, bollinger_upper_value, bollinger_lower_value)
        if latest_price is not None
        else Decimal("0.0000")
    )
    bollinger_width_value = bollinger_width(
        bollinger_upper_value,
        bollinger_lower_value,
        bollinger_middle_value,
    )
    atr_14_value = atr(highs, lows, closes, 14)
    price_distance_sma_20_value = (
        price_distance(latest_price, sma_20_value) if latest_price is not None else Decimal("0.0000")
    )
    price_distance_ema_12_value = (
        price_distance(latest_price, ema_12_value) if latest_price is not None else Decimal("0.0000")
    )
    volume_ratio_20_value = volume_ratio(volumes, 20)
    high_low_range_value = _price_momentum(highs[-1], lows[-1]) if highs and lows else Decimal("0.0000")
    ema_20_distance_value = (
        price_distance(latest_price, ema_20_value) if latest_price is not None else Decimal("0.0000")
    )
    ema_50_distance_value = (
        price_distance(latest_price, ema_50_value) if latest_price is not None else Decimal("0.0000")
    )
    sma_200_distance_value = (
        price_distance(latest_price, sma_200_value) if latest_price is not None else Decimal("0.0000")
    )

    has_insufficient_data = len(sentiment_scores) == 0 or len(bars) <= momentum_bars
    alternative_data = alternative_data or AlternativeDataSnapshot()

    return FeatureVector(
        symbol=symbol,
        timestamp=normalized_timestamp,
        lookback_hours=lookback_hours,
        sentiment_mean=sentiment_mean,
        sentiment_count=len(sentiment_scores),
        event_count=event_count,
        geopolitical_event_count=geopolitical_event_count,
        price_momentum_4h=_price_momentum(latest_price, prior_4h),
        latest_price=latest_price,
        has_insufficient_data=has_insufficient_data,
        sentiment_std=sentiment_std_value,
        sentiment_velocity=sentiment_velocity_value,
        price_momentum_1h=_price_momentum(latest_price, prior_1h),
        price_momentum_24h=_price_momentum(latest_price, prior_24h),
        sma_5=sma_5_value,
        sma_20=sma_20_value,
        ema_12=ema_12_value,
        ema_26=ema_26_value,
        rsi_14=rsi_14_value,
        macd_line=macd_line_value,
        macd_signal=macd_signal_value,
        macd_histogram=macd_histogram_value,
        bollinger_upper=bollinger_upper_value,
        bollinger_middle=bollinger_middle_value,
        bollinger_lower=bollinger_lower_value,
        bollinger_position=bollinger_position_value,
        bollinger_width=bollinger_width_value,
        atr_14=atr_14_value,
        price_distance_sma_20=price_distance_sma_20_value,
        price_distance_ema_12=price_distance_ema_12_value,
        volume_ratio_20=volume_ratio_20_value,
        price_momentum_7d=_price_momentum(latest_price, prior_7d),
        high_low_range=high_low_range_value,
        ema_20_distance=ema_20_distance_value,
        ema_50_distance=ema_50_distance_value,
        sma_200_distance=sma_200_distance_value,
        economic_event_count=economic_event_count,
        high_importance_event_count=high_importance_event_count,
        fed_event_count=fed_event_count,
        inflation_event_count=inflation_event_count,
        economic_surprise_mean=economic_surprise_mean_value,
        cot_net_position_ratio=alternative_data.cot_net_position_ratio,
        etf_flow_ounces_5d=alternative_data.etf_flow_ounces_5d,
        etf_holdings_ounces=alternative_data.etf_holdings_ounces,
        dxy_momentum_1d=alternative_data.dxy_momentum_1d,
        hour_of_day=normalized_timestamp.hour,
        day_of_week=normalized_timestamp.weekday(),
    )
