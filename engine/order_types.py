from __future__ import annotations
from enum import Enum
from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime
from typing import Optional
import uuid


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    IOC = "ioc"           # Immediate-Or-Cancel
    FOK = "fok"           # Fill-Or-Kill
    STOP_LOSS = "stop_loss"
    STOP_LIMIT = "stop_limit"
    TAKE_PROFIT = "take_profit"


class OrderStatus(Enum):
    PENDING = "pending"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class Order:
    """Represents a trading order in the system."""
    order_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str = ""
    side: OrderSide = OrderSide.BUY
    order_type: OrderType = OrderType.LIMIT
    price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    quantity: Decimal = Decimal("0")
    filled_quantity: Decimal = Decimal("0")
    status: OrderStatus = OrderStatus.PENDING
    timestamp: datetime = field(default_factory=datetime.utcnow)
    user_id: Optional[str] = None

    @property
    def remaining_quantity(self) -> Decimal:
        return self.quantity - self.filled_quantity

    @property
    def is_marketable(self) -> bool:
        """True if order must execute immediately (no resting)."""
        return self.order_type in {OrderType.MARKET, OrderType.IOC, OrderType.FOK}

    def __lt__(self, other):
        """Price-time priority comparison (not used by the engine’s FIFO levels but harmless)."""
        if self.price != other.price:
            if self.side == OrderSide.BUY:
                return self.price > other.price  # Higher price first for buys
            else:
                return self.price < other.price  # Lower price first for sells
        return self.timestamp < other.timestamp


@dataclass
class Trade:
    """Represents an executed trade."""
    trade_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str = ""
    price: Decimal = Decimal("0")
    quantity: Decimal = Decimal("0")
    aggressor_side: OrderSide = OrderSide.BUY
    maker_order_id: str = ""
    taker_order_id: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    maker_fee: Decimal = Decimal("0")
    taker_fee: Decimal = Decimal("0")
