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

from app.models import BacktestRun, MarketBar, NewsItem, SentimentScore, StrategyRun
from app.schemas import BacktestCreateRequest
from app.services.backtest_engine import create_and_run_backtest, run_backtest
from app.services.signal_engine import ModelRegistry, XGBoostStrategy


def _market_bar(hours: int, open_price: str, close_price: str) -> MarketBar:
    open_decimal = Decimal(open_price)
    close_decimal = Decimal(close_price)
    return MarketBar(
        timeframe="1h",
        bar_time=datetime(2026, 4, 1, hours, 0, tzinfo=UTC),
        open=open_decimal,
        high=max(open_decimal, close_decimal) + Decimal("1.00000000"),
        low=min(open_decimal, close_decimal) - Decimal("1.00000000"),
        close=close_decimal,
        volume=Decimal("10.00000000"),
    )


def _market_bar_ohlc(hours: int, open_price: str, high_price: str, low_price: str, close_price: str) -> MarketBar:
    return MarketBar(
        timeframe="1h",
        bar_time=datetime(2026, 4, 1, hours, 0, tzinfo=UTC),
        open=Decimal(open_price),
        high=Decimal(high_price),
        low=Decimal(low_price),
        close=Decimal(close_price),
        volume=Decimal("10.00000000"),
    )


def _sentiment_fixture(*, published_at: datetime, title_hash: str, score: str) -> tuple[NewsItem, SentimentScore]:
    item = NewsItem(
        title=f"Fixture {title_hash[:8]}",
        content="Fixture content",
        published_at=published_at,
        title_hash=title_hash,
        status="analyzed",
    )
    sentiment = SentimentScore(
        news_item=item,
        analyzer_type="rule_based",
        sentiment="positive" if Decimal(score) > 0 else "negative",
        score=Decimal(score),
        confidence=Decimal("0.9000"),
        reasoning="Fixture sentiment",
        created_at=published_at + timedelta(minutes=1),
    )
    return item, sentiment


def _seed_backtest_fixture(db_session) -> StrategyRun:
    strategy = StrategyRun(
        strategy_name="sentiment_backtest_v1",
        version="1.0.0",
        parameters={
            "lookback_hours": 2,
            "momentum_bars": 1,
            "positive_sentiment_threshold": "0.3000",
            "negative_sentiment_threshold": "-0.3000",
            "positive_momentum_threshold": "0.0001",
            "negative_momentum_threshold": "-0.0001",
        },
        is_active=True,
    )
    positive_news, positive_sentiment = _sentiment_fixture(
        published_at=datetime(2026, 4, 1, 1, 30, tzinfo=UTC),
        title_hash="1" * 64,
        score="0.8000",
    )
    negative_news, negative_sentiment = _sentiment_fixture(
        published_at=datetime(2026, 4, 1, 3, 30, tzinfo=UTC),
        title_hash="2" * 64,
        score="-0.9000",
    )
    db_session.add(strategy)
    db_session.add_all(
        [
            positive_news,
            positive_sentiment,
            negative_news,
            negative_sentiment,
            _market_bar(0, "100.00000000", "100.00000000"),
            _market_bar(1, "100.00000000", "101.00000000"),
            _market_bar(2, "102.00000000", "104.00000000"),
            _market_bar(3, "104.00000000", "103.00000000"),
            _market_bar(4, "103.00000000", "99.00000000"),
            _market_bar(5, "99.00000000", "98.00000000"),
        ]
    )
    db_session.commit()
    return strategy


def test_run_backtest_processes_bars_and_matches_known_result(db_session) -> None:
    strategy = _seed_backtest_fixture(db_session)

    result = run_backtest(
        db_session,
        BacktestCreateRequest(
            strategy_run_id=strategy.id,
            start_date=datetime(2026, 4, 1, tzinfo=UTC).date(),
            end_date=datetime(2026, 4, 1, tzinfo=UTC).date(),
            initial_capital=Decimal("1000.00"),
            slippage_bps=0,
            commission_bps=0,
        ),
        persist=False,
    )

    assert result.status == "completed"
    assert result.total_trades == 2
    assert result.final_capital == Decimal("1058.82")
    assert result.total_return == Decimal("0.058824")
    assert result.max_drawdown == Decimal("-0.009615")
    assert result.sharpe_ratio == Decimal("0.558211")
    assert result.win_rate == Decimal("1.0000")
    assert result.result_detail is not None
    assert result.result_detail["bars_processed"] == 6
    assert len(result.result_detail["signal_log"]) == 6
    assert len(result.result_detail["trade_log"]) == 2
    assert result.result_detail["trade_log"][0]["entry_time"] == "2026-04-01T02:00:00+00:00"
    assert result.result_detail["trade_log"][1]["side"] == "SHORT"


def test_run_backtest_reuses_feature_signal_entry_points_without_lookahead(db_session) -> None:
    strategy = StrategyRun(
        strategy_name="leakage_check",
        version="1.0.0",
        parameters={
            "lookback_hours": 2,
            "momentum_bars": 1,
            "positive_sentiment_threshold": "0.3000",
            "negative_sentiment_threshold": "-0.3000",
            "positive_momentum_threshold": "0.0001",
            "negative_momentum_threshold": "-0.0001",
        },
        is_active=True,
    )
    positive_news, positive_sentiment = _sentiment_fixture(
        published_at=datetime(2026, 4, 1, 1, 30, tzinfo=UTC),
        title_hash="3" * 64,
        score="0.8000",
    )
    future_news, future_sentiment = _sentiment_fixture(
        published_at=datetime(2026, 4, 1, 2, 0, tzinfo=UTC),
        title_hash="4" * 64,
        score="-0.9500",
    )
    db_session.add(strategy)
    db_session.add_all(
        [
            positive_news,
            positive_sentiment,
            future_news,
            future_sentiment,
            _market_bar(0, "100.00000000", "100.00000000"),
            _market_bar(1, "100.00000000", "101.00000000"),
            _market_bar(2, "102.00000000", "104.00000000"),
            _market_bar(3, "104.00000000", "105.00000000"),
        ]
    )
    db_session.commit()

    result = run_backtest(
        db_session,
        BacktestCreateRequest(
            strategy_run_id=strategy.id,
            start_date=datetime(2026, 4, 1, tzinfo=UTC).date(),
            end_date=datetime(2026, 4, 1, tzinfo=UTC).date(),
            initial_capital=Decimal("1000.00"),
            slippage_bps=0,
            commission_bps=0,
        ),
        persist=False,
    )

    signal_at_two = next(
        item for item in result.result_detail["signal_log"] if item["timestamp"] == "2026-04-01T02:00:00+00:00"
    )
    assert signal_at_two["direction"] == "BUY"
    assert signal_at_two["features_used"]["sentiment_mean"] == "0.8000"


def test_run_backtest_uses_ensemble_strategy_through_shared_signal_entry(db_session) -> None:
    strategy = StrategyRun(
        strategy_name="ensemble_v1",
        version="0.1.0",
        parameters={
            "lookback_hours": 2,
            "momentum_bars": 1,
            "members": [
                {
                    "strategy_name": "sentiment_momentum_v1",
                    "version": "1.0.0",
                    "weight": "1.0000",
                    "parameters": {
                        "positive_sentiment_threshold": "0.3000",
                        "negative_sentiment_threshold": "-0.3000",
                        "positive_momentum_threshold": "0.0001",
                        "negative_momentum_threshold": "-0.0001",
                    },
                }
            ],
        },
        is_active=True,
    )
    positive_news, positive_sentiment = _sentiment_fixture(
        published_at=datetime(2026, 4, 1, 1, 30, tzinfo=UTC),
        title_hash="33" * 32,
        score="0.8000",
    )
    db_session.add(strategy)
    db_session.add_all(
        [
            positive_news,
            positive_sentiment,
            _market_bar(0, "100.00000000", "100.00000000"),
            _market_bar(1, "100.00000000", "101.00000000"),
            _market_bar(2, "102.00000000", "104.00000000"),
            _market_bar(3, "104.00000000", "105.00000000"),
        ]
    )
    db_session.commit()

    result = run_backtest(
        db_session,
        BacktestCreateRequest(
            strategy_run_id=strategy.id,
            start_date=datetime(2026, 4, 1, tzinfo=UTC).date(),
            end_date=datetime(2026, 4, 1, tzinfo=UTC).date(),
            initial_capital=Decimal("1000.00"),
            slippage_bps=0,
            commission_bps=0,
        ),
        persist=False,
    )

    signal_at_two = next(
        item for item in result.result_detail["signal_log"] if item["timestamp"] == "2026-04-01T02:00:00+00:00"
    )
    assert signal_at_two["direction"] == "BUY"
    assert "ensemble_v1" in signal_at_two["reasoning"]
    assert signal_at_two["features_used"]["sentiment_mean"] == "0.8000"


def test_run_backtest_excludes_sentiment_created_after_bar_time(db_session) -> None:
    strategy = StrategyRun(
        strategy_name="availability_check",
        version="1.0.0",
        parameters={
            "lookback_hours": 2,
            "momentum_bars": 1,
            "positive_sentiment_threshold": "0.3000",
            "negative_sentiment_threshold": "-0.3000",
            "positive_momentum_threshold": "0.0001",
            "negative_momentum_threshold": "-0.0001",
        },
        is_active=True,
    )
    positive_news, positive_sentiment = _sentiment_fixture(
        published_at=datetime(2026, 4, 1, 1, 30, tzinfo=UTC),
        title_hash="5" * 64,
        score="0.8000",
    )
    delayed_news, delayed_sentiment = _sentiment_fixture(
        published_at=datetime(2026, 4, 1, 1, 45, tzinfo=UTC),
        title_hash="6" * 64,
        score="-0.9500",
    )
    delayed_sentiment.created_at = datetime(2026, 4, 1, 4, 0, tzinfo=UTC)
    db_session.add(strategy)
    db_session.add_all(
        [
            positive_news,
            positive_sentiment,
            delayed_news,
            delayed_sentiment,
            _market_bar(0, "100.00000000", "100.00000000"),
            _market_bar(1, "100.00000000", "101.00000000"),
            _market_bar(2, "102.00000000", "104.00000000"),
            _market_bar(3, "104.00000000", "105.00000000"),
        ]
    )
    db_session.commit()

    result = run_backtest(
        db_session,
        BacktestCreateRequest(
            strategy_run_id=strategy.id,
            start_date=datetime(2026, 4, 1, tzinfo=UTC).date(),
            end_date=datetime(2026, 4, 1, tzinfo=UTC).date(),
            initial_capital=Decimal("1000.00"),
            slippage_bps=0,
            commission_bps=0,
        ),
        persist=False,
    )

    signal_at_two = next(
        item for item in result.result_detail["signal_log"] if item["timestamp"] == "2026-04-01T02:00:00+00:00"
    )
    assert signal_at_two["features_used"]["sentiment_mean"] == "0.8000"


def test_run_backtest_models_slippage_and_commission(db_session) -> None:
    strategy = _seed_backtest_fixture(db_session)
    zero_costs = run_backtest(
        db_session,
        BacktestCreateRequest(
            strategy_run_id=strategy.id,
            start_date=datetime(2026, 4, 1, tzinfo=UTC).date(),
            end_date=datetime(2026, 4, 1, tzinfo=UTC).date(),
            initial_capital=Decimal("1000.00"),
            slippage_bps=0,
            commission_bps=0,
        ),
        persist=False,
    )
    with_costs = run_backtest(
        db_session,
        BacktestCreateRequest(
            strategy_run_id=strategy.id,
            start_date=datetime(2026, 4, 1, tzinfo=UTC).date(),
            end_date=datetime(2026, 4, 1, tzinfo=UTC).date(),
            initial_capital=Decimal("1000.00"),
            slippage_bps=10,
            commission_bps=10,
        ),
        persist=False,
    )

    assert with_costs.final_capital < zero_costs.final_capital
    assert Decimal(with_costs.result_detail["trade_log"][0]["commission"]) > Decimal("0")


def test_run_backtest_triggers_configured_stop_loss_bar_by_bar(db_session, monkeypatch) -> None:
    strategy = StrategyRun(
        strategy_name="backtest_stop_loss",
        version="1.0.0",
        parameters={
            "lookback_hours": 2,
            "momentum_bars": 1,
            "paper": {"stop_loss_distance": "5.00000000"},
        },
        is_active=True,
    )
    db_session.add(strategy)
    db_session.add_all(
        [
            _market_bar_ohlc(0, "100.00000000", "101.00000000", "99.00000000", "100.00000000"),
            _market_bar_ohlc(1, "100.00000000", "101.00000000", "94.00000000", "96.00000000"),
            _market_bar_ohlc(2, "96.00000000", "97.00000000", "95.00000000", "96.00000000"),
        ]
    )
    db_session.commit()
    calls = {"count": 0}

    def fake_signal(*args, **kwargs):
        calls["count"] += 1
        return type("Decision", (), {"direction": "BUY" if calls["count"] == 1 else "HOLD", "reasoning": "fixture"})()

    monkeypatch.setattr("app.services.backtest_engine.service.generate_signal", fake_signal)

    result = run_backtest(
        db_session,
        BacktestCreateRequest(
            strategy_run_id=strategy.id,
            start_date=datetime(2026, 4, 1, tzinfo=UTC).date(),
            end_date=datetime(2026, 4, 1, tzinfo=UTC).date(),
            initial_capital=Decimal("1000.00"),
            slippage_bps=0,
            commission_bps=0,
        ),
        persist=False,
    )

    trade = result.result_detail["trade_log"][0]
    assert result.total_trades == 1
    assert trade["exit_reason"] == "stop_loss"
    assert trade["exit_time"] == "2026-04-01T01:00:00+00:00"
    assert trade["exit_price"] == "95.00000000"
    assert trade["net_pnl"] == "-50.00000000"


def test_run_backtest_triggers_configured_take_profit_bar_by_bar(db_session, monkeypatch) -> None:
    strategy = StrategyRun(
        strategy_name="backtest_take_profit",
        version="1.0.0",
        parameters={
            "lookback_hours": 2,
            "momentum_bars": 1,
            "paper": {"take_profit_distance": "8.00000000"},
        },
        is_active=True,
    )
    db_session.add(strategy)
    db_session.add_all(
        [
            _market_bar_ohlc(0, "100.00000000", "101.00000000", "99.00000000", "100.00000000"),
            _market_bar_ohlc(1, "100.00000000", "109.00000000", "99.00000000", "108.00000000"),
            _market_bar_ohlc(2, "108.00000000", "109.00000000", "107.00000000", "108.00000000"),
        ]
    )
    db_session.commit()
    calls = {"count": 0}

    def fake_signal(*args, **kwargs):
        calls["count"] += 1
        return type("Decision", (), {"direction": "BUY" if calls["count"] == 1 else "HOLD", "reasoning": "fixture"})()

    monkeypatch.setattr("app.services.backtest_engine.service.generate_signal", fake_signal)

    result = run_backtest(
        db_session,
        BacktestCreateRequest(
            strategy_run_id=strategy.id,
            start_date=datetime(2026, 4, 1, tzinfo=UTC).date(),
            end_date=datetime(2026, 4, 1, tzinfo=UTC).date(),
            initial_capital=Decimal("1000.00"),
            slippage_bps=0,
            commission_bps=0,
        ),
        persist=False,
    )

    trade = result.result_detail["trade_log"][0]
    assert result.total_trades == 1
    assert trade["exit_reason"] == "take_profit"
    assert trade["exit_time"] == "2026-04-01T01:00:00+00:00"
    assert trade["exit_price"] == "108.00000000"
    assert trade["net_pnl"] == "80.00000000"


def test_run_backtest_resolves_active_xgboost_model_from_registry(db_session, monkeypatch) -> None:
    strategy = StrategyRun(
        strategy_name="xgboost_v1",
        version="0.1.0",
        parameters={
            "lookback_hours": 2,
            "momentum_bars": 1,
        },
        is_active=True,
    )
    positive_news, positive_sentiment = _sentiment_fixture(
        published_at=datetime(2026, 4, 1, 0, 30, tzinfo=UTC),
        title_hash="7" * 64,
        score="0.7000",
    )
    db_session.add(strategy)
    db_session.add_all(
        [
            positive_news,
            positive_sentiment,
            _market_bar(0, "100.00000000", "100.00000000"),
            _market_bar(1, "101.00000000", "102.00000000"),
            _market_bar(2, "102.00000000", "103.00000000"),
            _market_bar(3, "103.00000000", "104.00000000"),
        ]
    )
    ModelRegistry(db_session).register_model_version(
        model_name="xgboost_v1",
        version="0.2.0",
        model_type="xgboost",
        artifact_uri="models/backtest-active-xgboost.json",
        feature_schema={"features": ["sentiment_mean", "price_momentum_4h"]},
        metrics={"auc": "0.5200"},
        status="validated",
        is_active=True,
        trained_at=datetime(2026, 4, 1, 0, 0, tzinfo=UTC),
    )
    db_session.commit()

    loaded_artifacts: list[str] = []

    def fake_load_model(self, artifact_uri: str):
        loaded_artifacts.append(artifact_uri)
        return object()

    def fake_predict(self, model, features) -> Decimal:
        return Decimal("0.9000")

    monkeypatch.setattr(XGBoostStrategy, "_load_model", fake_load_model)
    monkeypatch.setattr(XGBoostStrategy, "_predict", fake_predict)

    result = run_backtest(
        db_session,
        BacktestCreateRequest(
            strategy_run_id=strategy.id,
            start_date=datetime(2026, 4, 1, tzinfo=UTC).date(),
            end_date=datetime(2026, 4, 1, tzinfo=UTC).date(),
            initial_capital=Decimal("1000.00"),
            slippage_bps=0,
            commission_bps=0,
        ),
        persist=False,
    )

    assert loaded_artifacts
    assert set(loaded_artifacts) == {"models/backtest-active-xgboost.json"}
    assert any(item["direction"] == "BUY" for item in result.result_detail["signal_log"])
    assert any(
        item["reasoning"] == "buy from xgboost_v1 probability=0.9000"
        for item in result.result_detail["signal_log"]
    )


def test_run_backtest_rejects_insufficient_data(db_session) -> None:
    strategy = StrategyRun(
        strategy_name="insufficient_backtest",
        version="1.0.0",
        parameters={"lookback_hours": 2, "momentum_bars": 1},
        is_active=True,
    )
    db_session.add(strategy)
    db_session.add(_market_bar(0, "100.00000000", "100.00000000"))
    db_session.commit()

    with pytest.raises(Exception) as exc_info:
        run_backtest(
            db_session,
            BacktestCreateRequest(
                strategy_run_id=strategy.id,
                start_date=datetime(2026, 4, 1, tzinfo=UTC).date(),
                end_date=datetime(2026, 4, 1, tzinfo=UTC).date(),
                initial_capital=Decimal("1000.00"),
                slippage_bps=0,
                commission_bps=0,
            ),
            persist=False,
        )

    assert exc_info.value.__class__.__name__ == "BacktestDataInsufficientError"


def test_runtime_failure_persists_failed_backtest_row(db_session, monkeypatch) -> None:
    strategy = _seed_backtest_fixture(db_session)

    def explode(*args, **kwargs):
        raise RuntimeError("synthetic backtest failure")

    monkeypatch.setattr("app.services.backtest_engine.service.generate_signal", explode)

    with pytest.raises(RuntimeError, match="synthetic backtest failure"):
        create_and_run_backtest(
            db_session,
            BacktestCreateRequest(
                strategy_run_id=strategy.id,
                start_date=datetime(2026, 4, 1, tzinfo=UTC).date(),
                end_date=datetime(2026, 4, 1, tzinfo=UTC).date(),
                initial_capital=Decimal("1000.00"),
                slippage_bps=0,
                commission_bps=0,
            ),
        )

    failed_runs = db_session.execute(select(BacktestRun).order_by(BacktestRun.created_at.desc())).scalars().all()

    assert len(failed_runs) == 1
    assert failed_runs[0].status == "failed"
    assert failed_runs[0].error_message == "synthetic backtest failure"
    assert failed_runs[0].completed_at is not None
