import time
import sqlite3
import logging
import os
import pandas as pd
from dotenv import load_dotenv
from binance_trading import BinanceTrading
from ai_trading_strategy import AITradingStrategy
import db_monitor
import asyncio
from binance.exceptions import BinanceAPIException

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


def run_monitor():
    db_monitor.main()
    
def init_db():
    conn = sqlite3.connect('futures_trades.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS trades
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  timestamp TEXT,
                  action TEXT,
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

    if 'action' not in columns:
        c.execute("ALTER TABLE trades ADD COLUMN action TEXT")
    if 'order_status' not in columns:
        c.execute("ALTER TABLE trades ADD COLUMN order_status TEXT")
    if 'order_reason' not in columns:
        c.execute("ALTER TABLE trades ADD COLUMN order_reason TEXT")

    conn.commit()
    conn.close()

def log_trade(conn, action, percentage, reason, usdt_balance, btc_price, reflection, order_result):
    c = conn.cursor()
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    
    order_status = order_result.get("status", "unknown")
    order_reason = order_result.get("reason", "")
    
    c.execute("""INSERT INTO trades 
                 (timestamp, action, percentage, reason, usdt_balance, btc_price, reflection, order_status, order_reason) 
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
              (timestamp, action, percentage, reason, usdt_balance, btc_price, reflection, order_status, order_reason))
    conn.commit()

def get_recent_trades(conn, days=7):
    c = conn.cursor()
    seven_days_ago = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time() - days * 24 * 60 * 60))
    c.execute("SELECT * FROM trades WHERE timestamp > ? ORDER BY timestamp DESC", (seven_days_ago,))
    columns = [column[0] for column in c.description]
    return pd.DataFrame.from_records(data=c.fetchall(), columns=columns)
    
def trade_main(binance_trader, symbol, leverage, gpt_result, current_position, usdt_balance, btc_price, use_limit=True, wait_time=300):
    if usdt_balance is None or btc_price is None:
        logger.error("USDT balance or BTC price is None.")
        return {"status": "failed", "reason": "Invalid balance or price data"}
    
    # Cancel all open orders including stop loss
    cancel_result = binance_trader.cancel_open_orders(symbol)
    if cancel_result["status"] == "failed":
        logger.error(f"Failed to cancel open orders: {cancel_result['reason']}")
        return cancel_result

    try:
        if gpt_result.action == "hold":
            return {"status": "success", "reason": "AI decided to hold current position"}
        
        elif gpt_result.action in ["open_long", "open_short"]:
            if gpt_result.action == "open_long":
                order_result = binance_trader.open_long_position(symbol, usdt_balance, leverage, gpt_result.percentage, use_limit, wait_time)
            else:
                order_result = binance_trader.open_short_position(symbol, usdt_balance, leverage, gpt_result.percentage, use_limit, wait_time)
        
        elif gpt_result.action in ["close_long", "close_short"]:
            # close position 이 제대로 나오는지... gpt 가 현재 포지션이 있을때만 나와야함
            if current_position is None:
                return {"status": "failed", "reason": "No position to close"}
            else:
                position_size = abs(float(current_position['positionAmt']))
                if gpt_result.action == "close_long":
                    order_result = binance_trader.close_long_position(symbol, position_size, gpt_result.percentage, use_limit, wait_time)
                else:
                    order_result = binance_trader.close_short_position(symbol, position_size, gpt_result.percentage, use_limit, wait_time)
        else:
            return {"status": "failed", "reason": f"Invalid action: {gpt_result.action}"}

        if order_result["status"] == "success":
            logger.info(f"{gpt_result.action.capitalize()} order executed successfully: {order_result}")
            
            # Set stop loss for opening positions
            if gpt_result.action in ["open_long", "open_short"]:
                entry_price = float(order_result["order"]["avgPrice"])
                executed_qty = abs(float(order_result["order"]["executedQty"]))
                stop_loss_result = binance_trader.set_stop_loss(symbol, "BUY" if gpt_result.action == "open_long" else "SELL", executed_qty, entry_price)
                if stop_loss_result["status"] == "success":
                    logger.info(f"Stop loss set successfully: {stop_loss_result}")
                else:
                    logger.warning(f"Failed to set stop loss: {stop_loss_result['reason']}. Continuing without stop loss.")
        else:
            logger.error(f"{gpt_result.action.capitalize()} order failed: {order_result}")

        return order_result

    except Exception as e:
        logger.error(f"Unexpected error in execute_trade: {e}")
        return {"status": "failed", "reason": str(e)}    

def ai_trading():
    symbol = "BTCUSDT"
    usdt_balance = binance_trader.get_futures_account_balance()
    btc_price = binance_trader.get_binance_futures_price(symbol)

    if usdt_balance is None or btc_price is None:
        logger.error("Unable to retrieve balance or price data.")
        return
    
    logger.info(f"Available USDT Balance: {usdt_balance}, BTC Price: {btc_price}")
    
    df_daily = binance_trader.get_ohlcv(symbol, interval="1d", limit=30)
    df_daily = ai_strategy.add_indicators(df_daily)
    df_hourly = binance_trader.get_ohlcv(symbol, interval="1h", limit=24)
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
            
            position = binance_trader.get_position(symbol)
            current_position = position if position and float(position.get("positionAmt", 0)) != 0 else None
            
            gpt_result = ai_strategy.get_ai_trading_decision(usdt_balance, btc_price, df_daily, df_hourly, fear_greed_index, current_position)
            
            
            if gpt_result is None:
                logger.error("Failed to get AI trading actions.")
                return
            
            logger.info(f"AI Action: {gpt_result.action.upper()}")
            logger.info(f"Action Reason: {gpt_result.reason}")
            logger.info(f"Action Percentage: {gpt_result.percentage}%")

            leverage = 10.0
            margin_type = "ISOLATED"
            binance_trader.set_leverage(symbol, leverage)
            binance_trader.set_margin_type(symbol, margin_type)

            order_result = trade_main(binance_trader, symbol, leverage, gpt_result, current_position, usdt_balance, btc_price)

            log_trade(conn, gpt_result.action, gpt_result.percentage, gpt_result.reason, 
                      usdt_balance, btc_price, reflection, order_result)

            if order_result["status"] != "success":
                logger.error(f"{gpt_result.action.capitalize()} order failed: {order_result}")
            else:
                logger.info(f"{gpt_result.action.capitalize()} order executed successfully: {order_result}")

    except sqlite3.Error as e:
        logger.error(f"Database connection error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error in ai_trading: {e}")

async def run_trading_job():
    global trading_in_progress
    if trading_in_progress:
        logger.warning("Trading job is already in progress, skipping this run.")
        return
    try:
        trading_in_progress = True
        await asyncio.to_thread(ai_trading)
    except Exception as e:
        logger.error(f"An error occurred: {e}")
    finally:
        trading_in_progress = False

async def main():
    while True:
        await run_trading_job()
        await db_monitor.main()
        await asyncio.sleep(3600)  # 30분 대기

if __name__ == "__main__":
    init_db()
    update_db_schema()
    
    trading_in_progress = False
    
    asyncio.run(main())