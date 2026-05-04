"""
SQLite persistence layer.

Tables
------
trades          — every executed / closed trade
backtest_results — rolling backtest scores per strategy
strategy_state  — enabled/disabled flag + consecutive-fail counter
"""

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import DB_PATH
from utils.logger import get_logger

log = get_logger(__name__)

_lock = threading.Lock()


@contextmanager
def _conn():
    with _lock:
        con = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()


def init_db() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with _conn() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy        TEXT    NOT NULL,
                direction       TEXT    NOT NULL,
                symbol          TEXT    NOT NULL,
                entry_price     REAL    NOT NULL,
                stop_loss       REAL    NOT NULL,
                take_profit     REAL    NOT NULL,
                lot_size        REAL    NOT NULL,
                confidence      REAL    NOT NULL,
                timeframe       TEXT    NOT NULL,
                mt5_ticket      INTEGER,
                status          TEXT    DEFAULT 'OPEN',
                close_price     REAL,
                pnl             REAL,
                opened_at       TIMESTAMP NOT NULL,
                closed_at       TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS backtest_results (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy        TEXT    NOT NULL,
                run_date        DATE    NOT NULL,
                win_rate        REAL    NOT NULL,
                profit_factor   REAL    NOT NULL,
                max_drawdown    REAL    NOT NULL,
                total_trades    INTEGER NOT NULL,
                score           REAL    NOT NULL,
                params_json     TEXT
            );

            CREATE TABLE IF NOT EXISTS strategy_state (
                strategy            TEXT PRIMARY KEY,
                enabled             INTEGER NOT NULL DEFAULT 1,
                consecutive_fails   INTEGER NOT NULL DEFAULT 0,
                disabled_at         TIMESTAMP,
                params_json         TEXT
            );
        """)
    log.info("Database initialised at %s", DB_PATH)


# ── Trades ────────────────────────────────────────────────────────────────────

def insert_trade(trade: Dict[str, Any]) -> int:
    sql = """
        INSERT INTO trades
            (strategy, direction, symbol, entry_price, stop_loss, take_profit,
             lot_size, confidence, timeframe, mt5_ticket, status, opened_at)
        VALUES
            (:strategy, :direction, :symbol, :entry_price, :stop_loss, :take_profit,
             :lot_size, :confidence, :timeframe, :mt5_ticket, 'OPEN', :opened_at)
    """
    trade.setdefault("opened_at", datetime.utcnow())
    with _conn() as con:
        cur = con.execute(sql, trade)
        return cur.lastrowid


def close_trade(trade_id: int, close_price: float, pnl: float) -> None:
    with _conn() as con:
        con.execute(
            """UPDATE trades SET status='CLOSED', close_price=?, pnl=?, closed_at=?
               WHERE id=?""",
            (close_price, pnl, datetime.utcnow(), trade_id),
        )


def get_open_trades() -> List[sqlite3.Row]:
    with _conn() as con:
        return con.execute("SELECT * FROM trades WHERE status='OPEN'").fetchall()


def get_trades_today() -> List[sqlite3.Row]:
    today = datetime.utcnow().date().isoformat()
    with _conn() as con:
        return con.execute(
            "SELECT * FROM trades WHERE date(opened_at)=?", (today,)
        ).fetchall()


def get_daily_pnl() -> float:
    rows = get_trades_today()
    return sum(r["pnl"] or 0.0 for r in rows if r["status"] == "CLOSED")


# ── Backtest results ──────────────────────────────────────────────────────────

def insert_backtest_result(result: Dict[str, Any]) -> None:
    sql = """
        INSERT INTO backtest_results
            (strategy, run_date, win_rate, profit_factor, max_drawdown,
             total_trades, score, params_json)
        VALUES
            (:strategy, :run_date, :win_rate, :profit_factor, :max_drawdown,
             :total_trades, :score, :params_json)
    """
    result.setdefault("run_date", datetime.utcnow().date().isoformat())
    with _conn() as con:
        con.execute(sql, result)


def get_recent_scores(strategy: str, days: int = 3) -> List[float]:
    with _conn() as con:
        rows = con.execute(
            """SELECT score FROM backtest_results
               WHERE strategy=?
               ORDER BY run_date DESC LIMIT ?""",
            (strategy, days),
        ).fetchall()
    return [r["score"] for r in rows]


# ── Strategy state ────────────────────────────────────────────────────────────

def upsert_strategy_state(strategy: str, enabled: bool, consecutive_fails: int,
                           params_json: Optional[str] = None) -> None:
    with _conn() as con:
        con.execute(
            """INSERT INTO strategy_state (strategy, enabled, consecutive_fails, params_json)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(strategy) DO UPDATE SET
                   enabled=excluded.enabled,
                   consecutive_fails=excluded.consecutive_fails,
                   disabled_at=CASE WHEN excluded.enabled=0 THEN CURRENT_TIMESTAMP ELSE NULL END,
                   params_json=COALESCE(excluded.params_json, params_json)""",
            (strategy, int(enabled), consecutive_fails, params_json),
        )


def get_strategy_state(strategy: str) -> Optional[sqlite3.Row]:
    with _conn() as con:
        return con.execute(
            "SELECT * FROM strategy_state WHERE strategy=?", (strategy,)
        ).fetchone()


def _update_ticket(trade_id: int, ticket: int) -> None:
    with _conn() as con:
        con.execute(
            "UPDATE trades SET mt5_ticket=?, status='OPEN' WHERE id=?",
            (ticket, trade_id),
        )


def get_all_strategy_states() -> List[sqlite3.Row]:
    with _conn() as con:
        return con.execute("SELECT * FROM strategy_state").fetchall()
