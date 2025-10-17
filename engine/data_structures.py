# engine/data_structures.py
from typing import List, Dict, Optional
from decimal import Decimal
import heapq
from .order_types import Order


class PriceLevel:
    """Represents a single price level (FIFO queue of resting orders)."""

    def __init__(self, price: Decimal):
        self.price: Decimal = Decimal(price)
        self.orders: List[Order] = []
        self.total_quantity: Decimal = Decimal("0")

    def add_order(self, order: Order) -> None:
        """Append to FIFO and increase aggregate by the order's remaining qty."""
        self.orders.append(order)
        self.total_quantity += order.remaining_quantity

    def remove_order(self, order_id: str) -> bool:
        """Remove an order from this level; update aggregate accordingly."""
        for i, order in enumerate(self.orders):
            if order.order_id == order_id:
                self.total_quantity -= order.remaining_quantity
                if self.total_quantity < 0:
                    self.total_quantity = Decimal("0")
                self.orders.pop(i)
                return True
        return False

    def update_quantity(self, order_id: str, filled_quantity: Decimal) -> None:
        """
        Adjust the level aggregate after a partial fill/cancel of a specific order.
        NOTE: The caller is responsible for incrementing order.filled_quantity;
              this method only fixes the level aggregate and removes fully-filled orders.
        """
        fq = Decimal(filled_quantity)
        if fq <= 0:
            return

        for idx, order in enumerate(self.orders):
            if order.order_id == order_id:
                self.total_quantity -= fq
                if self.total_quantity < 0:
                    self.total_quantity = Decimal("0")
                # If that order is now fully consumed, drop it from FIFO
                if order.remaining_quantity <= 0:
                    self.orders.pop(idx)
                break

    def empty(self) -> bool:
        """
        True if no displayed quantity remains at this level.
        We also reconcile total_quantity defensively if it's out of sync.
        """
        if self.total_quantity <= 0:
            # quick path
            return True

        agg = sum(o.remaining_quantity for o in self.orders)
        if agg != self.total_quantity:
            self.total_quantity = agg
        return self.total_quantity <= 0


class OrderBookSide:
    """
    One side (bid/ask) of the order book.

    - Bids: best is MAX price. We push -price to a min-heap.
    - Asks: best is MIN price. We push price directly to a min-heap.
    """

    def __init__(self, is_bid: bool):
        self.is_bid = is_bid
        self.price_levels: Dict[Decimal, PriceLevel] = {}
        self.price_heap: List[Decimal] = []   # stores price or -price
        self._price_set: set = set()          # actual prices present

    def _heap_key(self, price: Decimal) -> Decimal:
        price = Decimal(price)
        return -price if self.is_bid else price

    def _heap_to_price(self, key: Decimal) -> Decimal:
        key = Decimal(key)
        return -key if self.is_bid else key

    def _clean_heap(self) -> None:
        """Pop heap heads that no longer have a non-empty price level."""
        while self.price_heap:
            top_key = self.price_heap[0]
            price = self._heap_to_price(top_key)
            lvl = self.price_levels.get(price)
            if lvl is not None and not lvl.empty():
                return
            heapq.heappop(self.price_heap)
            self._price_set.discard(price)

    def prune_empty_levels(self) -> None:
        """Remove all empty levels and tidy the heap."""
        to_drop = [p for p, lvl in self.price_levels.items() if lvl.empty()]
        for p in to_drop:
            self.price_levels.pop(p, None)
            self._price_set.discard(p)
        self._clean_heap()

    def get_best_price(self) -> Optional[Decimal]:
        """Return best price on this side (or None if empty)."""
        self._clean_heap()
        if not self.price_heap:
            return None
        return self._heap_to_price(self.price_heap[0])

    def add_order(self, order: Order) -> None:
        """Insert order at its price level."""
        price = Decimal(order.price)
        lvl = self.price_levels.get(price)
        if lvl is None:
            lvl = PriceLevel(price)
            self.price_levels[price] = lvl
            if price not in self._price_set:
                heapq.heappush(self.price_heap, self._heap_key(price))
                self._price_set.add(price)
        lvl.add_order(order)

    def remove_order(self, order_id: str, price: Decimal) -> bool:
        """Remove a specific resting order; drop the level if it becomes empty."""
        price = Decimal(price)
        lvl = self.price_levels.get(price)
        if lvl is None:
            return False

        removed = lvl.remove_order(order_id)
        if removed and lvl.empty():
            del self.price_levels[price]
            self._price_set.discard(price)
            self._clean_heap()
        return removed
