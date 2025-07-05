# live_bot.py (Corrected and Verified Version)

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

# --- Define path for the persistent cooldown file ---
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

# --- Helper functions to manage the cooldown file ---
def load_cooldowns() -> dict:
    if not COOLDOWN_FILE.exists():
        return {}
    try:
        with open(COOLDOWN_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}

def save_cooldowns(cooldowns: dict):
    with open(COOLDOWN_FILE, 'w') as f:
        json.dump(cooldowns, f, indent=4)

# --- Bybit Data Fetcher ---
# In live_bot.py

def fetch_bybit_data(symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame | None:
    """
    Fetches OHLCV data for Bybit perpetuals. This version is more flexible
    to handle different API behaviors for daily vs. intraday timeframes.
    """
    try:
        bybit = ccxt.bybit()
        bybit.load_markets()
        market = bybit.market(symbol)
        
        # --- NEW FLEXIBLE LOGIC ---
        # Start with base parameters
        params = {'type': 'swap'}
        
        # Only add the 'subType' for non-daily timeframes, as it can sometimes
        # cause issues with fetching historical daily data for some pairs.
        if timeframe.upper() != '1D':
            params['subType'] = 'linear'

        # Use the provided limit for intraday, but let ccxt use its default for daily.
        fetch_limit = limit if timeframe.upper() != '1D' else None
        
        # Fetch OHLCV data
        ohlcv = bybit.fetch_ohlcv(symbol, timeframe, limit=fetch_limit, params=params)
        
        if not ohlcv:
            logging.warning(f"No data returned for {symbol} on {timeframe} timeframe")
            return None

        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df.set_index('timestamp', inplace=True)
        df['turnover'] = df['close'] * df['volume']
        return df
    except ccxt.BadSymbol as e:
        logging.error(f"Symbol not found on Bybit: {symbol}. Error: {e}")
        return None
    except Exception as e:
        logging.error(f"Error fetching data for {symbol} on {timeframe}: {e}")
        return None




# --- Telegram Notifier ---
async def send_telegram_message(message: str):
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

# --- Data Preparation ---
def _prep_live_data(symbol: str) -> pd.DataFrame | None:
    """
    Prepares the live data DataFrame with all necessary indicators.
    This version is robust and handles missing daily data gracefully.
    """
    # --- 1. Fetch ESSENTIAL intraday data ---
    # These are required for the core logic to run.
    df5 = fetch_bybit_data(symbol, cfg.BOT_TIMEFRAME, limit=1000)
    df4h = fetch_bybit_data(symbol, "4h", limit=300)
    df_atr_tf = fetch_bybit_data(symbol, cfg.ATR_TIMEFRAME, limit=200)
    df_rsi_tf = fetch_bybit_data(symbol, cfg.RSI_TIMEFRAME, limit=200)
    df_adx_tf = fetch_bybit_data(symbol, cfg.ADX_TIMEFRAME, limit=200)

    # --- 2. Check if ESSENTIAL data was fetched successfully ---
    if any(df is None for df in [df5, df4h, df_atr_tf, df_rsi_tf, df_adx_tf]):
        logging.warning(f"Could not fetch one or more essential intraday timeframes for {symbol}")
        return None

    # --- 3. Try to fetch OPTIONAL daily data for context ---
    # The bot will not fail if this request returns no data.
    df_daily = fetch_bybit_data(symbol, "1D")

    # --- 4. Calculate indicators on their respective timeframes ---
    df4h["ema_fast"] = ta.ema(df4h["close"], cfg.EMA_FAST)
    df4h["ema_slow"] = ta.ema(df4h["close"], cfg.EMA_SLOW)
    atr_col = f"atr_{cfg.ATR_TIMEFRAME}"
    df_atr_tf[atr_col] = ta.atr(df_atr_tf, cfg.ATR_PERIOD)
    rsi_col = f"rsi_{cfg.RSI_TIMEFRAME}"
    df_rsi_tf[rsi_col] = ta.rsi(df_rsi_tf["close"], cfg.RSI_PERIOD)
    adx_col = f"adx_{cfg.ADX_TIMEFRAME}"
    df_adx_tf[adx_col] = ta.adx(df_adx_tf, period=cfg.ADX_PERIOD)
    
    # --- 5. Merge essential indicators back onto the 5m DataFrame ---
    df5[["ema_fast_4h", "ema_slow_4h"]] = df4h[["ema_fast", "ema_slow"]].reindex(df5.index, method="ffill")
    df5[atr_col] = df_atr_tf[atr_col].reindex(df5.index, method="ffill")
    df5[rsi_col] = df_rsi_tf[rsi_col].reindex(df5.index, method="ffill")
    df5[adx_col] = df_adx_tf[adx_col].reindex(df5.index, method="ffill")

    # --- 6. Robustly handle the optional structural trend data ---
    if df_daily is not None and not df_daily.empty:
        # If we got daily data, calculate and merge the 30-day return.
        df_daily['ret_30d'] = (df_daily['close'] / df_daily['close'].shift(cfg.STRUCTURAL_TREND_DAYS)) - 1
        df5['ret_30d'] = df_daily['ret_30d'].reindex(df5.index, method="ffill")
    else:
        # If no daily data, create a placeholder column of NaNs.
        # This prevents the rest of the code from crashing.
        df5['ret_30d'] = float('nan')

    # --- 7. Calculate final look-back columns ---
    BARS_PER_HOUR = 60 // int(cfg.BOT_TIMEFRAME.replace('m', ''))
    BOOM_BAR_COUNT = BARS_PER_HOUR * cfg.PRICE_BOOM_PERIOD_H
    SLOWDOWN_BAR_COUNT = BARS_PER_HOUR * cfg.PRICE_SLOWDOWN_PERIOD_H
    df5["close_boom_ago"] = df5["close"].shift(BOOM_BAR_COUNT)
    df5["close_slowdown_ago"] = df5["close"].shift(SLOWDOWN_BAR_COUNT)
    
    # Only require the core calculation columns to be non-NaN to proceed.
    return df5.dropna(subset=['close_boom_ago', 'close_slowdown_ago'])

# In live_bot.py

def check_for_signals():
    """The main job function that checks all symbols for trade signals."""
    logging.info("--- Starting new signal check cycle ---")
    
    cooldowns = load_cooldowns()

    # --- NEW: Fetch BTC data once per cycle ---
    btc_df = None
    if cfg.SHOW_BTC_FAST_FILTER_CONTEXT and cfg.BTC_FAST_FILTER_ENABLED:
        btc_df = fetch_bybit_data("BTCUSDT", cfg.BTC_FAST_TIMEFRAME, limit=100)
        if btc_df is not None:
            btc_df['ema'] = ta.ema(btc_df['close'], cfg.BTC_FAST_EMA_PERIOD)

    try:
        with open(cfg.SYMBOLS_FILE, 'r') as fh:
            symbols = [s.strip().upper() for s in fh if s.strip() and not s.startswith("#")]
    except FileNotFoundError:
        logging.error(f"'{cfg.SYMBOLS_FILE}' not found. Exiting.")
        return

    for symbol in symbols:
        if symbol in cooldowns:
            cooldown_end_time = pd.to_datetime(cooldowns[symbol])
            if pd.Timestamp.now(tz='UTC') < cooldown_end_time:
                continue

        logging.info(f"Checking {symbol}...")
        
        df_prep = _prep_live_data(symbol)
        if df_prep is None or df_prep.empty:
            logging.warning(f"Could not prepare data for {symbol}, skipping.")
            continue
            
        last_candle = df_prep.iloc[-2]
        
        if symbol in cooldowns and pd.to_datetime(cooldowns[symbol]) > last_candle.name:
             continue

        # --- CORE TRIGGER LOGIC ---
        boom = (last_candle["close"] - last_candle["close_boom_ago"]) / last_candle["close_boom_ago"] >= cfg.PRICE_BOOM_PCT
        slow = (last_candle["close"] - last_candle["close_slowdown_ago"]) / last_candle["close_slowdown_ago"] <= cfg.PRICE_SLOWDOWN_PCT
        
        is_core_signal = boom and slow

        if is_core_signal:
            logging.info(f"!!! CORE SIGNAL FOUND for {symbol} !!!")
            
            # --- Gather all data for the message ---
            atr_col = f"atr_{cfg.ATR_TIMEFRAME}"
            rsi_col = f"rsi_{cfg.RSI_TIMEFRAME}"
            adx_col = f"adx_{cfg.ADX_TIMEFRAME}"

            entry_price = last_candle['close']
            atr_value = last_candle.get(atr_col, float('nan'))
            stop_loss = entry_price + cfg.SL_ATR_MULT * atr_value
            partial_tp_price = entry_price - cfg.PARTIAL_TP_ATR_MULT * atr_value
            trail_distance = cfg.TRAIL_ATR_MULT * atr_value

            # --- Build the dynamic context message ---
            context_lines = []

            if cfg.SHOW_EMA_TREND_CONTEXT:
                ema_fast = last_candle.get('ema_fast_4h', float('nan'))
                ema_slow = last_candle.get('ema_slow_4h', float('nan'))
                if pd.notna(ema_fast) and pd.notna(ema_slow):
                    ema_trend_ok = ema_fast < ema_slow
                    icon = "✅" if ema_trend_ok else "❌"
                    context_lines.append(f"{icon} *EMA Trend (4h):* Fast < Slow? `{ema_trend_ok}`")
                else:
                    context_lines.append("⚠️ *EMA Trend (4h):* `Data N/A`")

            if cfg.SHOW_RSI_CONTEXT:
                rsi_val = last_candle.get(rsi_col, float('nan'))
                if pd.notna(rsi_val):
                    rsi_ok = cfg.RSI_ENTRY_MIN <= rsi_val <= cfg.RSI_ENTRY_MAX
                    icon = "✅" if rsi_ok else "❌"
                    context_lines.append(f"{icon} *RSI ({cfg.RSI_TIMEFRAME}):* `{rsi_val:.2f}` (Ideal? `{rsi_ok}`)")

            if cfg.SHOW_ADX_CONTEXT:
                adx_val = last_candle.get(adx_col, float('nan'))
                if pd.notna(adx_val):
                    context_lines.append(f"📈 *ADX ({cfg.ADX_TIMEFRAME}):* `{adx_val:.2f}`")

            if cfg.SHOW_STRUCTURAL_CONTEXT:
                ret_30d = last_candle.get('ret_30d', float('nan'))
                if pd.notna(ret_30d):
                    context_lines.append(f"📉 *30d Return:* `{ret_30d:.1%}`")

            if cfg.SHOW_BTC_FAST_FILTER_CONTEXT and btc_df is not None:
                btc_last = btc_df.reindex([last_candle.name], method='ffill').iloc[0]
                btc_price = btc_last.get('close', float('nan'))
                btc_ema = btc_last.get('ema', float('nan'))
                if pd.notna(btc_price) and pd.notna(btc_ema):
                    btc_market_is_hot = btc_price > btc_ema
                    icon = "❌" if btc_market_is_hot else "✅"
                    context_lines.append(f"{icon} *BTC Filter:* Market Hot? `{btc_market_is_hot}`")

            context_message = "\n".join(context_lines)

            # --- Final Message Assembly ---
            message = (
                f"🎯 *New Short Opportunity: ${symbol}*\n\n"
                f"--- *Core Setup (Boom & Slowdown)* ---\n"
                f"**Entry Price:** `{entry_price:.4f}`\n"
                f"**Stop Loss:** `{stop_loss:.4f}`\n"
                f"**Partial TP (TP1):** `{partial_tp_price:.4f}`\n"
                f"**Trail Distance:** `{trail_distance:.5f}`\n\n"
                f"--- *Contextual Analysis* ---\n"
                f"{context_message}\n\n"
                f"_*Discretionary decision required._"
            )
            
            asyncio.run(send_telegram_message(message))
            
            cooldown_end = pd.Timestamp.now(tz='UTC') + pd.Timedelta(minutes=cfg.SIGNAL_COOLDOWN_MINUTES)
            cooldowns[symbol] = cooldown_end.isoformat()
            save_cooldowns(cooldowns)
            logging.info(f"Sent opportunity alert for {symbol}. Cooldown until {cooldown_end.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        
        time.sleep(2)

# --- Main Execution ---
if __name__ == "__main__":
    logging.info("Starting Crypto Signal Bot...")
    check_for_signals()
    schedule.every(cfg.BOT_SCHEDULE_MINUTES).minutes.do(check_for_signals)
    logging.info(f"Scheduled to run every {cfg.BOT_SCHEDULE_MINUTES} minutes.")
    while True:
        schedule.run_pending()
        time.sleep(1)
