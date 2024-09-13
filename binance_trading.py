import logging
from binance.client import Client
from binance.exceptions import BinanceAPIException
import pandas as pd
import requests
import time
import math

logger = logging.getLogger(__name__)

class BinanceTrading:
    def __init__(self, api_key, api_secret):
        self.client = Client(api_key, api_secret)

    def get_symbol_info(self, symbol):
        try:
            exchange_info = self.client.futures_exchange_info()
            for sym_info in exchange_info['symbols']:
                if sym_info['symbol'] == symbol:
                    return sym_info
            logger.error(f"Symbol information for {symbol} not found.")
            return None
        except BinanceAPIException as e:
            logger.error(f"Error fetching symbol information: {e}")
            return None

    def adjust_quantity(self, symbol, quantity):
        symbol_info = self.get_symbol_info(symbol)
        if symbol_info is None:
            return quantity

        step_size = float(next(filter(lambda x: x['filterType'] == 'LOT_SIZE', symbol_info['filters']))['stepSize'])
        precision = int(round(-math.log(step_size, 10), 0))
        return round(quantity, precision)

    def adjust_price(self, symbol, price):
        symbol_info = self.get_symbol_info(symbol)
        if symbol_info is None:
            return price

        tick_size = float(next(filter(lambda x: x['filterType'] == 'PRICE_FILTER', symbol_info['filters']))['tickSize'])
        precision = int(round(-math.log(tick_size, 10), 0))
        return round(price, precision)

    def get_futures_account_balance(self):
        try:
            account_info = self.client.futures_account()
            available_balance = float(account_info['availableBalance'])
            return available_balance
        except BinanceAPIException as e:
            logger.error(f"Error fetching futures account balance: {e}")
            return 0.0

    def execute_position_action(self, action, symbol, amount, leverage, use_limit=True, wait_time=300):
        try:
            quantity = self.adjust_quantity(symbol, amount * leverage)
            
            if use_limit:
                current_price = self.get_binance_futures_price(symbol)
                if action in ['open_long', 'close_short']:
                    limit_price = self.adjust_price(symbol, current_price * 1.001)  # 0.1% higher
                    side = 'BUY'
                else:
                    limit_price = self.adjust_price(symbol, current_price * 0.999)  # 0.1% lower
                    side = 'SELL'
                
                return self.execute_limit_order_with_fallback(symbol, side, quantity, limit_price, wait_time)
            else:
                order = self.client.futures_create_order(
                    symbol=symbol,
                    side="BUY" if action in ['open_long', 'close_short'] else "SELL",
                    type="MARKET",
                    quantity=quantity
                )
                logger.info(f"{action.capitalize()} executed successfully: {quantity} {symbol}")
                return {"status": "success", "order": order}
        except Exception as e:
            logger.error(f"Error executing {action}: {e}")
            return None

    def open_long_position(self, symbol, amount, leverage, use_limit=True, wait_time=300):
        return self.execute_position_action('open_long', symbol, amount, leverage, use_limit, wait_time)

    def open_short_position(self, symbol, amount, leverage, use_limit=True, wait_time=300):
        return self.execute_position_action('open_short', symbol, amount, leverage, use_limit, wait_time)

    def close_long_position(self, symbol, position_amt, use_limit=True, wait_time=300):
        return self.execute_position_action('close_long', symbol, position_amt, 1, use_limit, wait_time)

    def close_short_position(self, symbol, position_amt, use_limit=True, wait_time=300):
        return self.execute_position_action('close_short', symbol, position_amt, 1, use_limit, wait_time)

    def get_binance_futures_price(self, symbol='BTCUSDT'):
        try:
            price = self.client.futures_symbol_ticker(symbol=symbol)['price']
            return float(price)
        except BinanceAPIException as e:
            logger.error(f"Error fetching Binance Futures price: {e}")
            return None

    def get_position(self, symbol):
        try:
            positions = self.client.futures_position_information(symbol=symbol)
            for pos in positions:
                if float(pos["positionAmt"]) != 0:
                    return pos
            return None
        except BinanceAPIException as e:
            logger.error(f"Error fetching position information: {e}")
            return None

    def set_leverage(self, symbol, leverage):
        if leverage is None:
            logger.error("Leverage value is None.")
            return

        try:
            response = self.client.futures_change_leverage(symbol=symbol, leverage=int(leverage))
            logger.info(f"Leverage set to {leverage} for {symbol}: {response}")
        except BinanceAPIException as e:
            logger.error(f"Error setting leverage: {e}")

    def set_margin_type(self, symbol, margin_type="ISOLATED"):
        try:
            current_margin_type = self.client.futures_get_position_mode()
            if current_margin_type['dualSidePosition']:  # Hedge Mode
                logger.info("Account is in Hedge Mode. No need to change margin type.")
                return
            
            self.client.futures_change_margin_type(symbol=symbol, marginType=margin_type)
            logger.info(f"Margin mode set to {margin_type}.")
        except BinanceAPIException as e:
            if e.code == -4046:  # "No need to change margin type" error
                logger.info(f"Margin mode is already {margin_type}. No change needed.")
            else:
                logger.error(f"Error setting margin type: {e}")

    def get_ohlcv(self, symbol, interval="1h", limit=500):
        base_url = "https://fapi.binance.com"
        endpoint = "/fapi/v1/klines"
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }

        try:
            response = requests.get(base_url + endpoint, params=params)
            response.raise_for_status()
            data = response.json()

            df = pd.DataFrame(data, columns=[
                "timestamp", "open", "high", "low", "close", "volume", 
                "close_time", "quote_asset_volume", "number_of_trades", 
                "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"
            ])

            df["timestamp"] = pd.to_datetime(df["timestamp"], unit='ms')
            df = df[["timestamp", "open", "high", "low", "close", "volume"]]
            df = df.astype({
                "open": "float", "high": "float", "low": "float", "close": "float", "volume": "float"
            })

            return df

        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching OHLCV data: {e}")
            return None

    def execute_limit_order_with_fallback(self, symbol, side, quantity, price, wait_time=300):
        try:
            limit_order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='LIMIT',
                timeInForce='GTC',
                quantity=quantity,
                price=price
            )
            logger.info(f"Limit order placed: {limit_order}")

            order_id = limit_order['orderId']
            start_time = time.time()

            while time.time() - start_time < wait_time:
                order_status = self.client.futures_get_order(symbol=symbol, orderId=order_id)

                if order_status['status'] == 'FILLED':
                    return {"status": "success", "order": order_status}

                if order_status['status'] == 'PARTIALLY_FILLED':
                    filled_qty = float(order_status['executedQty'])
                    remaining_qty = quantity - filled_qty

                    if time.time() - start_time >= 300:
                        self.client.futures_cancel_order(symbol=symbol, orderId=order_id)
                        market_order = self.client.futures_create_order(
                            symbol=symbol,
                            side=side,
                            type='MARKET',
                            quantity=remaining_qty
                        )
                        return {"status": "partial_limit_full_market", "limit_order": order_status, "market_order": market_order}

                time.sleep(10)

            self.client.futures_cancel_order(symbol=symbol, orderId=order_id)
            market_order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='MARKET',
                quantity=quantity
            )
            return {"status": "timeout_full_market", "market_order": market_order}

        except Exception as e:
            logger.error(f"Error executing limit order with fallback: {e}")
            return {"status": "failed", "reason": str(e)}