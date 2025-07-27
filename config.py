"""
Global strategy settings.
Edit only the plain  NAME = value  lines – no complex syntax.
"""

from pathlib import Path

SIGNAL_COOLDOWN_MINUTES = 240 # Cooldown per symbol after a signal is sent

# ─── Live Bot & Notification Settings ────────────────────────────────
TELEGRAM_BOT_TOKEN    = "7770157032:AAGO-J_Mb8Oxg3i6xQmWTj3rM3JMO5MMscQ"  # Replace with your Bot Token
TELEGRAM_CHAT_ID      = "2133130545"    # Replace with your Chat ID
BOT_TIMEFRAME         = "5m"                       # Timeframe for the bot to check for signals
BOT_SCHEDULE_MINUTES  = 1                          # How often to check for new signals

# In config.py
DEBUG_SYMBOL = "HUSDT"  # Set to a symbol to get detailed logs, or None to disable
# ─── Data locations ──────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
SYMBOLS_FILE = PROJECT_ROOT / "symbols.txt"

# =============================================================================
# "NEW CHAMPION" STRATEGY PARAMETERS
# The bot will check against these values and report if they are met.
# =============================================================================

# ─── Core Signal Generation (The Trigger for an Alert) ───────────────
PRICE_BOOM_PERIOD_H      = 24
# This is now the MINIMUM threshold to trigger a basic alert.
# We will check our champion value (0.20) as a separate condition.
PRICE_BOOM_PCT           = 0.13

PRICE_SLOWDOWN_PERIOD_H  = 4
PRICE_SLOWDOWN_PCT       = 0.01

# ─── Champion Strategy Filter Values (For Checking) ──────────────────
CHAMPION_MIN_BOOM_PCT    = 0.15      # The ideal boom threshold from our analysis
CHAMPION_MIN_RSI         = 30      # Replace with your exact SPSS cutpoint value

# ─── Primary Environmental Filter: BTC Slow Trend ──────────────
BTC_SLOW_FILTER_ENABLED   = True
BTC_SLOW_TIMEFRAME        = "1D"
BTC_SLOW_EMA_PERIOD       = 200

# ─── Trade Management / Exit Parameters (For Display) ──────────
SL_ATR_MULT              = 2.5
PARTIAL_TP_ATR_MULT      = 1.0
TRAIL_ATR_MULT_FINAL     = 1

# ─── Trade Management / Exit Parameters (For Display) ──────────
PARTIAL_TP_ATR_MULT      = 1.0       # Partial Take-Profit = 1 * ATR
TP2_ATR_MULT             = 6.0       # <--- ADD THIS LINE. Informational target for the runner.
TRAIL_ATR_MULT_FINAL     = 1         # Trailing Stop Distance = 1.5 * ATR

# ─── Indicator Calculation Parameters ──────────────────────────
RSI_TIMEFRAME = "1h"
RSI_PERIOD    = 14
ATR_TIMEFRAME = "1h"
ATR_PERIOD    = 14
