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
Bitbank adapter custom types.
"""

from enum import Enum, auto
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


class BitbankOrderStatus(Enum):
    """Bitbank order status enumeration."""
    
    UNFILLED = auto()
    PARTIALLY_FILLED = auto()
    FULLY_FILLED = auto()
    CANCELED_UNFILLED = auto()
    CANCELED_PARTIALLY_FILLED = auto()
    
    @classmethod
    def from_str(cls, value: str) -> "BitbankOrderStatus":
        """Parse from string value."""
        mapping = {
            "UNFILLED": cls.UNFILLED,
            "PARTIALLY_FILLED": cls.PARTIALLY_FILLED,
            "FULLY_FILLED": cls.FULLY_FILLED,
            "CANCELED_UNFILLED": cls.CANCELED_UNFILLED,
            "CANCELED_PARTIALLY_FILLED": cls.CANCELED_PARTIALLY_FILLED,
        }
        return mapping.get(value.upper(), cls.UNFILLED)


class BitbankOrderSide(Enum):
    """Bitbank order side enumeration."""
    
    BUY = "buy"
    SELL = "sell"
    
    @classmethod
    def from_str(cls, value: str) -> "BitbankOrderSide":
        """Parse from string value."""
        return cls.BUY if value.lower() == "buy" else cls.SELL


class BitbankOrderType(Enum):
    """Bitbank order type enumeration."""
    
    LIMIT = "limit"
    MARKET = "market"
    STOP_LIMIT = "stop_limit"
    
    @classmethod
    def from_str(cls, value: str) -> "BitbankOrderType":
        """Parse from string value."""
        mapping = {
            "limit": cls.LIMIT,
            "market": cls.MARKET,
            "stop_limit": cls.STOP_LIMIT,
        }
        return mapping.get(value.lower(), cls.LIMIT)


@dataclass
class BitbankOrderInfo:
    """Bitbank order information."""
    
    order_id: int
    pair: str
    side: BitbankOrderSide
    order_type: BitbankOrderType
    price: Optional[Decimal]
    start_amount: Decimal
    remaining_amount: Decimal
    executed_amount: Decimal
    average_price: Optional[Decimal]
    status: BitbankOrderStatus
    ordered_at: int  # Unix timestamp in milliseconds
    
    @property
    def is_open(self) -> bool:
        """Check if order is still open."""
        return self.status in (
            BitbankOrderStatus.UNFILLED,
            BitbankOrderStatus.PARTIALLY_FILLED,
        )
    
    @property
    def is_filled(self) -> bool:
        """Check if order is fully filled."""
        return self.status == BitbankOrderStatus.FULLY_FILLED
    
    @property
    def is_canceled(self) -> bool:
        """Check if order was canceled."""
        return self.status in (
            BitbankOrderStatus.CANCELED_UNFILLED,
            BitbankOrderStatus.CANCELED_PARTIALLY_FILLED,
        )


@dataclass
class BitbankAsset:
    """Bitbank asset balance information."""
    
    asset: str
    free_amount: Decimal
    locked_amount: Decimal
    
    @property
    def total(self) -> Decimal:
        """Get total amount (free + locked)."""
        return self.free_amount + self.locked_amount


@dataclass
class BitbankTrade:
    """Bitbank trade (fill) information."""
    
    trade_id: int
    order_id: int
    pair: str
    side: BitbankOrderSide
    price: Decimal
    amount: Decimal
    fee_amount_base: Decimal
    fee_amount_quote: Decimal
    executed_at: int  # Unix timestamp in milliseconds
    
    @property
    def value(self) -> Decimal:
        """Get trade value (price * amount)."""
        return self.price * self.amount
