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

async def send_trade_update(bot):
    trade = fetch_last_trade(DB_PATH)
    if trade:
        trade_message = f"""Last trade attempt:
Trade Num: {trade[0]}
Time: {trade[1]}
Action: {trade[2]}
Percentage: {trade[3]}
Status: {trade[8]}
Reason: {trade[9]}"""
        try:
            html_message = trade_message.replace('-', '&#45;')
            await bot.send_message(chat_id=CHAT_ID, text=html_message, parse_mode="HTML")
            logger.info("Message sent successfully.")
        except Exception as e:
            logger.error(f"Error sending message: {e}")

async def main():
    bot = Bot(token=TELEGRAM_TOKEN)
    try:
        await send_trade_update(bot)
    finally:
        await bot.session.close()

if __name__ == '__main__':
    asyncio.run(main())