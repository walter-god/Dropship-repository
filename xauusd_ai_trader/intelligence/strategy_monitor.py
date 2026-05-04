"""
Strategy health monitor.

Runs a daily backtest for each strategy, computes a composite score,
tracks consecutive underperforming days, and auto-disables strategies
that fall below the threshold for N consecutive days.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, List

from config import (
    BACKTEST_ROLLING_DAYS,
    STRATEGY_DISABLE_CONSECUTIVE_DAYS,
    STRATEGY_DISABLE_THRESHOLD,
    STRATEGY_SCORE_WEIGHTS,
)
from database import db_manager
from intelligence.backtester import run_backtest
from intelligence.optimizer import optimize_strategy, _score
from utils.logger import get_logger

log = get_logger(__name__)


class StrategyMonitor:
    def __init__(self, strategies: list):
        self.strategies = {s.name: s for s in strategies}
        self._ensure_states()

    # ── Initialisation ────────────────────────────────────────────────────────

    def _ensure_states(self) -> None:
        for name in self.strategies:
            state = db_manager.get_strategy_state(name)
            if state is None:
                db_manager.upsert_strategy_state(name, enabled=True, consecutive_fails=0)

    # ── Daily health check ────────────────────────────────────────────────────

    def run_daily_health_check(self) -> Dict[str, Dict]:
        """
        For each strategy:
          1. Run a rolling-window backtest with current params.
          2. Compute score.
          3. Update DB state and enable/disable accordingly.
        Returns a summary dict keyed by strategy name.
        """
        summary = {}
        for name, strategy in self.strategies.items():
            log.info("Health check: [%s]", name)
            try:
                result = run_backtest(strategy, rolling_days=BACKTEST_ROLLING_DAYS)
                score = _score(
                    result["win_rate"],
                    result["profit_factor"],
                    result["max_drawdown"],
                )
                db_manager.insert_backtest_result({
                    "strategy": name,
                    "win_rate": result["win_rate"],
                    "profit_factor": result["profit_factor"],
                    "max_drawdown": result["max_drawdown"],
                    "total_trades": result["total_trades"],
                    "score": score,
                    "params_json": json.dumps(strategy.params),
                })

                # Check rolling consecutive fails
                recent_scores = db_manager.get_recent_scores(name, STRATEGY_DISABLE_CONSECUTIVE_DAYS)
                consecutive_fails = sum(1 for s in recent_scores if s < STRATEGY_DISABLE_THRESHOLD)
                should_disable = (
                    consecutive_fails >= STRATEGY_DISABLE_CONSECUTIVE_DAYS
                    and len(recent_scores) >= STRATEGY_DISABLE_CONSECUTIVE_DAYS
                )

                state = db_manager.get_strategy_state(name)
                currently_enabled = bool(state["enabled"]) if state else True

                if should_disable and currently_enabled:
                    db_manager.upsert_strategy_state(name, enabled=False,
                                                      consecutive_fails=consecutive_fails)
                    log.warning(
                        "[%s] AUTO-DISABLED — score %.3f below %.3f for %d consecutive days",
                        name, score, STRATEGY_DISABLE_THRESHOLD, consecutive_fails,
                    )
                elif not should_disable and not currently_enabled:
                    db_manager.upsert_strategy_state(name, enabled=True, consecutive_fails=0)
                    log.info("[%s] RE-ENABLED — score %.3f recovered", name, score)
                else:
                    db_manager.upsert_strategy_state(
                        name, enabled=currently_enabled,
                        consecutive_fails=consecutive_fails,
                    )

                summary[name] = {
                    "score": round(score, 4),
                    "win_rate": result["win_rate"],
                    "profit_factor": result["profit_factor"],
                    "max_drawdown": result["max_drawdown"],
                    "total_trades": result["total_trades"],
                    "enabled": not should_disable,
                    "consecutive_fails": consecutive_fails,
                }
                log.info(
                    "[%s] score=%.3f wr=%.1f%% pf=%.2f dd=%.1f%% trades=%d enabled=%s",
                    name, score,
                    result["win_rate"] * 100, result["profit_factor"],
                    result["max_drawdown"] * 100, result["total_trades"],
                    not should_disable,
                )
            except Exception as exc:
                log.error("Health check failed for [%s]: %s", name, exc)
                summary[name] = {"error": str(exc)}

        return summary

    # ── Enable / disable control ──────────────────────────────────────────────

    def get_enabled_strategies(self) -> List:
        enabled = []
        for name, strategy in self.strategies.items():
            state = db_manager.get_strategy_state(name)
            if state is None or bool(state["enabled"]):
                enabled.append(strategy)
        return enabled

    def force_enable(self, name: str) -> None:
        db_manager.upsert_strategy_state(name, enabled=True, consecutive_fails=0)
        log.info("[%s] force-enabled", name)

    def force_disable(self, name: str) -> None:
        db_manager.upsert_strategy_state(name, enabled=False, consecutive_fails=0)
        log.info("[%s] force-disabled", name)

    # ── Status summary ────────────────────────────────────────────────────────

    def get_status(self) -> Dict[str, Dict]:
        status = {}
        for row in db_manager.get_all_strategy_states():
            name = row["strategy"]
            recent = db_manager.get_recent_scores(name, 3)
            status[name] = {
                "enabled": bool(row["enabled"]),
                "consecutive_fails": row["consecutive_fails"],
                "recent_scores": [round(s, 3) for s in recent],
                "disabled_at": row["disabled_at"],
            }
        return status
