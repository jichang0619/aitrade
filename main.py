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
    
def execute_trade(binance_trader, symbol, leverage, result, current_position, usdt_balance, btc_price, use_limit=True, wait_time=300):
    if usdt_balance is None or btc_price is None:
        logger.error("USDT balance or BTC price is None.")
        return {"status": "failed", "reason": "Invalid balance or price data"}
    
    if result.action == "hold":
        return {"status": "success", "reason": "AI decided to hold current position"}
    
    # Cancel all open orders including stop loss
    cancel_result = binance_trader.cancel_open_orders(symbol)
    if cancel_result["status"] == "failed":
        logger.error(f"Failed to cancel open orders: {cancel_result['reason']}")
        return cancel_result

    # Get current position amount
    current_position_amount = binance_trader.get_position_amount(symbol)
    if current_position_amount is None:
        return {"status": "failed", "reason": "Unable to get current position amount"}

    logger.info(f"Current position amount: {current_position_amount} BTC")

    if result.action in ["open_long", "close_short", "open_short", "close_long"]:
        if result.action in ["open_long", "open_short"]:
            # For opening positions, calculate amount in USDT
            usdt_amount_to_trade = usdt_balance * 0.95 * (result.percentage / 100)  # Using 95% of available balance
            amount_to_trade = usdt_amount_to_trade  # Keep in USDT for opening positions
            logger.info(f"Opening position: {amount_to_trade} USDT")
        else:  # close_long or close_short
            # For closing positions, calculate amount in BTC
            btc_amount_to_close = abs(current_position_amount) * (result.percentage / 100)
            amount_to_trade = btc_amount_to_close  # Keep in BTC for closing positions
            logger.info(f"Closing position: {amount_to_trade} BTC")

        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            try:
                # Ensure leverage is passed correctly
                trade_result = binance_trader.execute_position_action(result.action, symbol, amount_to_trade, leverage, use_limit, wait_time)

                if trade_result["status"] == "success":
                    logger.info(f"{result.action.capitalize()} order executed successfully: {trade_result}")
                    
                    # Set stop loss for opening positions
                    if result.action in ["open_long", "open_short"]:
                        entry_price = float(trade_result["order"]["avgPrice"])
                        executed_qty = abs(float(trade_result["order"]["executedQty"]))
                        stop_loss_result = binance_trader.set_stop_loss(symbol, "BUY" if result.action == "open_long" else "SELL", executed_qty, entry_price)
                        if stop_loss_result["status"] == "success":
                            logger.info(f"Stop loss set successfully: {stop_loss_result}")
                        else:
                            logger.warning(f"Failed to set stop loss: {stop_loss_result['reason']}. Continuing without stop loss.")
                    
                    return trade_result
                else:
                    logger.error(f"{result.action.capitalize()} order failed: {trade_result}")
                    return trade_result

            except BinanceAPIException as e:
                if e.code == -2019:  # Margin is insufficient
                    retry_count += 1
                    if retry_count < max_retries:
                        logger.warning(f"Insufficient margin. Retry {retry_count}/{max_retries}")
                        amount_to_trade *= 0.9  # 10% 감소
                        time.sleep(5)  # 재시도 전 대기
                    else:
                        logger.error("Max retries reached. Unable to execute trade due to insufficient margin.")
                        return {"status": "failed", "reason": "Max retries reached due to insufficient margin"}
                else:
                    logger.error(f"Binance API Error: {e}")
                    return {"status": "failed", "reason": str(e)}
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                return {"status": "failed", "reason": str(e)}
    else:
        return {"status": "failed", "reason": f"Invalid action: {result.action}"}
    
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
                logger.error("Failed to get AI trading actions.")
                return
            
            logger.info(f"AI Action: {result.action.upper()}")
            logger.info(f"Action Reason: {result.reason}")

            leverage = 10.0
            margin_type = "ISOLATED"
            binance_trader.set_leverage(symbol, leverage)
            binance_trader.set_margin_type(symbol, margin_type)

            order_result = execute_trade(binance_trader, symbol, leverage, result, current_position, usdt_balance, btc_price)

            log_trade(conn, result.action, result.percentage, result.reason, 
                      usdt_balance, btc_price, reflection, order_result)

            if order_result["status"] != "success":
                logger.error(f"{result.action.capitalize()} order failed: {order_result}")
            else:
                logger.info(f"{result.action.capitalize()} order executed successfully: {order_result}")

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
        await asyncio.sleep(1800)  # 30분 대기

if __name__ == "__main__":
    init_db()
    update_db_schema()
    
    trading_in_progress = False
    
    asyncio.run(main())