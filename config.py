"""
Global strategy settings.
Edit only the plain  NAME = value  lines – no complex syntax.
"""

from pathlib import Path

# ─── Live Bot & Notification Settings ────────────────────────────────
TELEGRAM_BOT_TOKEN    = "7770157032:AAGO-J_Mb8Oxg3i6xQmWTj3rM3JMO5MMscQ"  # Replace with your Bot Token
TELEGRAM_CHAT_ID      = "2133130545"    # Replace with your Chat ID
BOT_TIMEFRAME         = "5m"                       # Timeframe for the bot to check for signals
BOT_SCHEDULE_MINUTES  = 1                          # How often to check for new signals

# In config.py
DEBUG_SYMBOL = "HUSDT"  # Set to a symbol to get detailed logs, or None to disable

# In config.py
SIGNAL_COOLDOWN_MINUTES = 30 # Cooldown per symbol after a signal is sent

# --- Contextual Filters to INCLUDE in the Alert Message ---
# Set these to True to see their status in the Telegram alert.
SHOW_EMA_TREND_CONTEXT    = True
SHOW_RSI_CONTEXT          = True
SHOW_ADX_CONTEXT          = True
SHOW_STRUCTURAL_CONTEXT   = True
SHOW_BTC_FAST_FILTER_CONTEXT = True # We will now use this!

# ─── Portfolio ───────────────────────────────────────────────────────
INITIAL_CAPITAL       = 1_000.0       # USD starting equity
RISK_PCT              = 0.05          # % equity risked per new trade
TAKER_FEE_PCT         = 0.0006        # 0.06 % taker fee
MAKER_FEE_PCT         = 0.0002        # 0.02 % maker rebate (negative ⇒ rebate)

MAX_LEVERAGE          = 10.0          # exchange leverage cap
CONTRACT_STEP_SIZE    = 0.00001       # lot precision (e.g. 0.001 BTC)
MIN_NOTIONAL          = 0.1           # smallest USD notional exchange accepts

FUNDING_FEE_PCT_PER_DAY = 0.005

# ─── Data locations ──────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
RAW_CSV_DIR  = PROJECT_ROOT / "raw_csv"
PARQUET_DIR  = PROJECT_ROOT / "parquet"
SIGNALS_DIR  = PROJECT_ROOT / "signals"
RESULTS_DIR  = PROJECT_ROOT / "results"
SYMBOLS_FILE = PROJECT_ROOT / "symbols.txt"

# ─── Date filter (inclusive) ─────────────────────────────────────────
START_DATE = "2025-06-01"    # ISO date or None
END_DATE   = "2025-07-01"

# ─── Parallelism ─────────────────────────────────────────────────────
MAX_WORKERS = None           # None ⇒ use all logical CPU cores

# ─── Indicator & entry parameters ────────────────────────────────────
ATR_TIMEFRAME            = "1h"
ATR_PERIOD               = 14
EMA_FAST                 = 20
EMA_SLOW                 = 200

PRICE_BOOM_PERIOD_H      = 24        # hrs look-back
PRICE_BOOM_PCT           = 0.1       # +10 % boom threshold
PRICE_SLOWDOWN_PERIOD_H  = 4         # hrs look-back
PRICE_SLOWDOWN_PCT       = 0.01      # ≤ +5 % slowdown

SL_ATR_MULT              = 3         # initial stop = entry + 2 × ATR
TP_ATR_MULT              = 3         # vanilla TP for one-leg back-tests
MIN_STOP_DIST_PCT        = 0.001     # guard against micro stops (0.1 %)

# ── RSI filter ───────────────────────────────────────────────────────
RSI_TIMEFRAME = "4h"
RSI_PERIOD    = 14
RSI_ENTRY_MIN = 40.0          # allow short only if 30 ≤ RSI ≤ 65
RSI_ENTRY_MAX = 65.0

# ─── Volatility Filter ──────────────────────────────────────────────
VOLATILITY_FILTER_ENABLED = False
MIN_ATR_PCT = 0.002

# ─── Structural Filter (long-term trend) ─────────────────────────────
STRUCTURAL_TREND_DAYS    = 30
STRUCTURAL_TREND_RET_PCT = -0.20

# ─── Macro Regime Filter ─────────────────────────────────────────────
# Avoids shorting when the broader market (BTC) is in a strong uptrend.
BTC_FAST_FILTER_ENABLED   = True   # Use the short-term trend filter
BTC_FAST_TIMEFRAME        = "4h"
BTC_FAST_EMA_PERIOD       = 20

BTC_SLOW_FILTER_ENABLED   = False  # Use the long-term trend filter
BTC_SLOW_TIMEFRAME        = "1D"
BTC_SLOW_EMA_PERIOD       = 50
# ─── Dynamic exit & risk management ──────────────────────────────────
PARTIAL_TP_ENABLED    = True
PARTIAL_TP_ATR_MULT   = 1.0
PARTIAL_CLOSE_PCT     = 0.70
TRAIL_ATR_MULT        = 1.5

# --- MODIFICATION START (Quick Fix) ---
# If PARTIAL_TP_ENABLED is False, this setting determines the exit logic.
# If True: Use a trailing stop from entry (the profit-taking mechanism).
# If False: Use a fixed take profit target (defined by TP_ATR_MULT).
TRAIL_SL_FROM_ENTRY_ENABLED = True
# --- MODIFICATION END (Quick Fix) ---

ENTRY_DELAY_MAX_MINUTES = 120

# --- Time-based Exits ---
TIME_EXIT_ENABLED           = False
TIME_EXIT_DAYS              = 10
TIME_EXIT_PARTIAL_CLOSE_PCT = 1.0
TIME_EXIT_TRAIL_ATR_MULT    = 1.0

# --- Trailing SL Recalculation ---
TRAIL_SL_RECALC_ENABLED = False
TRAIL_SL_RECALC_DAYS    = 3

# ─── Cool-down after consecutive losses ──────────────────────────────
COOLDOWN_LOSS_COUNT   = 5
COOLDOWN_DURATION_H   = 24

# ─── Sideways “cooling-off” gap before entry ─────────────────────────
GAP_VWAP_HOURS        = 2
GAP_MAX_DEV_PCT       = 0.01
GAP_MIN_BARS          = 3

# ─── Analytics Columns (for output CSV) ───────────────────────────────
ANALYTICS_EMA_TIMEFRAME = "4h"
ANALYTICS_EMA_PERIODS   = [8, 21, 33, 54, 89, 200]
ANALYTICS_BBANDS_TIMEFRAME = "1h"
ANALYTICS_BBANDS_PERIOD = 20
ANALYTICS_BBANDS_STD_DEV = 2.0

ADX_FILTER_ENABLED = False
ADX_TIMEFRAME      = "4h"
ADX_PERIOD         = 14
ADX_MIN_LEVEL      = 20.0 # Only take trades if ADX is above this level

# ─── House-keeping: create runtime dirs ──────────────────────────────
for _path in (PARQUET_DIR, SIGNALS_DIR, RESULTS_DIR):
    _path.mkdir(parents=True, exist_ok=True)

__all__ = [name for name in globals() if not name.startswith("_")]
