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

def get_action_emoji(action):
    if 'long' in action.lower():
        return '🚀' if 'open' in action.lower() else '🛬'
    elif 'short' in action.lower():
        return '🐻' if 'open' in action.lower() else '🛫'
    else:
        return '🔄'

async def send_trade_update(bot):
    trade = fetch_last_trade(DB_PATH)
    if trade:
        action_emoji = get_action_emoji(trade[2])
        
        trade_message = f"""🔔 <b>Last Trade Update</b> 🔔

🔢 <b>Trade Num:</b> {trade[0]}
🕒 <b>Time:</b> {trade[1]}
🎯 <b>Action:</b> {action_emoji} {trade[2]}
📊 <b>Percentage:</b> {trade[3]}%
🚦 <b>Status:</b> {'✅' if trade[8] == 'success' else '❌'} {trade[8]}
📝 <b>Order Info:</b> {trade[9]}

💰 <b>USDT Balance:</b> {trade[5]:.2f}
💲 <b>BTC Price:</b> ${trade[6]:.2f}"""

        ai_reason_message = f"""🤖 <b>AI Action Reasoning</b> 🧠

{trade[4]}"""

        reflection_message = f"""🔮 <b>Trade Reflection</b> 📊

{trade[7]}"""

        try:
            # Send initial trade update
            await bot.send_message(chat_id=CHAT_ID, text=trade_message, parse_mode="HTML")
            logger.info("Trade update message sent successfully.")

            # Wait for 10 seconds
            await asyncio.sleep(10)

            # Send AI action reason
            await bot.send_message(chat_id=CHAT_ID, text=ai_reason_message, parse_mode="HTML")
            logger.info("AI action reason message sent successfully.")

            # Wait for another 10 seconds
            await asyncio.sleep(10)

            # Send reflection
            await bot.send_message(chat_id=CHAT_ID, text=reflection_message, parse_mode="HTML")
            logger.info("Reflection message sent successfully.")

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