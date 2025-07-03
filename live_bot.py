# live_bot.py

import time
import logging
import pandas as pd
import ccxt
import schedule
import telegram
import asyncio
import json
from pathlib import Path

# Import your existing modules
import config as cfg
import indicators as ta

# --- NEW: Define path for the persistent cooldown file ---
COOLDOWN_FILE = Path("signal_cooldowns.json")

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("live_bot.log"),
        logging.StreamHandler()
    ]
)

# --- REMOVED: The old in-memory `last_signal_time` dictionary is no longer needed ---

# --- NEW: Helper functions to manage the cooldown file ---
def load_cooldowns() -> dict:
    """Loads the cooldown timestamps from the JSON file."""
    if not COOLDOWN_FILE.exists():
        return {}
    try:
        with open(COOLDOWN_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}

def save_cooldowns(cooldowns: dict):
    """Saves the cooldown timestamps to the JSON file."""
    with open(COOLDOWN_FILE, 'w') as f:
        json.dump(cooldowns, f, indent=4)

# --- Bybit Data Fetcher (No changes here) ---
def fetch_bybit_data(symbol: str, timeframe: str, limit: int = 500) -> pd.DataFrame | None:
    # ... (This function remains the same as the last correct version)
    try:
        bybit = ccxt.bybit()
        bybit.load_markets()
        market = bybit.market(symbol)
        params = {'type': 'swap', 'subType': 'linear'}
        ohlcv = bybit.fetch_ohlcv(symbol, timeframe, limit=limit, params=params)
        if not ohlcv:
            logging.warning(f"No data returned for {symbol} on {timeframe} timeframe")
            return None
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        df['turnover'] = df['close'] * df['volume']
        return df
    except ccxt.BadSymbol as e:
        logging.error(f"Symbol not found on Bybit: {symbol}. Error: {e}")
        return None
    except Exception as e:
        logging.error(f"Error fetching data for {symbol} on {timeframe}: {e}")
        return None

# --- Telegram Notifier (No changes here) ---
async def send_telegram_message(message: str):
    # ... (This function remains the same)
    try:
        bot = telegram.Bot(token=cfg.TELEGRAM_BOT_TOKEN)
        await bot.send_message(
            chat_id=cfg.TELEGRAM_CHAT_ID,
            text=message,
            parse_mode='Markdown'
        )
        logging.info(f"Successfully sent Telegram notification.")
    except Exception as e:
        logging.error(f"Failed to send Telegram message: {e}")

# --- Data Preparation (No changes here) ---
def _prep_live_data(symbol: str) -> pd.DataFrame | None:
    # ... (This function remains the same as the last correct version)
    df5 = fetch_bybit_data(symbol, cfg.BOT_TIMEFRAME, limit=500)
    if df5 is None: return None
    df4h = fetch_bybit_data(symbol, "4h", limit=300)
    df_atr_tf = fetch_bybit_data(symbol, cfg.ATR_TIMEFRAME, limit=100)
    df_rsi_tf = fetch_bybit_data(symbol, cfg.RSI_TIMEFRAME, limit=100)
    df_adx_tf = fetch_bybit_data(symbol, cfg.ADX_TIMEFRAME, limit=100)
    if any(df is None for df in [df4h, df_atr_tf, df_rsi_tf, df_adx_tf]):
        logging.warning(f"Could not fetch all required timeframes for {symbol}")
        return None
    df4h["ema_fast"] = ta.ema(df4h["close"], cfg.EMA_FAST)
    df4h["ema_slow"] = ta.ema(df4h["close"], cfg.EMA_SLOW)
    atr_col = f"atr_{cfg.ATR_TIMEFRAME}"
    df_atr_tf[atr_col] = ta.atr(df_atr_tf, cfg.ATR_PERIOD)
    rsi_col = f"rsi_{cfg.RSI_TIMEFRAME}"
    df_rsi_tf[rsi_col] = ta.rsi(df_rsi_tf["close"], cfg.RSI_PERIOD)
    adx_col = f"adx_{cfg.ADX_TIMEFRAME}"
    df_adx_tf[adx_col] = ta.adx(df_adx_tf, period=cfg.ADX_PERIOD)
    df5[["ema_fast_4h", "ema_slow_4h"]] = df4h[["ema_fast", "ema_slow"]].reindex(df5.index, method="ffill")
    df5[atr_col] = df_atr_tf[atr_col].reindex(df5.index, method="ffill")
    df5[rsi_col] = df_rsi_tf[rsi_col].reindex(df5.index, method="ffill")
    df5[adx_col] = df_adx_tf[adx_col].reindex(df5.index, method="ffill")
    BARS_PER_HOUR = 60 // int(cfg.BOT_TIMEFRAME.replace('m', ''))
    BOOM_BAR_COUNT = BARS_PER_HOUR * cfg.PRICE_BOOM_PERIOD_H
    SLOWDOWN_BAR_COUNT = BARS_PER_HOUR * cfg.PRICE_SLOWDOWN_PERIOD_H
    df5["close_boom_ago"] = df5["close"].shift(BOOM_BAR_COUNT)
    df5["close_slowdown_ago"] = df5["close"].shift(SLOWDOWN_BAR_COUNT)
    return df5.dropna()

def check_for_signals():
    """The main job function that checks all symbols for trade signals."""
    logging.info("--- Starting new signal check cycle ---")
    
    # --- NEW: Load cooldowns at the start of each cycle ---
    cooldowns = load_cooldowns()

    try:
        with open(cfg.SYMBOLS_FILE, 'r') as fh:
            symbols = [s.strip().upper() for s in fh if s.strip() and not s.startswith("#")]
    except FileNotFoundError:
        logging.error(f"'{cfg.SYMBOLS_FILE}' not found. Exiting.")
        return

    for symbol in symbols:
        # --- NEW: Check if the symbol is currently in a cooldown period ---
        if symbol in cooldowns:
            cooldown_end_time = pd.to_datetime(cooldowns[symbol])
            if pd.Timestamp.now(tz='UTC') < cooldown_end_time:
                # Log only once to avoid spamming the log file
                # logging.info(f"Symbol {symbol} is in cooldown. Skipping.")
                continue # Skip to the next symbol

        logging.info(f"Checking {symbol}...")
        
        df_prep = _prep_live_data(symbol)
        if df_prep is None or df_prep.empty:
            logging.warning(f"Could not prepare data for {symbol}, skipping.")
            continue
            
        last_candle = df_prep.iloc[-2]
        
        # --- NEW: This check prevents re-alerting on the same candle if the script runs fast ---
        # It's a secondary check to the main cooldown logic.
        if symbol in cooldowns and pd.to_datetime(cooldowns[symbol]) > last_candle.name:
             continue

        atr_col = f"atr_{cfg.ATR_TIMEFRAME}"
        rsi_col = f"rsi_{cfg.RSI_TIMEFRAME}"
        adx_col = f"adx_{cfg.ADX_TIMEFRAME}"

        boom = (last_candle["close"] - last_candle["close_boom_ago"]) / last_candle["close_boom_ago"] >= cfg.PRICE_BOOM_PCT
        slow = (last_candle["close"] - last_candle["close_slowdown_ago"]) / last_candle["close_slowdown_ago"] <= cfg.PRICE_SLOWDOWN_PCT
        ema_down = last_candle["ema_fast_4h"] < last_candle["ema_slow_4h"]
        rsi_ok = cfg.RSI_ENTRY_MIN <= last_candle[rsi_col] <= cfg.RSI_ENTRY_MAX
        adx_ok = not cfg.ADX_FILTER_ENABLED or last_candle[adx_col] > cfg.ADX_MIN_LEVEL
        
        is_signal = all([boom, slow, ema_down, rsi_ok, adx_ok])

        if is_signal:
            logging.info(f"!!! SIGNAL DETECTED for {symbol} !!!")
            
            # Format and Send Notification (using the improved message from before)
            entry_price = last_candle['close']
            atr_value = last_candle[atr_col]
            stop_loss = entry_price + cfg.SL_ATR_MULT * atr_value
            partial_tp_price = entry_price - cfg.PARTIAL_TP_ATR_MULT * atr_value
            final_tp_price = entry_price - cfg.TP_ATR_MULT * atr_value
            message = (
                f"🚨 *New Short Signal: ${symbol}*\n\n"
                f"**Entry Price:** `{entry_price:.4f}`\n"
                f"**Stop Loss:**   `{stop_loss:.4f}` (Entry + {cfg.SL_ATR_MULT}x ATR)\n\n"
                f"**Partial TP (TP1):** `{partial_tp_price:.4f}` (Entry - {cfg.PARTIAL_TP_ATR_MULT}x ATR)\n"
                f"**Final TP (Optional):** `{final_tp_price:.4f}` (Entry - {cfg.TP_ATR_MULT}x ATR)\n\n"
                f"*Signal Details:*\n"
                f"- Time: `{last_candle.name.strftime('%Y-%m-%d %H:%M')}`\n"
                f"- RSI ({cfg.RSI_TIMEFRAME}): `{last_candle[rsi_col]:.2f}`\n"
                f"- ADX ({cfg.ADX_TIMEFRAME}): `{last_candle[adx_col]:.2f}`\n"
                f"- ATR ({cfg.ATR_TIMEFRAME}): `{atr_value:.5f}`"
            )
            asyncio.run(send_telegram_message(message))
            
            # --- NEW: Update the cooldowns dictionary and save it to the file ---
            cooldown_end = pd.Timestamp.now(tz='UTC') + pd.Timedelta(minutes=cfg.SIGNAL_COOLDOWN_MINUTES)
            cooldowns[symbol] = cooldown_end.isoformat()
            save_cooldowns(cooldowns)
            logging.info(f"Placed {symbol} in cooldown until {cooldown_end.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        
        time.sleep(2)

# --- Main Execution (No changes here) ---
if __name__ == "__main__":
    logging.info("Starting Crypto Signal Bot...")
    check_for_signals()
    schedule.every(cfg.BOT_SCHEDULE_MINUTES).minutes.do(check_for_signals)
    logging.info(f"Scheduled to run every {cfg.BOT_SCHEDULE_MINUTES} minutes.")
    while True:
        schedule.run_pending()
        time.sleep(1)
