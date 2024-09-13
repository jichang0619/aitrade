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
        self.symbol_info = {}

    def get_symbol_info(self, symbol):
        if symbol not in self.symbol_info:
            try:
                exchange_info = self.client.futures_exchange_info()
                for sym_info in exchange_info['symbols']:
                    if sym_info['symbol'] == symbol:
                        self.symbol_info[symbol] = sym_info
                        return sym_info
                logger.error(f"Symbol information for {symbol} not found.")
                return None
            except BinanceAPIException as e:
                logger.error(f"Error fetching symbol information: {e}")
                return None
        return self.symbol_info[symbol]

    def adjust_quantity(self, symbol, quantity):
        symbol_info = self.get_symbol_info(symbol)
        if symbol_info is None:
            return quantity

        step_size = float(next(filter(lambda x: x['filterType'] == 'LOT_SIZE', symbol_info['filters']))['stepSize'])
        precision = int(round(-math.log(step_size, 10), 0))
        
        adjusted_quantity = math.floor(quantity * (10 ** precision)) / (10 ** precision)
        
        min_qty = float(next(filter(lambda x: x['filterType'] == 'LOT_SIZE', symbol_info['filters']))['minQty'])
        if adjusted_quantity < min_qty:
            logger.warning(f"Adjusted quantity {adjusted_quantity} is less than minimum quantity {min_qty}. Setting to minimum.")
            adjusted_quantity = min_qty

        return adjusted_quantity

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

    def set_stop_loss(self, symbol, side, quantity, entry_price, risk_percentage=2.5):
        """
        Set a stop loss order for a given position.
        
        :param symbol: Trading pair symbol (e.g., 'BTCUSDT')
        :param side: 'BUY' for long positions, 'SELL' for short positions
        :param quantity: Position size
        :param entry_price: Entry price of the position
        :param risk_percentage: Percentage of entry price to set as stop loss (default 2%)
        :return: Result of the stop loss order placement
        """
        try:
            symbol_info = self.client.get_symbol_info(symbol)
            price_filter = next(filter(lambda f: f['filterType'] == 'PRICE_FILTER', symbol_info['filters']))
            tick_size = float(price_filter['tickSize'])

            if side == 'BUY':  # For long positions
                stop_price = entry_price * (1 - risk_percentage / 100)
                stop_side = 'SELL'
            else:  # For short positions
                stop_price = entry_price * (1 + risk_percentage / 100)
                stop_side = 'BUY'
            
            # Round the stop price to the nearest valid price
            stop_price = round(stop_price / tick_size) * tick_size
            
            stop_loss_order = self.client.futures_create_order(
                symbol=symbol,
                side=stop_side,
                type='STOP_MARKET',
                quantity=quantity,
                stopPrice=stop_price
            )
            
            logger.info(f"Stop loss order placed: {stop_loss_order}")
            return {"status": "success", "order": stop_loss_order}
        
        except BinanceAPIException as e:
            logger.error(f"Error setting stop loss: {e}")
            return {"status": "failed", "reason": str(e)}
        except Exception as e:
            logger.error(f"Unexpected error setting stop loss: {e}")
            return {"status": "failed", "reason": str(e)}
        
    def get_max_leverage(self, symbol):
        try:
            leverage_brackets = self.client.futures_leverage_bracket(symbol=symbol)
            return int(leverage_brackets[0]['brackets'][0]['initialLeverage'])
        except BinanceAPIException as e:
            logger.error(f"Error fetching max leverage: {e}")
            return None

    def get_available_balance(self, symbol):
        try:
            account_info = self.client.futures_account()
            for asset in account_info['assets']:
                if asset['asset'] == 'USDT':  # We're always trading with USDT in this case
                    return float(asset['availableBalance'])
        except BinanceAPIException as e:
            logger.error(f"Error fetching available balance: {e}")
            return None
        

            
    def execute_position_action(self, action, symbol, amount, leverage, use_limit=True, wait_time=300):
        try:
            max_leverage = self.get_max_leverage(symbol)
            if max_leverage is None:
                return {"status": "failed", "reason": "Unable to fetch max leverage"}
            
            if leverage > max_leverage:
                logger.warning(f"Requested leverage {leverage} exceeds max leverage {max_leverage}. Using max leverage.")
                leverage = max_leverage

            available_balance = self.get_available_balance(symbol)
            if available_balance is None:
                return {"status": "failed", "reason": "Unable to fetch available balance"}

            current_price = self.get_binance_futures_price(symbol)
            if current_price is None:
                return {"status": "failed", "reason": "Unable to fetch current price"}

            symbol_info = self.get_symbol_info(symbol)
            min_notional = float(next(filter(lambda x: x['filterType'] == 'MIN_NOTIONAL', symbol_info['filters']))['notional'])
            
            # Calculate the quantity considering leverage
            quantity = (amount * leverage) / current_price
            
            # Ensure the order meets the minimum notional value
            min_qty = max(min_notional / current_price, float(next(filter(lambda x: x['filterType'] == 'LOT_SIZE', symbol_info['filters']))['minQty']))
            
            max_position_size = (available_balance * leverage) / current_price
            quantity = self.adjust_quantity(symbol, max(min(quantity, max_position_size), min_qty))

            logger.info(f"Available balance: {available_balance} USDT")
            logger.info(f"Current price: {current_price} USDT")
            logger.info(f"Leverage: {leverage}x")
            logger.info(f"Max position size: {max_position_size} {symbol}")
            logger.info(f"Minimum quantity: {min_qty} {symbol}")
            logger.info(f"Adjusted quantity: {quantity} {symbol}")
            logger.info(f"Order value (with leverage): {quantity * current_price} USDT")

            if quantity * current_price < min_notional:
                return {"status": "failed", "reason": f"Insufficient balance. Minimum order value is {min_notional} USDT."}

            if use_limit:
                if action in ['open_long', 'close_short']:
                    side = "BUY"
                    limit_price = self.adjust_price(symbol, current_price * 1.001)  # 0.1% higher
                else:
                    side = "SELL"
                    limit_price = self.adjust_price(symbol, current_price * 0.999)  # 0.1% lower
                
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

        except BinanceAPIException as e:
            logger.error(f"Binance API error in execute_position_action: {e}")
            return {"status": "failed", "reason": str(e)}
        except Exception as e:
            logger.error(f"Unexpected error in execute_position_action: {e}")
            return {"status": "failed", "reason": str(e)}
            
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