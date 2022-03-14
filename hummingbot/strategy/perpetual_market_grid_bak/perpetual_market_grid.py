import logging
# import time
from decimal import Decimal
# from itertools import chain
# from math import ceil, floor
from typing import Dict, List

# import numpy as np
# import pandas as pd

# from hummingbot.connector.derivative.position import Position
# from hummingbot.connector.exchange_base import ExchangeBase
# from hummingbot.core.clock import Clock
# from hummingbot.core.data_type.limit_order import LimitOrder
# from hummingbot.core.data_type.order_candidate import PerpetualOrderCandidate
from hummingbot.core.event.events import (
    # BuyOrderCompletedEvent,
    # OrderFilledEvent,
    OrderType,
    # PositionAction,
    PositionMode,
    PriceType,
    # SellOrderCompletedEvent,
    # TradeType
)
# from hummingbot.core.network_iterator import NetworkStatus
# from hummingbot.core.utils import map_df_to_str
from hummingbot.strategy.asset_price_delegate import AssetPriceDelegate
from hummingbot.strategy.market_trading_pair_tuple import MarketTradingPairTuple
# from hummingbot.strategy.order_book_asset_price_delegate import OrderBookAssetPriceDelegate
# from hummingbot.strategy.perpetual_market_grid.data_types import PriceSize, Proposal
from hummingbot.strategy.perpetual_market_grid.perpetual_market_grid_order_tracker import (
    PerpetualMarketGridOrderTracker
)
from hummingbot.strategy.strategy_py_base import StrategyPyBase

NaN = float("nan")
s_decimal_zero = Decimal(0)
s_decimal_neg_one = Decimal(-1)


class PerpetualMarketGridStrategy(StrategyPyBase):
    OPTION_LOG_CREATE_ORDER = 1 << 3
    OPTION_LOG_GRID_ORDER_FILLED = 1 << 4
    OPTION_LOG_STATUS_REPORT = 1 << 5
    OPTION_LOG_ALL = 0x7fffffffffffffff
    _logger = None

    @classmethod
    def logger(cls):
        if cls._logger is None:
            cls._logger = logging.getLogger(__name__)
        return cls._logger

    def init_params(self,
                    market_info: MarketTradingPairTuple,
                    leverage: int,
                    position_mode: str,
                    bid_spread: Decimal,
                    ask_spread: Decimal,
                    order_amount: Decimal,
                    long_profit_taking_spread: Decimal,
                    short_profit_taking_spread: Decimal,
                    stop_loss_spread: Decimal,
                    time_between_stop_loss_orders: float,
                    stop_loss_slippage_buffer: Decimal,
                    grid_interval: Decimal,
                    order_levels: int = 1,
                    order_level_spread: Decimal = s_decimal_zero,
                    order_level_amount: Decimal = s_decimal_zero,
                    order_refresh_time: float = 30.0,
                    order_refresh_tolerance_pct: Decimal = s_decimal_neg_one,
                    filled_order_delay: float = 60.0,
                    order_optimization_enabled: bool = False,
                    ask_order_optimization_depth: Decimal = s_decimal_zero,
                    bid_order_optimization_depth: Decimal = s_decimal_zero,
                    asset_price_delegate: AssetPriceDelegate = None,
                    price_type: str = "mid_price",
                    price_ceiling: Decimal = s_decimal_neg_one,
                    price_floor: Decimal = s_decimal_neg_one,
                    logging_options: int = OPTION_LOG_ALL,
                    status_report_interval: float = 900,
                    minimum_spread: Decimal = Decimal(0),
                    hb_app_notification: bool = False,
                    order_override: Dict[str, List[str]] = {},
                    ):

        if price_ceiling != s_decimal_neg_one and price_ceiling < price_floor:
            raise ValueError("Parameter price_ceiling cannot be lower than price_floor.")

        self._sb_order_tracker = PerpetualMarketGridOrderTracker()
        self._market_info = market_info
        self._leverage = leverage
        self._position_mode = PositionMode.HEDGE if position_mode == "Hedge" else PositionMode.ONEWAY
        self._bid_spread = bid_spread
        self._ask_spread = ask_spread
        self._minimum_spread = minimum_spread
        self._order_amount = order_amount
        self._long_profit_taking_spread = long_profit_taking_spread
        self._short_profit_taking_spread = short_profit_taking_spread
        self._stop_loss_spread = stop_loss_spread
        self._order_levels = order_levels
        self._buy_levels = order_levels
        self._sell_levels = order_levels
        self._order_level_spread = order_level_spread
        self._order_level_amount = order_level_amount
        self._order_refresh_time = order_refresh_time
        self._order_refresh_tolerance_pct = order_refresh_tolerance_pct
        self._filled_order_delay = filled_order_delay
        self._order_optimization_enabled = order_optimization_enabled
        self._ask_order_optimization_depth = ask_order_optimization_depth
        self._bid_order_optimization_depth = bid_order_optimization_depth
        self._asset_price_delegate = asset_price_delegate
        self._price_type = self.get_price_type(price_type)
        self._price_ceiling = price_ceiling
        self._price_floor = price_floor
        self._hb_app_notification = hb_app_notification
        self._order_override = order_override

        self._cancel_timestamp = 0
        self._create_timestamp = 0
        self._all_markets_ready = False
        self._logging_options = logging_options
        self._last_timestamp = 0
        self._status_report_interval = status_report_interval
        self._last_own_trade_price = Decimal('nan')
        self._ts_peak_bid_price = Decimal('0')
        self._ts_peak_ask_price = Decimal('0')
        self._exit_orders = dict()
        self._next_buy_exit_order_timestamp = 0
        self._next_sell_exit_order_timestamp = 0

        self.add_markets([market_info.market])

        self._close_order_type = OrderType.LIMIT
        self._time_between_stop_loss_orders = time_between_stop_loss_orders
        self._stop_loss_slippage_buffer = stop_loss_slippage_buffer
        self._grid_interval = grid_interval
        self._order_completed = False
        # self._grid_interval = Decimal('0.002')
        # self._grid_interval = get_grid_interval(price_floor, price_ceiling, order_levels)

    # def get_grid_interval(pfloor, pceil, levels):
        # grid_interval = Decimal('0')
        # last_step = pfloor
        # for level in range(1, levels + 1):
        #         next_step = pfloor + (
        #                 level * (pceil - pfloor) / levels
        #         )
        #         grid_interval = grid_interval + (next_step - last_step) / last_step
        #         last_step = next_step
        #
        # grid_interval = grid_interval / levels
        # return grid_interval

    @property
    def price_floor(self) -> Decimal:
        return self._price_floor

    @price_floor.setter
    def price_floor(self, value: Decimal):
        self._price_floor = value

    def get_price_type(self, price_type_str: str) -> PriceType:
        if price_type_str == "mid_price":
            return PriceType.MidPrice
        elif price_type_str == "best_bid":
            return PriceType.BestBid
        elif price_type_str == "best_ask":
            return PriceType.BestAsk
        elif price_type_str == "last_price":
            return PriceType.LastTrade
        elif price_type_str == 'last_own_trade_price':
            return PriceType.LastOwnTrade
        elif price_type_str == "custom":
            return PriceType.Custom
        else:
            raise ValueError(f"Unrecognized price type string {price_type_str}.")

    def grid_price(self, level: int):
        return int(self._price_floor * pow(1 + self._interval, level - self._order_levels / 2))

    # After initializing the required variables, we define the tick method.
    # The tick method is the entry point for the strategy.
    def tick(self, timestamp: float):
        # self.logger().info(f"ceiling {self._price_ceiling}")
        self.logger().info(f"floor {self._price_floor}")
        # self.logger().info(f"levels {self._order_levels}")
        # self.logger().info(f"interval {self._grid_interval}")
        if not self._all_markets_ready:
            self._all_markets_ready = self._market_info.market.ready
            if not self._all_markets_ready:
                self.logger().warning(f"{self._market_info.market.name} is not ready. Please wait...")
                return
            else:
                self.logger().warning(f"{self._market_info.market.name} is ready. Trading started")

        if not self._order_completed:
            # The get_mid_price method gets the mid price of the coin and
            # stores it. This method is derived from the MarketTradingPairTuple class.
            mid_price = self._market_info.get_mid_price()

            # The buy_with_specific_market method executes the trade for you. This
            # method is derived from the Strategy_base class.
            order_id = self.buy_with_specific_market(
                self._market_info,  # market_trading_pair_tuple
                Decimal("0.01"),   # amount
                OrderType.LIMIT,    # order_type
                mid_price           # price
            )
            self.logger().info(f"Submitted limit buy order {order_id}")
            self._order_completed = True

    # Emit a log message when the order completes
    def did_complete_buy_order(self, order_completed_event):
        self.logger().info(f"Your limit buy order {order_completed_event.order_id} has been executed")
        self.logger().info(order_completed_event)
