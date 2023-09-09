import asyncio
import logging
from typing import Optional

import numpy as np
from dydx3.helpers.request_helpers import epoch_seconds_to_iso, iso_to_epoch_seconds

from hummingbot.core.network_iterator import NetworkStatus, safe_ensure_future
from hummingbot.core.web_assistant.connections.data_types import WSJSONRequest
from hummingbot.core.web_assistant.ws_assistant import WSAssistant
from hummingbot.data_feed.candles_feed.candles_base import CandlesBase
from hummingbot.data_feed.candles_feed.dydx_perpetual_candles import constants as CONSTANTS
from hummingbot.logger import HummingbotLogger


class DydxPerpetualCandles(CandlesBase):
    _logger: Optional[HummingbotLogger] = None

    @classmethod
    def logger(cls) -> HummingbotLogger:
        if cls._logger is None:
            cls._logger = logging.getLogger(__name__)
        return cls._logger

    def __init__(self, trading_pair: str, interval: str = "1m", max_records: int = 150):
        super().__init__(trading_pair, interval, max_records)

    @property
    def name(self):
        return f"dydx_perpetuals_{self._trading_pair}"

    @property
    def rest_url(self):
        return CONSTANTS.REST_URL

    @property
    def wss_url(self):
        return CONSTANTS.WSS_URL

    @property
    def health_check_url(self):
        return self.rest_url + CONSTANTS.HEALTH_CHECK_ENDPOINT

    @property
    def candles_url(self):
        return self.rest_url + CONSTANTS.CANDLES_ENDPOINT

    @property
    def rate_limits(self):
        return CONSTANTS.RATE_LIMITS

    @property
    def intervals(self):
        return CONSTANTS.INTERVALS

    async def check_network(self) -> NetworkStatus:
        rest_assistant = await self._api_factory.get_rest_assistant()
        await rest_assistant.execute_request(url=self.health_check_url,
                                             throttler_limit_id=CONSTANTS.HEALTH_CHECK_ENDPOINT)
        return NetworkStatus.CONNECTED

    def get_exchange_trading_pair(self, trading_pair):
        return trading_pair  # no need to change the pair format for dydx

    async def fetch_candles(self,
                            start_time: Optional[int] = None,
                            end_time: Optional[int] = None,
                            limit: Optional[int] = CONSTANTS.CANDLES_LIMIT):
        rest_assistant = await self._api_factory.get_rest_assistant()
        params = {"resolution": self.intervals[self.interval], "limit": limit}
        if start_time is not None:
            params["fromISO"] = epoch_seconds_to_iso(start_time)
        if end_time is not None:
            params["toISO"] = epoch_seconds_to_iso(end_time)
        candles = await rest_assistant.execute_request(url=self.candles_url + self._ex_trading_pair,
                                                       throttler_limit_id=CONSTANTS.CANDLES_ENDPOINT,
                                                       params=params)
        new_candles = []
        for i in candles["candles"]:
            timestamp_ms = iso_to_epoch_seconds(i["startedAt"])
            open = i["open"]
            high = i["high"]
            low = i["low"]
            close = i["close"]
            volume = i["baseTokenVolume"]
            quote_asset_volume = i["usdVolume"]
            n_trades = i["trades"]
            # no data field
            taker_buy_base_volume = 0
            taker_buy_quote_volume = 0
            new_candles.append([timestamp_ms, open, high, low, close, volume,
                                quote_asset_volume, n_trades, taker_buy_base_volume,
                                taker_buy_quote_volume])
        return np.array(new_candles).astype(float)

    async def fill_historical_candles(self):
        max_request_needed = (self._candles.maxlen // CONSTANTS.CANDLES_LIMIT) + 1
        requests_executed = 0
        while not self.is_ready:
            missing_records = self._candles.maxlen - len(self._candles)
            # print(missing_records)
            # print(self._candles)
            end_timestamp = self._candles[0][0]
            # print("fill_historical_candles")
            # print(self._candles)
            # print(end_timestamp)
            # print(str(missing_records) + " / " + str(self._candles.maxlen) + " miss")
            # print(str(len(self._candles)) + " / " + str(self._candles.maxlen) + " obs")
            # print(str(requests_executed) + " / " + str(max_request_needed) + " iter")
            try:
                if requests_executed < max_request_needed:
                    # we have to add one more since, the last row is not going to be included
                    candles = await self.fetch_candles(end_time=end_timestamp, limit=min(CONSTANTS.CANDLES_LIMIT, missing_records + 1))
                    # we are computing again the quantity of records again since the websocket process is able to
                    # modify the deque and if we extend it, the new observations are going to be dropped.
                    # print(str(len(candles)) + " new / " + str(missing_records + 1) + " req")
                    self._candles.extendleft(candles[0:(missing_records)][::1])
                    # print("merge for " + str(len(self._candles)) + " total")
                    # print(self._candles)
                    requests_executed += 1
                else:
                    self.logger().error(f"There is no data available for the quantity of "
                                        f"candles requested for {self.name}.")
                    raise
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().exception(
                    "Unexpected error occurred when getting historical klines. Retrying in 1 seconds...",
                )
                await self._sleep(1.0)

    """
    websocket candles not supported by dydx v3 api
    appears on roadmap for v4 but not released as at September 2023
    websocket processing would go in remaining code when supported
    instead rely on above query by filling new candles via REST
    """

    async def _subscribe_channels(self, ws: WSAssistant):
        """
        Subscribes to the market events through the provided websocket connection.
        uses market as websocket candles not supported by dydx v3 api
        :param ws: the websocket assistant used to connect to the exchange
        """
        try:
            payload = {
                "type": "subscribe",
                "channel": "v3_markets",
                "id": self._ex_trading_pair
            }
            subscribe_markets_request: WSJSONRequest = WSJSONRequest(payload = payload, is_auth_required = False)
            await ws.send(subscribe_markets_request)
            self.logger().info("Subscribed to public market...")
        except asyncio.CancelledError:
            raise
        except Exception:
            self.logger().error(
                "Unexpected error connecting to websocket...",
                exc_info = True
            )
            raise

    async def _process_websocket_messages(self, websocket_assistant: WSAssistant):
        """
        not used as websocket candles not supported by dydx v3 api
        """
        data = await self.fetch_candles(limit=1)

        timestamp = data[0][0]
        open = data[0][1]
        low = data[0][2]
        high = data[0][3]
        close = data[0][4]
        volume = data[0][5]
        quote_asset_volume = data[0][6]
        n_trades = data[0][7]
        taker_buy_base_volume = data[0][8]
        taker_buy_quote_volume = data[0][9]
        # print(self._candles)
        # print(data)
        print("start " + str(len(self._candles)))
        if len(self._candles) == 0:
            # self._candles.append(data)
            self._candles.append(np.array([timestamp, open, high, low, close, volume,
                                           quote_asset_volume, n_trades, taker_buy_base_volume,
                                           taker_buy_quote_volume]))
            # self._candles = np.concatenate((self._candles, data), axis=0)
            # print(self._candles)
            # self.logger().error(self._candles)
            safe_ensure_future(self.fill_historical_candles())
        elif timestamp > int(self._candles[-1][0]):
            self._candles.append(np.array([timestamp, open, high, low, close, volume,
                                           quote_asset_volume, n_trades, taker_buy_base_volume,
                                           taker_buy_quote_volume]))
        elif timestamp == int(self._candles[-1][0]):
            self._candles.pop()
            self._candles.append(np.array([timestamp, open, high, low, close, volume,
                                           quote_asset_volume, n_trades, taker_buy_base_volume,
                                           taker_buy_quote_volume]))
        print("stop " + str(len(self._candles)))
