"""
Optuna-based hyperparameter optimizer.

For each strategy, defines a search space of key parameters, runs N trials,
and returns the best parameter set based on the composite performance score.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from config import (
    ATR_MULTIPLIER_SL,
    ATR_MULTIPLIER_TP,
    BREAKOUT_ATR_QUIET_MULT,
    BREAKOUT_CONSOLIDATION_BARS,
    BREAKOUT_VOL_MULT,
    LIQSWEEP_EQ_THRESHOLD_PIPS,
    LIQSWEEP_LOOKBACK,
    LIQSWEEP_OB_LOOKBACK,
    MOM_FVG_MIN_PIPS,
    MOM_MACD_FAST,
    MOM_MACD_SIGNAL,
    MOM_MACD_SLOW,
    MOM_RSI_PERIOD,
    OPTUNA_TIMEOUT_SECONDS,
    OPTUNA_TRIALS,
    STRATEGY_SCORE_WEIGHTS,
    TREND_HTF_EMA_FAST,
    TREND_HTF_EMA_SLOW,
    TREND_OB_LOOKBACK,
)
from intelligence.backtester import run_backtest
from utils.logger import get_logger

log = get_logger(__name__)

try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    OPTUNA_AVAILABLE = True
except ImportError:
    OPTUNA_AVAILABLE = False
    log.warning("optuna not installed — optimization skipped")


def _score(win_rate: float, profit_factor: float, max_drawdown: float) -> float:
    """Composite performance score in [0, 1]."""
    w = STRATEGY_SCORE_WEIGHTS
    pf_norm = min(profit_factor / 3.0, 1.0)   # cap at 3× profit factor
    dd_score = max(0.0, 1.0 - max_drawdown)    # lower DD = better
    return (
        w["win_rate"] * win_rate
        + w["profit_factor"] * pf_norm
        + w["max_drawdown"] * dd_score
    )


# ── Parameter search spaces ───────────────────────────────────────────────────

def _liquidity_sweep_space(trial) -> Dict[str, Any]:
    return {
        "lookback": trial.suggest_int("lookback", 10, 40),
        "eq_threshold_pips": trial.suggest_float("eq_threshold_pips", 2.0, 10.0),
        "ob_lookback": trial.suggest_int("ob_lookback", 3, 10),
        "sl_multiplier": trial.suggest_float("sl_multiplier", 1.0, 3.0),
        "tp_multiplier": trial.suggest_float("tp_multiplier", 2.0, 5.0),
        "atr_period": trial.suggest_int("atr_period", 10, 21),
    }


def _trend_continuation_space(trial) -> Dict[str, Any]:
    ema_fast = trial.suggest_int("ema_fast", 10, 30)
    ema_slow = trial.suggest_int("ema_slow", ema_fast + 10, 80)
    return {
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "ob_lookback": trial.suggest_int("ob_lookback", 5, 20),
        "sl_multiplier": trial.suggest_float("sl_multiplier", 1.0, 3.0),
        "tp_multiplier": trial.suggest_float("tp_multiplier", 2.0, 5.0),
        "atr_period": trial.suggest_int("atr_period", 10, 21),
    }


def _breakout_space(trial) -> Dict[str, Any]:
    return {
        "consolidation_bars": trial.suggest_int("consolidation_bars", 10, 30),
        "atr_quiet_mult": trial.suggest_float("atr_quiet_mult", 0.4, 0.9),
        "vol_mult": trial.suggest_float("vol_mult", 1.2, 2.5),
        "sl_multiplier": trial.suggest_float("sl_multiplier", 1.0, 3.0),
        "tp_multiplier": trial.suggest_float("tp_multiplier", 2.0, 5.0),
        "atr_period": trial.suggest_int("atr_period", 10, 21),
    }


def _momentum_space(trial) -> Dict[str, Any]:
    macd_fast = trial.suggest_int("macd_fast", 8, 16)
    macd_slow = trial.suggest_int("macd_slow", macd_fast + 8, 30)
    return {
        "rsi_period": trial.suggest_int("rsi_period", 10, 21),
        "macd_fast": macd_fast,
        "macd_slow": macd_slow,
        "macd_signal": trial.suggest_int("macd_signal", 5, 12),
        "fvg_min_pips": trial.suggest_float("fvg_min_pips", 5.0, 20.0),
        "sl_multiplier": trial.suggest_float("sl_multiplier", 1.0, 3.0),
        "tp_multiplier": trial.suggest_float("tp_multiplier", 2.0, 5.0),
        "atr_period": trial.suggest_int("atr_period", 10, 21),
    }


_SEARCH_SPACES = {
    "liquidity_sweep": _liquidity_sweep_space,
    "trend_continuation": _trend_continuation_space,
    "breakout": _breakout_space,
    "momentum": _momentum_space,
}


# ── Optimizer ─────────────────────────────────────────────────────────────────

def optimize_strategy(
    strategy,
    n_trials: int = OPTUNA_TRIALS,
    timeout: int = OPTUNA_TIMEOUT_SECONDS,
) -> Optional[Dict[str, Any]]:
    """
    Run optuna optimization for a strategy. Returns best params dict or None.
    """
    if not OPTUNA_AVAILABLE:
        log.warning("optuna unavailable — returning default params for %s", strategy.name)
        return None

    space_fn = _SEARCH_SPACES.get(strategy.name)
    if space_fn is None:
        log.warning("No search space defined for strategy: %s", strategy.name)
        return None

    study = optuna.create_study(
        direction="maximize",
        study_name=f"{strategy.name}_opt",
        sampler=optuna.samplers.TPESampler(seed=42),
    )

    def objective(trial):
        params = space_fn(trial)
        try:
            result = run_backtest(strategy, params=params)
            if result["total_trades"] < 5:
                return 0.0
            return _score(
                result["win_rate"],
                result["profit_factor"],
                result["max_drawdown"],
            )
        except Exception as exc:
            log.debug("Trial %d failed: %s", trial.number, exc)
            return 0.0

    log.info("Starting optimization for [%s] — %d trials, %ds timeout",
             strategy.name, n_trials, timeout)
    study.optimize(objective, n_trials=n_trials, timeout=timeout, show_progress_bar=False)

    if not study.best_trial or study.best_value == 0.0:
        log.warning("Optimization found no valid trials for [%s]", strategy.name)
        return None

    log.info(
        "[%s] best score: %.4f | params: %s",
        strategy.name, study.best_value, study.best_params,
    )
    return study.best_params


def optimize_all_strategies(strategies: list) -> Dict[str, Optional[Dict]]:
    """Run optimize_strategy for every strategy in the list."""
    results = {}
    for strategy in strategies:
        try:
            best_params = optimize_strategy(strategy)
            results[strategy.name] = best_params
            if best_params:
                strategy.params = best_params
        except Exception as exc:
            log.error("Optimization failed for [%s]: %s", strategy.name, exc)
            results[strategy.name] = None
    return results
