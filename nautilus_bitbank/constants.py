# -------------------------------------------------------------------------------------------------
#  Copyright (C) 2024 Penguinworks. All rights reserved.
#
#  Licensed under the GNU Lesser General Public License Version 3.0 (the "License");
#  You may not use this file except in compliance with the License.
#  You may obtain a copy of the License at https://www.gnu.org/licenses/lgpl-3.0.en.html
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
# -------------------------------------------------------------------------------------------------
"""
Bitbank adapter constants.
"""

from nautilus_trader.model.identifiers import Venue


# Venue identifier for Bitbank
BITBANK_VENUE = Venue("BITBANK")

# API endpoints
BITBANK_REST_URL = "https://api.bitbank.cc"
BITBANK_PUBLIC_REST_URL = "https://public.bitbank.cc"
BITBANK_WS_URL = "wss://stream.bitbank.cc"

# PubNub settings
BITBANK_PUBNUB_SUBSCRIBE_KEY = "sub-c-e12e9174-dd60-11e6-806b-02ee2ddab7fe"

# Rate limits (requests per minute)
BITBANK_PUBLIC_RATE_LIMIT = 100  # Public API
BITBANK_PRIVATE_RATE_LIMIT = 10  # Private API (per endpoint)

# Order status mappings
ORDER_STATUS_MAP = {
    "UNFILLED": "OPEN",
    "PARTIALLY_FILLED": "PARTIALLY_FILLED",
    "FULLY_FILLED": "FILLED",
    "CANCELED_UNFILLED": "CANCELED",
    "CANCELED_PARTIALLY_FILLED": "CANCELED",
}

# Order side mappings
ORDER_SIDE_MAP = {
    "buy": "BUY",
    "sell": "SELL",
}

# Order type mappings
ORDER_TYPE_MAP = {
    "limit": "LIMIT",
    "market": "MARKET",
    "stop_limit": "STOP_LIMIT",
}

# Supported trading pairs (commonly traded)
POPULAR_PAIRS = [
    "btc_jpy",
    "eth_jpy",
    "xrp_jpy",
    "ltc_jpy",
    "mona_jpy",
    "bcc_jpy",
    "xlm_jpy",
    "qtum_jpy",
    "bat_jpy",
    "omg_jpy",
    "xym_jpy",
    "link_jpy",
    "mkr_jpy",
    "boba_jpy",
    "enj_jpy",
    "matic_jpy",
    "dot_jpy",
    "doge_jpy",
    "astr_jpy",
    "ada_jpy",
    "sol_jpy",
]

# Error codes
ERROR_CODES = {
    10000: "URL not found",
    10001: "Rate limit exceeded",
    10002: "Invalid API key",
    10003: "Invalid API nonce",
    10005: "Invalid signature",
    10007: "Timed out",
    10008: "Withdrawal disabled",
    20001: "Authentication failed",
    20002: "Invalid pair",
    20003: "Invalid amount",
    20004: "Invalid price",
    20005: "Invalid order ID",
    20012: "Unsupported order type",
    20013: "Market orders are forbidden",
    30001: "Insufficient balance",
    30003: "Order not found",
    30004: "Cannot cancel filled order",
    40001: "Pair is paused",
    60001: "Insufficient funds",
    60003: "Exceed maximum amount",
    60004: "Exceed maximum order value",
}
