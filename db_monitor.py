import sqlite3
import logging
import os
from dotenv import load_dotenv
import asyncio
from aiogram import Bot


# Load environment variables
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
DB_PATH = 'futures_trades.db'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TELEGRAM_TOKEN)

def fetch_last_trade(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 1")
    trade = cursor.fetchone()
    conn.close()
    return trade

async def send_trade_update():
    trade = fetch_last_trade(DB_PATH)
    if trade:
        trade_message = f"Last trade:\nID: {trade[0]}\nSymbol: {trade[1]}\nPrice: {trade[2]}\nQuantity: {trade[3]}"
        try:
            # Use HTML or Markdown formatting directly
            html_message = trade_message.replace('-', '&#45;')
            await bot.send_message(chat_id=CHAT_ID, text=html_message, parse_mode="HTML")
            logger.info("Message sent successfully.")
        except Exception as e:
            logger.error(f"Error sending message: {e}")
        finally:
            # Clean up resources or handle post-message tasks if necessary
            pass  # No additional actions required

async def main():
    await send_trade_update()

if __name__ == '__main__':
    asyncio.run(main())