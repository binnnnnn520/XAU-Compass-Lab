from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from time import sleep
from typing import Any, Callable, Iterable

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import MarketBar

SUPPORTED_TIMEFRAMES = {
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
}
INTERNAL_SYMBOL = "XAUUSD"
PROVIDER_SYMBOL_MAP = {INTERNAL_SYMBOL: "XAUUSD=X", "XAUUSD=X": "XAUUSD=X"}

# Yahoo's chart API rejects requests without a browser-like User-Agent (HTTP 429).
MARKET_DATA_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0 Safari/537.36"
)


@dataclass(frozen=True)
class MarketBarInput:
    symbol: str
    timeframe: str
    bar_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    data_source: str


@dataclass(frozen=True)
class SyncSummary:
    bars_seen: int
    bars_inserted: int
    bars_skipped: int
    gap_count: int
    gaps: tuple[datetime, ...]


@dataclass(frozen=True)
class ProviderPayloadResult:
    provider_name: str
    provider_symbol: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    initial_delay_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    retryable_status_codes: tuple[int, ...] = (429, 500, 502, 503, 504)


def _normalize_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if normalized == "XAUUSD=X":
        return INTERNAL_SYMBOL
    if normalized != INTERNAL_SYMBOL:
        raise ValueError(f"Unsupported symbol: {symbol}")
    return INTERNAL_SYMBOL


def _provider_symbol(symbol: str) -> str:
    normalized = _normalize_symbol(symbol)
    return PROVIDER_SYMBOL_MAP[normalized]


def _provider_symbol_for_source(symbol: str, source: dict[str, object]) -> str:
    normalized = _normalize_symbol(symbol)
    symbol_map = source.get("symbol_map", {})
    if isinstance(symbol_map, dict):
        mapped = symbol_map.get(normalized) or symbol_map.get(symbol)
        if mapped:
            return str(mapped)
    return _provider_symbol(normalized)


def _validate_timeframe(timeframe: str) -> None:
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValueError(f"Unsupported timeframe: {timeframe}")


def _normalize_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC)

    if isinstance(value, str):
        normalized = value.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    raise TypeError(f"Unsupported datetime value: {value!r}")


def _normalize_window(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    normalized_start = _normalize_datetime(start)
    normalized_end = _normalize_datetime(end)
    if normalized_end <= normalized_start:
        raise ValueError("end must be later than start")
    return normalized_start, normalized_end


def _to_decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def fetch_provider_payload(
    provider_symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    timeout_seconds: float,
) -> dict[str, Any]:
    with httpx.Client(
        timeout=timeout_seconds,
        follow_redirects=True,
        headers={"User-Agent": MARKET_DATA_USER_AGENT},
    ) as client:
        response = client.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{provider_symbol}",
            params={
                "interval": timeframe,
                "period1": int(start.timestamp()),
                "period2": int(end.timestamp()),
                "includePrePost": "false",
                "events": "div,splits",
            },
        )
        response.raise_for_status()
        return response.json()


def _is_retryable_error(exc: Exception, retryable_status_codes: tuple[int, ...]) -> bool:
    if isinstance(exc, (httpx.ConnectError, httpx.ReadError, httpx.ReadTimeout, httpx.WriteError, httpx.WriteTimeout)):
        return True

    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in retryable_status_codes

    return False


def _fetch_provider_payload_with_retry(
    fetcher: Callable[[str, str, datetime, datetime, float], dict[str, Any]],
    provider_symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    timeout_seconds: float,
    retry_policy: RetryPolicy,
    sleeper: Callable[[float], None],
) -> dict[str, Any]:
    delay_seconds = retry_policy.initial_delay_seconds
    last_error: Exception | None = None

    for attempt in range(1, retry_policy.max_attempts + 1):
        try:
            return fetcher(provider_symbol, timeframe, start, end, timeout_seconds)
        except Exception as exc:
            last_error = exc
            should_retry = attempt < retry_policy.max_attempts and _is_retryable_error(
                exc,
                retry_policy.retryable_status_codes,
            )
            if not should_retry:
                raise
            sleeper(delay_seconds)
            delay_seconds *= retry_policy.backoff_multiplier

    raise RuntimeError(f"Failed to fetch market bars after {retry_policy.max_attempts} attempts: {last_error}") from last_error


def fetch_provider_payload_with_failover(
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    *,
    settings: Settings,
    provider_fetcher: Callable[[str, str, datetime, datetime, float], dict[str, Any]],
    retry_policy: RetryPolicy,
    sleeper: Callable[[float], None],
) -> ProviderPayloadResult:
    normalized_symbol = _normalize_symbol(symbol)
    last_error: Exception | None = None
    sources = active_sources = settings.market_data_sources

    for source in sources:
        provider_name = str(source["name"])
        provider_symbol = _provider_symbol_for_source(normalized_symbol, source)
        try:
            payload = _fetch_provider_payload_with_retry(
                provider_fetcher,
                provider_symbol,
                timeframe,
                start,
                end,
                settings.market_fetch_timeout_seconds,
                retry_policy,
                sleeper,
            )
            return ProviderPayloadResult(
                provider_name=provider_name,
                provider_symbol=provider_symbol,
                payload=payload,
            )
        except Exception as exc:
            if len(active_sources) == 1:
                raise
            last_error = exc
            continue

    raise RuntimeError(f"All market data sources failed for {normalized_symbol}: {last_error}") from last_error


def parse_provider_bars(
    payload: dict[str, Any],
    *,
    symbol: str,
    timeframe: str,
    data_source: str,
) -> list[MarketBarInput]:
    _validate_timeframe(timeframe)
    normalized_symbol = _normalize_symbol(symbol)
    chart = payload.get("chart") if isinstance(payload, dict) else None
    results = chart.get("result") if isinstance(chart, dict) else None
    if not results:
        return []

    first_result = results[0] if isinstance(results[0], dict) else {}
    timestamps = first_result.get("timestamp") or []
    indicators = first_result.get("indicators") or {}
    quotes = indicators.get("quote") or [{}]
    quote = quotes[0] if quotes and isinstance(quotes[0], dict) else {}

    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    deduped: dict[datetime, MarketBarInput] = {}
    for index, raw_timestamp in enumerate(timestamps):
        if index >= len(opens) or index >= len(highs) or index >= len(lows) or index >= len(closes):
            continue

        open_value = opens[index]
        high_value = highs[index]
        low_value = lows[index]
        close_value = closes[index]
        if None in (open_value, high_value, low_value, close_value):
            continue

        volume_value = volumes[index] if index < len(volumes) and volumes[index] is not None else 0
        bar_time = _normalize_datetime(raw_timestamp)
        deduped[bar_time] = MarketBarInput(
            symbol=normalized_symbol,
            timeframe=timeframe,
            bar_time=bar_time,
            open=_to_decimal(open_value),
            high=_to_decimal(high_value),
            low=_to_decimal(low_value),
            close=_to_decimal(close_value),
            volume=_to_decimal(volume_value),
            data_source=data_source,
        )

    return [deduped[key] for key in sorted(deduped)]


def detect_gaps(bar_times: Iterable[datetime], timeframe: str) -> tuple[datetime, ...]:
    _validate_timeframe(timeframe)
    expected_step = SUPPORTED_TIMEFRAMES[timeframe]
    ordered_times = sorted({_normalize_datetime(bar_time) for bar_time in bar_times})

    gaps: list[datetime] = []
    for previous, current in zip(ordered_times, ordered_times[1:]):
        missing = previous + expected_step
        while missing < current:
            gaps.append(missing)
            missing += expected_step

    return tuple(gaps)


def _persist_bars(session: Session, bars: list[MarketBarInput]) -> tuple[int, int]:
    inserted = 0
    skipped = 0

    for bar in bars:
        existing = session.execute(
            select(MarketBar.id).where(
                MarketBar.symbol == bar.symbol,
                MarketBar.timeframe == bar.timeframe,
                MarketBar.bar_time == bar.bar_time,
            )
        ).scalar_one_or_none()
        if existing is not None:
            skipped += 1
            continue

        market_bar = MarketBar(
            symbol=bar.symbol,
            timeframe=bar.timeframe,
            bar_time=bar.bar_time,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            data_source=bar.data_source,
        )
        try:
            with session.begin_nested():
                session.add(market_bar)
                session.flush()
        except IntegrityError:
            skipped += 1
            continue
        inserted += 1

    return inserted, skipped


def sync_bars_with_details(
    session: Session,
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    settings: Settings | None = None,
    provider_fetcher: Callable[[str, str, datetime, datetime, float], dict[str, Any]] | None = None,
    provider_parser: Callable[..., list[MarketBarInput]] | None = None,
    retry_policy: RetryPolicy | None = None,
    sleeper: Callable[[float], None] = sleep,
) -> SyncSummary:
    active_settings = settings or get_settings()
    _validate_timeframe(timeframe)
    normalized_symbol = _normalize_symbol(symbol)
    normalized_start, normalized_end = _normalize_window(start, end)
    fetcher = provider_fetcher or fetch_provider_payload
    parser = provider_parser or parse_provider_bars
    active_retry_policy = retry_policy or RetryPolicy()

    provider_result = fetch_provider_payload_with_failover(
        normalized_symbol,
        timeframe,
        normalized_start,
        normalized_end,
        settings=active_settings,
        provider_fetcher=fetcher,
        retry_policy=active_retry_policy,
        sleeper=sleeper,
    )
    parsed_bars = parser(
        provider_result.payload,
        symbol=normalized_symbol,
        timeframe=timeframe,
        data_source=provider_result.provider_name,
    )
    scoped_bars = [
        bar
        for bar in parsed_bars
        if normalized_start <= bar.bar_time <= normalized_end
    ]
    gaps = detect_gaps((bar.bar_time for bar in scoped_bars), timeframe)

    try:
        inserted, skipped = _persist_bars(session, scoped_bars)
        session.commit()
    except Exception:
        session.rollback()
        raise

    return SyncSummary(
        bars_seen=len(scoped_bars),
        bars_inserted=inserted,
        bars_skipped=skipped,
        gap_count=len(gaps),
        gaps=gaps,
    )


def sync_bars(
    session: Session,
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    settings: Settings | None = None,
    provider_fetcher: Callable[[str, str, datetime, datetime, float], dict[str, Any]] | None = None,
    provider_parser: Callable[..., list[MarketBarInput]] | None = None,
    retry_policy: RetryPolicy | None = None,
    sleeper: Callable[[float], None] = sleep,
) -> int:
    summary = sync_bars_with_details(
        session,
        symbol=symbol,
        timeframe=timeframe,
        start=start,
        end=end,
        settings=settings,
        provider_fetcher=provider_fetcher,
        provider_parser=provider_parser,
        retry_policy=retry_policy,
        sleeper=sleeper,
    )
    return summary.bars_inserted
