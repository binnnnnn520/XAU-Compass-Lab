from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from functools import cached_property
import json
from urllib.parse import urlparse


DEFAULT_NEWS_SOURCES_JSON_VALUE = json.dumps(
    [
        {
            "name": "Reuters RSS",
            "url": "https://feeds.reuters.com/reuters/businessNews",
            "source_type": "rss",
            "fetch_interval": 300,
        },
        {
            "name": "Kitco RSS",
            "url": "https://www.kitco.com/rss/news",
            "source_type": "rss",
            "fetch_interval": 300,
        },
        {
            "name": "Investing Gold News RSS",
            "url": "https://www.investing.com/rss/news_25.rss",
            "source_type": "rss",
            "fetch_interval": 600,
        },
        {
            "name": "Mining.com Gold RSS",
            "url": "https://www.mining.com/commodity/gold/feed/",
            "source_type": "rss",
            "fetch_interval": 900,
        },
    ]
)
DEFAULT_CORS_ALLOWED_ORIGINS = json.dumps(["http://localhost:3000"])


def _coerce_bool(value: str | bool | None, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _coerce_port(value: str | int | None, default: int) -> int:
    if value is None:
        return default
    return int(value)


def _coerce_decimal(value: str | Decimal | None, default: str) -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(value.strip())


def _coerce_string_list(value: str, *, name: str) -> list[str]:
    raw = value.strip()
    if raw.startswith("["):
        payload = json.loads(raw)
        if not isinstance(payload, list):
            raise ValueError(f"{name} must be a JSON array or comma-separated list.")
        items = payload
    else:
        items = raw.split(",")

    parsed = [str(item).strip() for item in items if str(item).strip()]
    if not parsed:
        raise ValueError(f"{name} must contain at least one value.")
    return parsed


@dataclass(frozen=True)
class Settings:
    app_version: str = os.getenv("APP_VERSION", "0.1.0")
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql://gold_agent@localhost:5432/gold_agent",
    )
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    connect_timeout_seconds: float = float(os.getenv("CONNECT_TIMEOUT_SECONDS", "1.5"))
    news_fetch_timeout_seconds: float = float(os.getenv("NEWS_FETCH_TIMEOUT_SECONDS", "10"))
    market_fetch_timeout_seconds: float = float(os.getenv("MARKET_FETCH_TIMEOUT_SECONDS", "10"))
    market_data_source: str = os.getenv("MARKET_DATA_SOURCE", "yahoo_finance")
    market_sync_lookback_hours: int = int(os.getenv("MARKET_SYNC_LOOKBACK_HOURS", "5000"))
    default_news_sources_json: str = os.getenv("DEFAULT_NEWS_SOURCES_JSON", DEFAULT_NEWS_SOURCES_JSON_VALUE)
    cors_allowed_origins_raw: str = os.getenv("CORS_ALLOWED_ORIGINS", DEFAULT_CORS_ALLOWED_ORIGINS)
    market_data_sources_json: str = os.getenv("MARKET_DATA_SOURCES_JSON", "")
    llm_analysis_enabled: bool = _coerce_bool(os.getenv("LLM_ANALYSIS_ENABLED"), False)
    llm_provider: str = os.getenv("LLM_PROVIDER", "openai")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "ZhipuAI/GLM-5")
    llm_timeout_seconds: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "20"))
    llm_max_retries: int = int(os.getenv("LLM_MAX_RETRIES", "2"))
    llm_endpoint_url: str = os.getenv(
        "LLM_ENDPOINT_URL",
        "https://api-inference.modelscope.cn/v1/chat/completions",
    )
    llm_cache_enabled: bool = _coerce_bool(os.getenv("LLM_CACHE_ENABLED"), True)
    llm_batch_enabled: bool = _coerce_bool(os.getenv("LLM_BATCH_ENABLED"), True)
    llm_batch_max_items: int = int(os.getenv("LLM_BATCH_MAX_ITEMS", "5"))
    llm_daily_budget_usd: Decimal = _coerce_decimal(os.getenv("LLM_DAILY_BUDGET_USD"), "5.0000")
    phase5_observation_collection_enabled: bool = _coerce_bool(
        os.getenv("PHASE5_OBSERVATION_COLLECTION_ENABLED"),
        False,
    )
    phase5_evidence_window_started: bool = _coerce_bool(
        os.getenv("PHASE5_EVIDENCE_WINDOW_STARTED"),
        False,
    )
    phase5_ibkr_paper_order_execution_enabled: bool = _coerce_bool(
        os.getenv("PHASE5_IBKR_PAPER_ORDER_EXECUTION_ENABLED"),
        False,
    )

    @property
    def database_host(self) -> str:
        explicit_host = os.getenv("DATABASE_HOST")
        if explicit_host:
            return explicit_host
        parsed = urlparse(self.database_url)
        return parsed.hostname or "localhost"

    @property
    def database_port(self) -> int:
        explicit_port = os.getenv("DATABASE_PORT")
        if explicit_port:
            return _coerce_port(explicit_port, 5432)
        parsed = urlparse(self.database_url)
        return parsed.port or 5432

    @property
    def redis_host(self) -> str:
        explicit_host = os.getenv("REDIS_HOST")
        if explicit_host:
            return explicit_host
        parsed = urlparse(self.redis_url)
        return parsed.hostname or "localhost"

    @property
    def redis_port(self) -> int:
        explicit_port = os.getenv("REDIS_PORT")
        if explicit_port:
            return _coerce_port(explicit_port, 6379)
        parsed = urlparse(self.redis_url)
        return parsed.port or 6379

    @cached_property
    def default_news_sources(self) -> list[dict[str, object]]:
        payload = json.loads(self.default_news_sources_json)
        if not isinstance(payload, list):
            raise ValueError("DEFAULT_NEWS_SOURCES_JSON must be a JSON array.")

        sources: list[dict[str, object]] = []
        for item in payload:
            if not isinstance(item, dict):
                raise ValueError("Each default news source must be a JSON object.")

            name = str(item["name"]).strip()
            url = str(item["url"]).strip()
            source_type = str(item.get("source_type", "rss")).strip() or "rss"
            fetch_interval = int(item.get("fetch_interval", 300))

            sources.append(
                {
                    "name": name,
                    "url": url,
                    "source_type": source_type,
                    "fetch_interval": fetch_interval,
                    "config": item.get("config", {}),
                }
            )

        return sources

    @cached_property
    def market_data_sources(self) -> list[dict[str, object]]:
        if not self.market_data_sources_json.strip():
            return [{"name": self.market_data_source, "symbol_map": {}}]

        payload = json.loads(self.market_data_sources_json)
        if not isinstance(payload, list):
            raise ValueError("MARKET_DATA_SOURCES_JSON must be a JSON array.")

        sources: list[dict[str, object]] = []
        for item in payload:
            if not isinstance(item, dict):
                raise ValueError("Each market data source must be a JSON object.")
            name = str(item["name"]).strip()
            symbol_map = item.get("symbol_map", {})
            sources.append(
                {
                    "name": name,
                    "symbol_map": symbol_map if isinstance(symbol_map, dict) else {},
                }
            )
        if not sources:
            raise ValueError("MARKET_DATA_SOURCES_JSON must contain at least one source.")
        return sources

    @cached_property
    def cors_allowed_origins(self) -> list[str]:
        return _coerce_string_list(self.cors_allowed_origins_raw, name="CORS_ALLOWED_ORIGINS")


def get_settings() -> Settings:
    return Settings()
