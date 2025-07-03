# live_bot.py

import time
import logging
import pandas as pd
import ccxt
import schedule
import telegram
import asyncio

# Import your existing modules
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

# --- Globals ---
# This dictionary will store the timestamp of the last signal for each symbol
# to prevent sending duplicate alerts for the same event.
last_signal_time = {}

# --- Bybit Data Fetcher ---

# In live_bot.py

def fetch_bybit_data(symbol: str, timeframe: str, limit: int = 500) -> pd.DataFrame | None:
    """
    Fetches OHLCV data for Bybit linear perpetuals and returns a pandas DataFrame.
    """
    try:
        bybit = ccxt.bybit()
        # Load markets to find the correct market ID and type
        bybit.load_markets()
        
        # Find the specific market for the linear perpetual swap
        market = bybit.market(symbol)

        # Explicitly set the market type to 'swap' and specify linear contracts
        params = {'type': 'swap', 'subType': 'linear'}
        
        # Bybit uses milliseconds for timestamps
        ohlcv = bybit.fetch_ohlcv(symbol, timeframe, limit=limit, params=params)
        
        if not ohlcv:
            logging.warning(f"No data returned for {symbol} on {timeframe} timeframe")
            return None

        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        
        # Add a turnover column if it's needed by your indicators (e.g., VWAP)
        df['turnover'] = df['close'] * df['volume']

        return df
    except ccxt.BadSymbol as e:
        logging.error(f"Symbol not found on Bybit: {symbol}. Please check symbols.txt. Error: {e}")
        return None
    except Exception as e:
        logging.error(f"Error fetching data for {symbol} on {timeframe}: {e}")
        return None

# --- Telegram Notifier ---
async def send_telegram_message(message: str):
    """Sends a message to the configured Telegram chat."""
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

# --- Strategy Logic (Adapted from your scout.py) ---
# In live_bot.py

def _prep_live_data(symbol: str) -> pd.DataFrame | None:
    """
    Prepares the live data DataFrame with all necessary indicators by fetching
    each required timeframe directly.
    """
    # 1. Fetch base 5m data (enough for boom/slowdown calcs)
    df5 = fetch_bybit_data(symbol, cfg.BOT_TIMEFRAME, limit=500)
    if df5 is None: return None

    # 2. Fetch higher timeframe data for indicators
    df4h = fetch_bybit_data(symbol, "4h", limit=300) # Needs enough for 200 EMA
    df_atr_tf = fetch_bybit_data(symbol, cfg.ATR_TIMEFRAME, limit=100)
    df_rsi_tf = fetch_bybit_data(symbol, cfg.RSI_TIMEFRAME, limit=100)
    df_adx_tf = fetch_bybit_data(symbol, cfg.ADX_TIMEFRAME, limit=100)

    # Check if all data was fetched successfully
    if any(df is None for df in [df4h, df_atr_tf, df_rsi_tf, df_adx_tf]):
        logging.warning(f"Could not fetch all required timeframes for {symbol}")
        return None

    # 3. Calculate indicators on their native timeframes
    df4h["ema_fast"] = ta.ema(df4h["close"], cfg.EMA_FAST)
    df4h["ema_slow"] = ta.ema(df4h["close"], cfg.EMA_SLOW)
    
    atr_col = f"atr_{cfg.ATR_TIMEFRAME}"
    df_atr_tf[atr_col] = ta.atr(df_atr_tf, cfg.ATR_PERIOD)

    rsi_col = f"rsi_{cfg.RSI_TIMEFRAME}"
    df_rsi_tf[rsi_col] = ta.rsi(df_rsi_tf["close"], cfg.RSI_PERIOD)

    adx_col = f"adx_{cfg.ADX_TIMEFRAME}"
    df_adx_tf[adx_col] = ta.adx(df_adx_tf, period=cfg.ADX_PERIOD)

    # 4. Merge all indicators back onto the 5m DataFrame
    df5[["ema_fast_4h", "ema_slow_4h"]] = df4h[["ema_fast", "ema_slow"]].reindex(df5.index, method="ffill")
    df5[atr_col] = df_atr_tf[atr_col].reindex(df5.index, method="ffill")
    df5[rsi_col] = df_rsi_tf[rsi_col].reindex(df5.index, method="ffill")
    df5[adx_col] = df_adx_tf[adx_col].reindex(df5.index, method="ffill")

    # 5. Calculate look-back columns on the 5m DataFrame
    BARS_PER_HOUR = 60 // int(cfg.BOT_TIMEFRAME.replace('m', ''))
    BOOM_BAR_COUNT = BARS_PER_HOUR * cfg.PRICE_BOOM_PERIOD_H
    SLOWDOWN_BAR_COUNT = BARS_PER_HOUR * cfg.PRICE_SLOWDOWN_PERIOD_H
    
    df5["close_boom_ago"] = df5["close"].shift(BOOM_BAR_COUNT)
    df5["close_slowdown_ago"] = df5["close"].shift(SLOWDOWN_BAR_COUNT)
    
    # Drop rows with NaN values from indicator calculations
    return df5.dropna()


def check_for_signals():
    """The main job function that checks all symbols for trade signals."""
    logging.info("--- Starting new signal check cycle ---")
    
    try:
        with cfg.SYMBOLS_FILE.open() as fh:
            symbols = [s.strip().upper() for s in fh if s.strip() and not s.startswith("#")]
    except FileNotFoundError:
        logging.error(f"'{cfg.SYMBOLS_FILE}' not found. Exiting.")
        return

    for symbol in symbols:
        logging.info(f"Checking {symbol}...")
        
        # NEW CODE
        # 1. Prepare Data & Indicators
        df_prep = _prep_live_data(symbol) # This function now fetches its own data
        if df_prep is None or df_prep.empty:
            logging.warning(f"Could not prepare data for {symbol}, skipping.")
            continue
            
        # 3. Check the LAST completed candle for a signal
        # We use `iloc[-2]` because `iloc[-1]` is the current, incomplete candle.
        last_candle = df_prep.iloc[-2]
        
        # Avoid re-sending alerts for the same candle
        if symbol in last_signal_time and last_signal_time[symbol] == last_candle.name:
            continue

        # 4. Apply Strategy Conditions (from your _process function)
        atr_col = f"atr_{cfg.ATR_TIMEFRAME}"
        rsi_col = f"rsi_{cfg.RSI_TIMEFRAME}"
        adx_col = f"adx_{cfg.ADX_TIMEFRAME}"

        boom = (last_candle["close"] - last_candle["close_boom_ago"]) / last_candle["close_boom_ago"] >= cfg.PRICE_BOOM_PCT
        slow = (last_candle["close"] - last_candle["close_slowdown_ago"]) / last_candle["close_slowdown_ago"] <= cfg.PRICE_SLOWDOWN_PCT
        ema_down = last_candle["ema_fast_4h"] < last_candle["ema_slow_4h"]
        rsi_ok = cfg.RSI_ENTRY_MIN <= last_candle[rsi_col] <= cfg.RSI_ENTRY_MAX
        adx_ok = not cfg.ADX_FILTER_ENABLED or last_candle[adx_col] > cfg.ADX_MIN_LEVEL
        
        # Combine all conditions
        is_signal = all([boom, slow, ema_down, rsi_ok, adx_ok]) # Add other conditions here
        #is_signal = True
        if is_signal:
            logging.info(f"!!! SIGNAL DETECTED for {symbol} !!!")
            
            # 5. Format and Send Notification
            entry_price = last_candle['close']
            atr_value = last_candle[atr_col]
            stop_loss = entry_price + cfg.SL_ATR_MULT * atr_value
            take_profit = entry_price - cfg.TP_ATR_MULT * atr_value # Example TP

            message = (
                f"🚨 *New Short Signal: ${symbol}*\n\n"
                f"**Entry Price:** `{entry_price:.4f}`\n"
                f"**Stop Loss:**   `{stop_loss:.4f}` (Entry + {cfg.SL_ATR_MULT} * ATR)\n"
                f"**Take Profit:** `{take_profit:.4f}` (Entry - {cfg.TP_ATR_MULT} * ATR)\n\n"
                f"*Signal Details:*\n"
                f"- Time: `{last_candle.name.strftime('%Y-%m-%d %H:%M')}`\n"
                f"- RSI ({cfg.RSI_TIMEFRAME}): `{last_candle[rsi_col]:.2f}`\n"
                f"- ADX ({cfg.ADX_TIMEFRAME}): `{last_candle[adx_col]:.2f}`\n"
                f"- ATR ({cfg.ATR_TIMEFRAME}): `{atr_value:.5f}`"
            )
            
            asyncio.run(send_telegram_message(message))
            
            # Update the last signal time to prevent duplicates
            last_signal_time[symbol] = last_candle.name
        
        # Small delay to avoid hitting API rate limits
        time.sleep(2)


# --- Main Execution ---
if __name__ == "__main__":
    logging.info("Starting Crypto Signal Bot...")
    
    # Run the check once at the start
    check_for_signals()
    
    # Schedule the job
    schedule.every(cfg.BOT_SCHEDULE_MINUTES).minutes.do(check_for_signals)
    
    logging.info(f"Scheduled to run every {cfg.BOT_SCHEDULE_MINUTES} minutes.")
    
    while True:
        schedule.run_pending()
        time.sleep(1)