# 🤖 Bitcoin Trading Bot

![Python](https://img.shields.io/badge/Python-3.7%2B-blue)
![Binance](https://img.shields.io/badge/Binance-Futures-yellow)
![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4-green)

An automated Bitcoin trading bot leveraging AI-driven decision-making and technical analysis on the Binance futures market.

## 📚 Table of Contents

- [Components](#components)
- [Setup](#setup)
- [Usage](#usage)
- [Disclaimer](#disclaimer)

## 🧩 Components

### 1. Main Script (`main.py`)

Orchestrates the entire trading process:

- 🔗 Initializes API connections
- 🗃️ Sets up SQLite database
- 🔄 Implements main trading loop
- 📊 Handles order execution and position management

**Key Functions:**
- `init_db()`: Initializes the SQLite database
- `ai_trading()`: Main trading function
- `execute_trade()`: Handles order placement

### 2. Binance Trading Module (`binance_trading.py`)

Manages all Binance Futures API interactions:

- 💼 Account and balance management
- 📈 Order placement and management
- 📉 Market data retrieval

**Key Functions:**
- `open_long_position()`, `open_short_position()`
- `close_long_position()`, `close_short_position()`
- `get_ohlcv()`: Retrieve historical price data
- `execute_limit_order_with_fallback()`

### 3. AI Trading Strategy Module (`ai_trading_strategy.py`)

Implements the AI-driven trading strategy:

- 📊 Calculates technical indicators
- 🧠 Interacts with OpenAI's GPT model
- 📝 Generates performance reflections

**Key Functions:**
- `add_indicators()`: Adds technical indicators to price data
- `get_ai_trading_decision()`: Gets trading decisions from GPT model
- `generate_reflection()`: Analyzes recent trades and market conditions

## 🛠 Setup
1. Install required dependencies:
pip install binance-futures openai pandas ta pydantic

2. Set up environment variables:
export BINANCE_ACCESS_KEY=your_binance_key
export BINANCE_SECRET_KEY=your_binance_secret
export OPENAI_API_KEY=your_openai_key

3. Initialize the SQLite database:
```python
from main import init_db
init_db()

