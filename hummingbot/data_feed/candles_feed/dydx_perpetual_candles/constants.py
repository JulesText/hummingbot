from bidict import bidict

from hummingbot.core.api_throttler.data_types import LinkedLimitWeightPair, RateLimit

API_VERSION = "v3"
REST_BASE_URL = "https://api.dydx.exchange"
REST_URL = "{}/{}".format(REST_BASE_URL, API_VERSION)

HEALTH_CHECK_ENDPOINT = "/time"

CANDLES_ENDPOINT = "/candles/"
CANDLES_LIMIT = 100  # max candles per request

WSS_URL = "wss://api.dydx.exchange/{}/ws".format(API_VERSION)

INTERVALS = bidict({
    "1m": "1MIN",
    "5m": "5MINS",
    "15m": "15MINS",
    "30m": "30MINS",
    "1h": "1HOUR",
    "4h": "4HOURS",
    "1d": "1DAY"
})

PUBLIC_ENDPOINT_LIMIT = "PublicPoints"

RATE_LIMITS = [
    RateLimit(PUBLIC_ENDPOINT_LIMIT, limit=175, time_interval=10),
    RateLimit(CANDLES_ENDPOINT, limit=175, time_interval=10, linked_limits=[LinkedLimitWeightPair(PUBLIC_ENDPOINT_LIMIT, 1)]),
    RateLimit(HEALTH_CHECK_ENDPOINT, limit=175, time_interval=10, linked_limits=[LinkedLimitWeightPair(PUBLIC_ENDPOINT_LIMIT, 1)])]
