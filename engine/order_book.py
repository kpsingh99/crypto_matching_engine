# engine/order_book.py
from typing import Dict, Optional, Tuple
from decimal import Decimal
import logging
from .order_types import Order, OrderSide, OrderStatus
from .data_structures import OrderBookSide

logger = logging.getLogger(__name__)


class OrderBook:
    """High-performance order book with strict price–time priority."""

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.bid_side = OrderBookSide(is_bid=True)
        self.ask_side = OrderBookSide(is_bid=False)
        self.orders: Dict[str, Order] = {}  # All orders by ID

    def add_order(self, order: Order, skip_existing: bool = False) -> bool:
        """Add a new order to the book.

        Args:
            order: Order object to add
            skip_existing: If True, quietly skip duplicate orders (used during recovery)
        """
        if order.order_id in self.orders:
            if skip_existing:
                logger.debug(f"Skipping duplicate order {order.order_id} during recovery")
                return False
            logger.error(f"Order {order.order_id} already exists")
            return False

        self.orders[order.order_id] = order

        if order.side == OrderSide.BUY:
            self.bid_side.add_order(order)
        else:
            self.ask_side.add_order(order)

        return True


    def cancel_order(self, order_id: str) -> Optional[Order]:
        """Cancel (or remove) an order by id."""
        order = self.orders.get(order_id)
        if order is None:
            return None

        if order.side == OrderSide.BUY:
            self.bid_side.remove_order(order_id, order.price)
        else:
            self.ask_side.remove_order(order_id, order.price)

        order.status = OrderStatus.CANCELLED
        self.orders.pop(order_id, None)
        return order
    
    def remove_filled(self, order_id: str) -> bool:
        """Remove an order that is already FILLED without changing status."""
        order = self.orders.get(order_id)
        if not order:
            return False
        side = self.bid_side if order.side == OrderSide.BUY else self.ask_side
        side.remove_order(order_id, order.price)
        self.orders.pop(order_id, None)
        return True


    def _best_from_side(self, side: OrderBookSide) -> Optional[Tuple[Decimal, Decimal]]:
        """Helper: return (price, agg_qty) for best non-empty level on a side."""
        best_price = side.get_best_price()
        if best_price is not None:
            lvl = side.price_levels.get(best_price)
            if lvl and not lvl.empty():
                return (best_price, lvl.total_quantity)
        return None

    def get_best_bid(self) -> Optional[Tuple[Decimal, Decimal]]:
        return self._best_from_side(self.bid_side)

    def get_best_ask(self) -> Optional[Tuple[Decimal, Decimal]]:
        return self._best_from_side(self.ask_side)

    def get_bbo(self) -> Dict:
        """Best Bid/Offer with spread as strings (safe for JSON)."""
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()
        return {
            "symbol": self.symbol,
            "best_bid": {"price": str(best_bid[0]), "quantity": str(best_bid[1])} if best_bid else None,
            "best_ask": {"price": str(best_ask[0]), "quantity": str(best_ask[1])} if best_ask else None,
            "spread": str(best_ask[0] - best_bid[0]) if best_bid and best_ask else None,
        }

    def get_depth(self, levels: int = 10) -> Dict:
        """
        Return top `levels` of depth for both sides, skipping empty levels.
        """
        bid_levels = []
        ask_levels = []

        # Bids: highest → lowest
        for price in sorted(self.bid_side.price_levels.keys(), reverse=True):
            lvl = self.bid_side.price_levels[price]
            if lvl.empty():
                continue
            bid_levels.append([str(price), str(lvl.total_quantity)])
            if len(bid_levels) >= levels:
                break

        # Asks: lowest → highest
        for price in sorted(self.ask_side.price_levels.keys()):
            lvl = self.ask_side.price_levels[price]
            if lvl.empty():
                continue
            ask_levels.append([str(price), str(lvl.total_quantity)])
            if len(ask_levels) >= levels:
                break

        return {
            "symbol": self.symbol,
            "bids": bid_levels,
            "asks": ask_levels,
        }
