from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings


settings = get_settings()

celery_app = Celery(
    "gold_agent",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.analysis", "app.tasks.live", "app.tasks.market", "app.tasks.news", "app.tasks.paper"],
)

celery_app.conf.timezone = "UTC"
celery_app.conf.enable_utc = True
celery_app.conf.beat_schedule = {
    "fetch-news-every-5min": {
        "task": "app.tasks.news.task_fetch_news",
        "schedule": crontab(minute="*/5"),
    },
    "probe-unhealthy-news-sources-hourly": {
        "task": "app.tasks.news.task_fetch_news",
        "schedule": crontab(minute=0),
        "kwargs": {"only_unhealthy": True},
    },
    "analyze-pending-news-every-10min": {
        "task": "app.tasks.analysis.task_analyze_news",
        "schedule": crontab(minute="*/10"),
    },
    "sync-market-bars-15m": {
        "task": "app.tasks.market.task_sync_market_bars",
        "schedule": crontab(minute="*/15"),
        "kwargs": {"timeframe": "15m"},
    },
    "sync-market-bars-hourly": {
        "task": "app.tasks.market.task_sync_market_bars",
        "schedule": crontab(minute=0),
        "kwargs": {"timeframe": "1h"},
    },
    "sync-market-bars-4h": {
        "task": "app.tasks.market.task_sync_market_bars",
        "schedule": crontab(minute=0, hour="*/4"),
        "kwargs": {"timeframe": "4h"},
    },
    "sync-market-bars-daily": {
        "task": "app.tasks.market.task_sync_market_bars",
        "schedule": crontab(minute=0, hour=0),
        "kwargs": {"timeframe": "1d"},
    },
    "check-paper-position-stops-every-minute": {
        "task": "app.tasks.paper.task_check_stops",
        "schedule": crontab(minute="*"),
    },
    "execute-pending-signals-every-5min": {
        "task": "app.tasks.paper.task_execute_pending_signals",
        "schedule": crontab(minute="*/5"),
    },
    "collect-phase5-parallel-observations-every-5min": {
        "task": "app.tasks.live.task_collect_parallel_observations",
        "schedule": crontab(minute="*/5"),
    },
}
