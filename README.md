Bitcoin Trading Bot
This project implements an automated Bitcoin trading bot using the Binance futures market. The bot utilizes AI-driven decision-making and technical analysis to execute trades.
Components
1. Main Script (paste.txt)
The main script orchestrates the entire trading process:

Initializes connections to Binance and OpenAI APIs
Sets up SQLite database for logging trades
Implements the main trading loop
Handles order execution and position management

Key functions:

init_db(): Initializes the SQLite database
ai_trading(): Main trading function that collects market data, gets AI decisions, and executes trades
execute_trade(): Handles the actual order placement on Binance

2. Binance Trading Module (paste-2.txt)
This module handles all interactions with the Binance Futures API:

Account and balance management
Order placement and management
Market data retrieval

Key functions:

open_long_position(), open_short_position(): Open new positions
close_long_position(), close_short_position(): Close existing positions
get_ohlcv(): Retrieve historical price data
execute_limit_order_with_fallback(): Place limit orders with market order fallback

3. AI Trading Strategy Module (paste-3.txt)
This module implements the AI-driven trading strategy:

Calculates technical indicators
Interacts with OpenAI's GPT model for trading decisions
Generates performance reflections

Key functions:

add_indicators(): Adds technical indicators to price data
get_ai_trading_decision(): Gets trading decisions from GPT model
generate_reflection(): Analyzes recent trades and market conditions

Setup and Usage

Install required dependencies (Binance API, OpenAI API, pandas, ta, etc.)
Set up environment variables for API keys
Initialize the SQLite database
Run the main script to start the trading bot

Note: This bot involves real money trading. Use at your own risk and always start with small amounts in a test environment.
Disclaimer
This trading bot is for educational purposes only. Cryptocurrency trading involves substantial risk of loss and is not suitable for every investor. The performance of this bot is not guaranteed, and the user assumes all financial risk.