# live_bot.py (FINAL DIAGNOSTIC VERSION)

import time
import logging
import pandas as pd
import ccxt
import schedule
import telegram
import asyncio
import json
from pathlib import Path
import traceback # <--- IMPORT THE TRACEBACK MODULE

import config as cfg
import indicators as ta

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("live_bot.log"),
        logging.StreamHandler()
    ]
)

# --- Helper functions for Cooldown ---
COOLDOWN_FILE = Path("signal_cooldowns.json")

def load_cooldowns() -> dict:
    if not COOLDOWN_FILE.exists(): return {}
    try:
        with open(COOLDOWN_FILE, 'r') as f: return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError): return {}

def save_cooldowns(cooldowns: dict):
    with open(COOLDOWN_FILE, 'w') as f: json.dump(cooldowns, f, indent=4)

# --- CCXT Data Fetcher ---
def fetch_bybit_data(symbol: str, timeframe: str, bybit: ccxt.Exchange, limit: int = 300) -> pd.DataFrame | None:
    try:
        fetch_limit = None if timeframe.upper() == '1D' else limit
        ohlcv = bybit.fetch_ohlcv(symbol, timeframe, limit=fetch_limit)

        if not ohlcv:
            logging.warning(f"No data returned for {symbol} on {timeframe}.")
            return None

        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df.set_index('timestamp', inplace=True)
        return df
    except Exception: # <-- CATCH GENERIC EXCEPTION
        # --- THIS IS THE CRITICAL CHANGE ---
        logging.error(f"An unexpected error occurred fetching data for {symbol} on {timeframe}:")
        logging.error(traceback.format_exc()) # <-- PRINT THE FULL TRACEBACK
        return None

# --- Telegram Notifier ---
async def send_telegram_message(message: str):
    # This function is fine, no changes needed here.
    try:
        bot = telegram.Bot(token=cfg.TELEGRAM_BOT_TOKEN)
        await bot.send_message(
            chat_id=cfg.TELEGRAM_CHAT_ID,
            text=message,
            parse_mode='Markdown'
        )
        logging.info("Successfully sent Telegram notification.")
    except Exception:
        logging.error("Failed to send Telegram message:")
        logging.error(traceback.format_exc())


# --- Data Preparation ---
def _prep_live_data(symbol: str, bybit: ccxt.Exchange) -> pd.DataFrame | None:
    # This function is fine, no changes needed here.
    df5 = fetch_bybit_data(symbol, cfg.BOT_TIMEFRAME, bybit, limit=500)
    df_atr_tf = fetch_bybit_data(symbol, cfg.ATR_TIMEFRAME, bybit)
    df_rsi_tf = fetch_bybit_data(symbol, cfg.RSI_TIMEFRAME, bybit)

    if any(df is None for df in [df5, df_atr_tf, df_rsi_tf]):
        logging.warning(f"Could not fetch one or more essential timeframes for {symbol}. Skipping.")
        return None

    df5[f"atr_{cfg.ATR_TIMEFRAME}"] = ta.atr(df_atr_tf, cfg.ATR_PERIOD).reindex(df5.index, method="ffill")
    df5[f"rsi_{cfg.RSI_TIMEFRAME}"] = ta.rsi(df_rsi_tf["close"], cfg.RSI_PERIOD).reindex(df5.index, method="ffill")

    BARS_PER_HOUR = 60 // int(cfg.BOT_TIMEFRAME.replace('m', ''))
    BOOM_BAR_COUNT = BARS_PER_HOUR * cfg.PRICE_BOOM_PERIOD_H
    SLOWDOWN_BAR_COUNT = BARS_PER_HOUR * cfg.PRICE_SLOWDOWN_PERIOD_H
    df5["close_boom_ago"] = df5["close"].shift(BOOM_BAR_COUNT)
    df5["close_slowdown_ago"] = df5["close"].shift(SLOWDOWN_BAR_COUNT)
    
    return df5.dropna(subset=['close_boom_ago', f"rsi_{cfg.RSI_TIMEFRAME}", f"atr_{cfg.ATR_TIMEFRAME}"])


# --- Main Signal Checking Logic ---
def check_for_signals():
    logging.info("--- Starting new signal check cycle ---")
    
    cooldowns = load_cooldowns()
    
    try:
        bybit = ccxt.bybit({'options': {'defaultType': 'swap'}})
        bybit.load_markets()
    except Exception:
        logging.error("Failed to initialize exchange or load markets:")
        logging.error(traceback.format_exc())
        return

    btc_is_strong = False
    if cfg.BTC_SLOW_FILTER_ENABLED:
        btc_df = fetch_bybit_data("BTCUSDT", cfg.BTC_SLOW_TIMEFRAME, bybit)
        if btc_df is not None and not btc_df.empty:
            btc_df['ema'] = ta.ema(btc_df['close'], cfg.BTC_SLOW_EMA_PERIOD)
            btc_last = btc_df.iloc[-1]
            if pd.notna(btc_last.get('close')) and pd.notna(btc_last.get('ema')):
                btc_is_strong = btc_last['close'] > btc_last['ema']
    
    # ... The rest of the function remains the same ...
    # (No changes needed in the symbol loop)
    try:
        with open(cfg.SYMBOLS_FILE, 'r') as fh:
            symbols = [line.split()[0].strip().upper() for line in fh if line.strip() and not line.strip().startswith("#")]
    except FileNotFoundError:
        logging.error(f"'{cfg.SYMBOLS_FILE}' not found. Exiting.")
        return

    for symbol in symbols:
        if symbol in cooldowns and pd.Timestamp.now(tz='UTC') < pd.to_datetime(cooldowns[symbol]):
            continue

        logging.info(f"--- Checking {symbol} ---")
        
        df_prep = _prep_live_data(symbol, bybit)
        if df_prep is None or df_prep.empty:
            logging.warning(f"Could not prepare data for {symbol}, skipping.")
            continue
        
        last_candle = df_prep.iloc[-2]
        
        boom_ret = (last_candle["close"] / last_candle["close_boom_ago"]) - 1
        boom_cond = boom_ret >= cfg.PRICE_BOOM_PCT
        slow_cond = (last_candle["close"] / last_candle["close_slowdown_ago"] - 1) <= cfg.PRICE_SLOWDOWN_PCT
        
        if not (boom_cond and slow_cond):
            continue
        
        logging.info(f"!!! POTENTIAL SIGNAL FOUND for {symbol} !!! Building report...")

        champion_boom_ok = boom_ret >= cfg.CHAMPION_MIN_BOOM_PCT
        
        rsi_val = last_candle.get(f"rsi_{cfg.RSI_TIMEFRAME}", float('nan'))
        champion_rsi_ok = pd.notna(rsi_val) and rsi_val >= cfg.CHAMPION_MIN_RSI
        
        champion_btc_ok = btc_is_strong

        all_champion_filters_met = champion_boom_ok and champion_rsi_ok and champion_btc_ok
        
        title = "✅ *CHAMPION SIGNAL* ✅" if all_champion_filters_met else "⚠️ *POTENTIAL SIGNAL* ⚠️"
        
        filter_lines = [
            f"{'✅' if champion_boom_ok else '❌'} *Boom > {cfg.CHAMPION_MIN_BOOM_PCT:.0%}?* (`{boom_ret:.2%}`)",
            f"{'✅' if champion_rsi_ok else '❌'} *RSI > {cfg.CHAMPION_MIN_RSI}?* (`{rsi_val:.2f}`)",
            f"{'✅' if champion_btc_ok else '❌'} *BTC Strong?* (`{btc_is_strong}`)"
        ]
        filter_checklist = "\n".join(filter_lines)

        entry_price = last_candle['close']
        atr_value = last_candle.get(f"atr_{cfg.ATR_TIMEFRAME}", float('nan'))
        
        if pd.isna(atr_value):
            logging.warning(f"ATR value is NaN for {symbol}. Cannot calculate trade parameters.")
            continue

        stop_loss = entry_price + cfg.SL_ATR_MULT * atr_value
        partial_tp = entry_price - cfg.PARTIAL_TP_ATR_MULT * atr_value
        tp2_price = entry_price - cfg.TP2_ATR_MULT * atr_value
        trail_dist = cfg.TRAIL_ATR_MULT_FINAL * atr_value

        message = (
            f"{title}\n\n"
            f"**Symbol:** `{symbol}`\n"
            f"**Time:** `{last_candle.name.strftime('%Y-%m-%d %H:%M')}` UTC\n\n"
            f"--- *Champion Filter Checklist* ---\n"
            f"{filter_checklist}\n\n"
            f"--- *Actionable Trade Parameters* ---\n"
            f"**Entry Price:** `{entry_price:.4f}`\n"
            f"**1. Stop-Loss (SL):** `{stop_loss:.4f}` ({cfg.SL_ATR_MULT} ATR)\n"
            f"**2. Partial Take-Profit (TP1):** `{partial_tp:.4f}` ({cfg.PARTIAL_TP_ATR_MULT} ATR)\n"
            f"**3. Trailing Stop Distance:** `{trail_dist:.5f}` (Set after TP1 is hit)\n\n"
            f"--- *Informational Target* ---\n"
            f"**Potential Target (TP2):** `{tp2_price:.4f}` ({cfg.TP2_ATR_MULT} ATR)\n"
        )
        
        asyncio.run(send_telegram_message(message))
        
        cooldown_end = pd.Timestamp.now(tz='UTC') + pd.Timedelta(minutes=cfg.SIGNAL_COOLDOWN_MINUTES)
        cooldowns[symbol] = cooldown_end.isoformat()
        save_cooldowns(cooldowns)
        logging.info(f"Sent alert for {symbol}. Cooldown until {cooldown_end.strftime('%Y-%m-%d %H:%M:%S UTC')}")

        time.sleep(1)

# --- Main Execution ---
if __name__ == "__main__":
    logging.info("Starting Crypto Signal Bot (Diagnostic Mode)...")
    check_for_signals()
    schedule.every(cfg.BOT_SCHEDULE_MINUTES).minutes.do(check_for_signals)
    logging.info(f"Scheduled to run every {cfg.BOT_SCHEDULE_MINUTES} minutes.")
    while True:
        schedule.run_pending()
        time.sleep(1)
