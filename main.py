import time
import sqlite3
import logging
import os
import pandas as pd
from dotenv import load_dotenv
from binance_trading import BinanceTrading
from ai_trading_strategy import AITradingStrategy

# Load environment variables
load_dotenv()

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Binance and AI trading instances
binance_api_key = os.getenv("BINANCE_ACCESS_KEY")
binance_api_secret = os.getenv("BINANCE_SECRET_KEY")
openai_api_key = os.getenv("OPENAI_API_KEY")

binance_trader = BinanceTrading(binance_api_key, binance_api_secret)
ai_strategy = AITradingStrategy(openai_api_key)

def init_db():
    conn = sqlite3.connect('futures_trades.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS trades
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  timestamp TEXT,
                  decision TEXT,
                  percentage INTEGER,
                  reason TEXT,
                  usdt_balance REAL,
                  btc_price REAL,
                  reflection TEXT,
                  order_status TEXT,
                  order_reason TEXT)''')
    conn.commit()
    return conn

def update_db_schema():
    conn = sqlite3.connect('futures_trades.db')
    c = conn.cursor()

    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='trades';")
    if not c.fetchone():
        logger.error("'trades' table does not exist. Run init_db() to create the table.")
        return

    c.execute("PRAGMA table_info(trades)")
    columns = [column[1] for column in c.fetchall()]

    if 'order_status' not in columns:
        c.execute("ALTER TABLE trades ADD COLUMN order_status TEXT")
    if 'order_reason' not in columns:
        c.execute("ALTER TABLE trades ADD COLUMN order_reason TEXT")

    conn.commit()
    conn.close()

def log_trade(conn, decision, percentage, reason, usdt_balance, btc_price, reflection, order_result):
    c = conn.cursor()
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    
    order_status = order_result.get("status", "unknown")
    order_reason = order_result.get("reason", "")
    
    c.execute("""INSERT INTO trades 
                 (timestamp, decision, percentage, reason, usdt_balance, btc_price, reflection, order_status, order_reason) 
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
              (timestamp, decision, percentage, reason, usdt_balance, btc_price, reflection, order_status, order_reason))
    conn.commit()

def get_recent_trades(conn, days=7):
    c = conn.cursor()
    seven_days_ago = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time() - days * 24 * 60 * 60))
    c.execute("SELECT * FROM trades WHERE timestamp > ? ORDER BY timestamp DESC", (seven_days_ago,))
    columns = [column[0] for column in c.description]
    return pd.DataFrame.from_records(data=c.fetchall(), columns=columns)

def execute_trade(symbol, leverage, result, current_position, usdt_balance, btc_price, use_limit=True, wait_time=300):
    if usdt_balance is None or btc_price is None:
        logger.error("USDT balance or BTC price is None.")
        return {"status": "failed", "reason": "Invalid balance or price data"}
    
    if result.decision in ["buy", "sell"]:
        if current_position and float(current_position["positionAmt"]) != 0:
            # Calculate the quantity to trade based on the current position
            position_size = abs(float(current_position["positionAmt"]))
            trade_quantity = position_size * (result.percentage / 100)
        else:
            # Calculate the quantity to trade based on the USDT balance
            trade_quantity = (usdt_balance * (result.percentage / 100)) / btc_price
        
        try:
            if result.decision == "buy":
                if current_position and float(current_position["positionAmt"]) < 0:
                    # Close short position if exists
                    order_result = binance_trader.close_short_position(symbol, trade_quantity, use_limit, wait_time)
                else:
                    # Open long position
                    order_result = binance_trader.open_long_position(symbol, trade_quantity, leverage, use_limit, wait_time)
            else:  # sell
                if current_position and float(current_position["positionAmt"]) > 0:
                    # Close long position if exists
                    order_result = binance_trader.close_long_position(symbol, trade_quantity, use_limit, wait_time)
                else:
                    # Open short position
                    order_result = binance_trader.open_short_position(symbol, trade_quantity, leverage, use_limit, wait_time)

            if order_result and order_result.get("status") in ["success", "partial_limit_full_market", "timeout_full_market"]:
                logger.info(f"{result.decision.capitalize()} order executed: {order_result}")
                return {"status": "success", "order": order_result}
            else:
                logger.error(f"{result.decision.capitalize()} order failed: {order_result}")
                return {"status": "failed", "reason": order_result.get("reason", "Unknown error")}
        except Exception as e:
            logger.error(f"Error executing {result.decision} order: {e}")
            return {"status": "failed", "reason": str(e)}
    else:  # hold
        return {"status": "hold", "reason": "No trade executed"}

def ai_trading():
    usdt_balance = binance_trader.get_futures_account_balance()
    btc_price = binance_trader.get_binance_futures_price()

    if usdt_balance is None or btc_price is None:
        logger.error("Unable to retrieve balance or price data.")
        return
    
    logger.info(f"Available USDT Balance: {usdt_balance}, BTC Price: {btc_price}")
    
    df_daily = binance_trader.get_ohlcv("BTCUSDT", interval="1d", limit=30)
    df_daily = ai_strategy.add_indicators(df_daily)
    
    df_hourly = binance_trader.get_ohlcv("BTCUSDT", interval="1h", limit=24)
    df_hourly = ai_strategy.add_indicators(df_hourly)
    
    fear_greed_index = ai_strategy.get_fear_and_greed_index()
    
    try:
        with sqlite3.connect('futures_trades.db') as conn:
            recent_trades = get_recent_trades(conn)
            current_market_data = {
                "fear_greed_index": fear_greed_index,
                "daily_ohlcv": df_daily.to_dict(),
                "hourly_ohlcv": df_hourly.to_dict(),
                "btc_price": btc_price
            }
            reflection = ai_strategy.generate_reflection(recent_trades, current_market_data)
            
            symbol = "BTCUSDT"
            position = binance_trader.get_position(symbol)
            current_position = position if position and float(position.get("positionAmt", 0)) != 0 else None
            
            result = ai_strategy.get_ai_trading_decision(usdt_balance, btc_price, df_daily, df_hourly, fear_greed_index, current_position)
            
            if result is None:
                logger.error("Failed to get AI trading decision.")
                return
            
            logger.info(f"AI Decision: {result.decision.upper()}")
            logger.info(f"Decision Reason: {result.reason}")

            leverage = 10.0
            margin_type = "ISOLATED"
            binance_trader.set_leverage(symbol, leverage)
            binance_trader.set_margin_type(symbol, margin_type)

            order_result = execute_trade(symbol=symbol, leverage=leverage, result=result, 
                                         current_position=current_position, usdt_balance=usdt_balance, 
                                         btc_price=btc_price, use_limit=True, wait_time=300)
            
            log_trade(conn, result.decision, result.percentage, result.reason, 
                      usdt_balance, btc_price, reflection, order_result)
    except sqlite3.Error as e:
        logger.error(f"Database connection error: {e}")
        return

if __name__ == "__main__":
    init_db()
    update_db_schema()
    
    trading_in_progress = False
    
    def job():
        global trading_in_progress
        if trading_in_progress:
            logger.warning("Trading job is already in progress, skipping this run.")
            return
        try:
            trading_in_progress = True
            ai_trading()
        except Exception as e:
            logger.error(f"An error occurred: {e}")
        finally:
            trading_in_progress = False

    # Run the job every 20 minutes
    while True:
        job()
        time.sleep(1200)  # Sleep for 20 minutes