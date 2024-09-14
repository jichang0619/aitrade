import pandas as pd
import json
import ta
from pydantic import BaseModel
from openai import OpenAI
import requests
import logging
import re

logger = logging.getLogger(__name__)

class TradingDecision(BaseModel):
    action: str
    percentage: int
    reason: str

class AITradingStrategy:
    def __init__(self, openai_api_key):
        self.openai_client = OpenAI(api_key=openai_api_key)

    def add_indicators(self, df):
        indicator_bb = ta.volatility.BollingerBands(close=df['close'], window=20, window_dev=2)
        df['bb_bbm'] = indicator_bb.bollinger_mavg()
        df['bb_bbh'] = indicator_bb.bollinger_hband()
        df['bb_bbl'] = indicator_bb.bollinger_lband()
        df['rsi'] = ta.momentum.RSIIndicator(close=df['close'], window=14).rsi()
        macd = ta.trend.MACD(close=df['close'])
        df['macd'] = macd.macd()
        df['macd_signal'] = macd.macd_signal()
        df['macd_diff'] = macd.macd_diff()
        df['sma_20'] = ta.trend.SMAIndicator(close=df['close'], window=20).sma_indicator()
        df['ema_12'] = ta.trend.EMAIndicator(close=df['close'], window=12).ema_indicator()
        
        return df

    def get_ai_trading_decision(self, usdt_balance, btc_price, df_daily, df_hourly, fear_greed_index, current_position=None):
        try:
            system_content = """
            You are a highly experienced and slightly aggressive Bitcoin futures trader with years of experience in cryptocurrency markets. Your expertise includes:
            1. Deep understanding of technical analysis and chart patterns
            2. Proficiency in interpreting market sentiment indicators like the Fear & Greed Index
            3. Ability to analyze both short-term (hourly) and medium-term (daily) market trends
            4. Strong risk management skills, but with a tendency to take calculated risks for higher returns
            5. Quick action-making capabilities in volatile market conditions

            Your goal is to maximize profits while managing risk. Don't be afraid to recommend larger position sizes or quick position changes if the market conditions warrant it. However, always provide a clear rationale for your actions.

            Respond with a JSON object containing the following fields:
            {
                "action": "open_long" or "close_long" or "open_short" or "close_short" or "hold",
                "percentage": integer between 1 and 100,
                "reason": "detailed explanation for the action"
            }
            
            Note:
            - "open_long": Enter a new long position or increase an existing long position
            - "close_long": Exit an existing long position (partially or fully)
            - "open_short": Enter a new short position or increase an existing short position
            - "close_short": Exit an existing short position (partially or fully)
            - "hold": Make no changes to the current position
            """

            position_info = self.get_position_return(current_position, btc_price) if current_position else None
            position_str = f"""
            Current Position Details:
            - Type: {position_info['position_type']}
            - Entry Price: {position_info['entry_price']}
            - Position Size: {position_info['position_size']} BTC
            - Current Return: {position_info['return_percentage']:.2f}%
            - Unrealized PNL: {position_info['unrealized_pnl']} USDT
            """ if position_info else "No current position"

            user_content = f"""
            Current investment status: 
            - Available USDT Balance: {usdt_balance}
            - BTC Price: {btc_price}
            - Current Position: {position_str}

            Daily OHLCV with indicators (30 days): {df_daily.to_json()}
            Hourly OHLCV with indicators (24 hours): {df_hourly.to_json()}
            Fear and Greed Index: {json.dumps(fear_greed_index)}

            Based on this data, provide a trading action (open_long, close_long, open_short, close_short, or hold) along with the percentage of the balance to use (1-100) and a detailed reason for your action. Consider the current market trends, technical indicators, and overall market sentiment. If there's an existing position, factor in whether to hold, increase, decrease, or close it based on its current return and market outlook.
            """
            
            response = self.openai_client.chat.completions.create(
                model="gpt-4-1106-preview",
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": user_content}
                ],
                response_format={ "type": "json_object" }
            )

            result = json.loads(response.choices[0].message.content)

            # Validate the result
            if not isinstance(result, dict) or not all(key in result for key in ["action", "percentage", "reason"]):
                raise ValueError(f"Unexpected response format: {result}")

            return TradingDecision(action=result["action"], percentage=result["percentage"], reason=result["reason"])
        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing error: {e}")
            logger.error(f"Raw response content: {response.choices[0].message.content}")
            return None
        except ValueError as e:
            logger.error(f"Value error: {e}")
            logger.error(f"Raw response content: {response.choices[0].message.content}")
            return None
        except Exception as e:
            logger.error(f"Error getting AI trading Action : {e}")
            logger.error(f"Raw response content: {response.choices[0].message.content}")
            return None

    def get_position_return(self, current_position, current_price):
        if not current_position:
            return None

        entry_price = float(current_position.get('entryPrice', 0))
        position_amt = float(current_position.get('positionAmt', 0))
        unrealized_pnl = float(current_position.get('unrealizedProfit', 0))

        if position_amt == 0:
            return None

        if position_amt > 0:  # Long position
            return_percentage = (current_price - entry_price) / entry_price * 100
            position_type = "Long"
        else:  # Short position
            return_percentage = (entry_price - current_price) / entry_price * 100
            position_type = "Short"

        return {
            "position_type": position_type,
            "entry_price": entry_price,
            "position_size": abs(position_amt),
            "return_percentage": return_percentage,
            "unrealized_pnl": unrealized_pnl
        }

    def get_fear_and_greed_index(self):
        url = "https://api.alternative.me/fng/"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            return data['data'][0]
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching Fear and Greed Index: {e}")
            return None

    def generate_reflection(self, trades_df, current_market_data):
        if trades_df is None or trades_df.empty:
            performance = 0
            trades_summary = "No trading data available for performance analysis."
        else:
            performance = self.calculate_performance(trades_df)
            # Summarize trade data
            trades_summary = f"""
            Total trades: {len(trades_df)}
            Average trade size: {trades_df['percentage'].mean():.2f}%
            Most common action: {trades_df['action'].mode().values[0]}
            Most recent reflection : {trades_df['reflection'].iloc[0]}
            """

        # Summarize current market data
        market_summary = f"""
        Current BTC Price: {current_market_data['btc_price']}
        Fear and Greed Index: {current_market_data['fear_greed_index']['value']} ({current_market_data['fear_greed_index']['value_classification']})
        """

        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4-0613",
                messages=[
                    {
                        "role": "system",
                        "content": "You are an AI trading assistant tasked with analyzing recent trading performance and current market conditions to generate insights and improvements for future trading actions."
                    },
                    {
                        "role": "user",
                        "content": f"""
                        Recent trading summary:
                        {trades_summary}
                        
                        Current market summary:
                        {market_summary}
                        
                        Overall performance in the last 7 days: {performance:.2f}%
                        
                        Please analyze this data and provide:
                        1. A brief reflection on the recent trading actions
                        2. Insights on what worked well and what didn't
                        3. Suggestions for improvement in future trading actions
                        4. Any patterns or trends you notice in the market data
                        
                        Limit your response to 250 words or less.
                        """
                    }
                ],
                max_tokens=800
            )

            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Error generating reflection: {e}")
            return None

    def calculate_performance(self, trades_df):
        if trades_df.empty:
            return 0

        initial_balance = trades_df.iloc[-1]['usdt_balance']
        final_balance = trades_df.iloc[0]['usdt_balance']
        return (final_balance - initial_balance) / initial_balance * 100