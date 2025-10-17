import time
from typing import List, Dict, Optional, Tuple
from decimal import Decimal
from datetime import datetime
import logging
import asyncio
from collections import deque
from .order_types import Order, OrderSide, OrderType, OrderStatus, Trade
from .order_book import OrderBook
from engine.performance import PerformanceMonitor
from engine.persistence import PersistenceManager, StateRecoveryManager
import uuid

logger = logging.getLogger(__name__)

class MatchingEngine:
    """
    Ultra high-performance matching engine optimized for 1000+ orders/sec
    Key optimizations:
    - Fine-grained locking (symbol-level only)
    - Batched persistence (off critical path)
    - Batched broadcasts with debouncing
    - Minimal async overhead
    - Cached BBO calculations
    """
    def __init__(self, symbol: str, maker_fee: Decimal = Decimal("0.001"),
                 taker_fee: Decimal = Decimal("0.002")):
        self.symbol = symbol
        self.order_book = OrderBook(symbol)
        self.trades: deque = deque(maxlen=10000)
        self.maker_fee = maker_fee
        self.taker_fee = taker_fee
        self.trade_subscribers = []
        self.market_data_subscribers = []
        
        # Fine-grained locking - only protects order book modifications
        self._book_lock = asyncio.Lock()
        
        # Batched persistence queues (off critical path)
        self._order_queue = asyncio.Queue(maxsize=10000)
        self._trade_queue = asyncio.Queue(maxsize=10000)
        
        # Broadcast batching
        self._pending_trades = []
        self._last_broadcast = time.time()
        self._broadcast_interval = 0.005  # 5ms batching window
        self._bbo_dirty = False
        self._cached_bbo = None
        
        self.persistence = PersistenceManager(f"{self.symbol.lower()}_engine.db")
        self.state_recovery = StateRecoveryManager(self.persistence)
        self.perf = PerformanceMonitor()
        self._bg_started = False
        self._md_throttle = 0.05  # 50ms throttle
        self._last_md_broadcast = 0


    async def _broadcast_market_data(self):
        """Send batched market data - FIXED VERSION"""
        now = time.time()
        if now - self._last_md_broadcast < self._md_throttle:
            return
        self._last_md_broadcast = now

        if not self._bbo_dirty:
            return

        bbo = self.order_book.get_bbo()
        depth = self.order_book.get_depth()
        
        payload = {
            "type": "market_data",
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": self.symbol,  # ADD THIS - client needs symbol
            "bbo": bbo,
            "depth": depth,
        }
        
        # Broadcast to all subscribers
        for sub in list(self.market_data_subscribers):
            try:
                await sub(payload)
            except Exception as e:
                logger.error(f"Error broadcasting market data: {e}")
        
        self._bbo_dirty = False  # IMPORTANT: Mark as clean after broadcast



    async def start(self) -> None:
        """Start background tasks"""
        if self._bg_started:
            return
        self._bg_started = True
        
        # Recovery
        asyncio.create_task(self.state_recovery.recover_state(self))
        
        # Background workers (off critical path)
        asyncio.create_task(self._persistence_worker())
        asyncio.create_task(self._broadcast_worker())
        asyncio.create_task(self._periodic_snapshot())

    async def _persistence_worker(self):
        """Batched persistence writer - processes queues in background"""
        batch_size = 100
        batch_interval = 0.1  # 100ms
        
        orders_batch = []
        trades_batch = []
        last_flush = time.time()
        
        while True:
            try:
                # Collect orders
                while len(orders_batch) < batch_size:
                    try:
                        order = self._order_queue.get_nowait()
                        orders_batch.append(order)
                    except asyncio.QueueEmpty:
                        break
                
                # Collect trades
                while len(trades_batch) < batch_size:
                    try:
                        trade = self._trade_queue.get_nowait()
                        trades_batch.append(trade)
                    except asyncio.QueueEmpty:
                        break
                
                # Flush if batch full or time expired
                now = time.time()
                should_flush = (len(orders_batch) >= batch_size or 
                               len(trades_batch) >= batch_size or 
                               (now - last_flush) >= batch_interval)
                
                if should_flush and (orders_batch or trades_batch):
                    # Batch write to DB
                    if orders_batch:
                        await self.persistence.save_orders_batch(orders_batch)
                        orders_batch.clear()
                    if trades_batch:
                        await self.persistence.save_trades_batch(trades_batch)
                        trades_batch.clear()
                    last_flush = now
                else:
                    await asyncio.sleep(0.001)  # 1ms sleep
                    
            except Exception as e:
                logger.error(f"Persistence worker error: {e}")
                await asyncio.sleep(0.1)

    async def _broadcast_worker(self):
        """Batched broadcast worker - debounces market data updates"""
        while True:
            try:
                await asyncio.sleep(self._broadcast_interval)
                
                # Batch trade broadcasts
                if self._pending_trades:
                    trades_to_send = self._pending_trades[:]
                    self._pending_trades.clear()
                    for trade in trades_to_send:
                        await self._send_trade(trade)
                
                # Market data broadcast (only if BBO changed)
                if self._bbo_dirty:
                    await self._send_market_data()
                    self._bbo_dirty = False
                    
            except Exception as e:
                logger.error(f"Broadcast worker error: {e}")

    async def _periodic_snapshot(self):
        """Snapshot every 60s"""
        while True:
            try:
                await asyncio.sleep(60)
                await self.persistence.save_orderbook_snapshot(self.symbol, self.order_book)
                logger.info(f"Snapshot saved for {self.symbol}")
            except Exception as e:
                logger.error(f"Snapshot failed: {e}")

    async def submit_order(self, order: Order) -> Tuple[bool, str, List[Trade]]:
        """
        Optimized order submission with minimal locking
        """
        start_ts = time.perf_counter()
        
        # Fast validation (no lock needed)
        ok, msg, _ = self._validate_order(order)
        if not ok:
            self.perf.record_order_latency((time.perf_counter() - start_ts) * 1000.0)
            return (False, msg, [])

        # Critical section - only lock during book modification
        async with self._book_lock:
            trades: List[Trade] = []
            
            if order.order_type == OrderType.MARKET:
                trades = self._match_market_order_sync(order)
            elif order.order_type == OrderType.LIMIT:
                trades = self._match_limit_order_sync(order)
            elif order.order_type == OrderType.IOC:
                trades = self._match_ioc_order_sync(order)
            elif order.order_type == OrderType.FOK:
                trades = self._match_fok_order_sync(order)
            else:
                return (False, f"Unsupported order type: {order.order_type}", [])
            
            # Mark BBO as dirty if we have trades
            if trades:
                self._bbo_dirty = True
                self._cached_bbo = None
        
        # Post-processing (outside lock)
        # Queue for batched persistence (non-blocking)
        try:
            self._order_queue.put_nowait(order)
            for trade in trades:
                self._trade_queue.put_nowait(trade)
                self._pending_trades.append(trade)
        except asyncio.QueueFull:
            logger.warning("Persistence queue full, dropping writes")
        
        # Record latency
        self.perf.record_order_latency((time.perf_counter() - start_ts) * 1000.0)
        return (True, "Order processed successfully", trades)

    def _validate_order(self, order: Order) -> Tuple[bool, str, List[Trade]]:
        """Fast inline validation"""
        if order.quantity <= 0:
            return (False, "Invalid quantity", [])
        if order.order_type in [OrderType.LIMIT] and order.price is None:
            return (False, "Price required for limit orders", [])
        if order.price is not None and order.price <= 0:
            return (False, "Invalid price", [])
        return (True, "Valid", [])

    async def cancel_order(self, order_id: str):
        """Cancel with minimal locking"""
        async with self._book_lock:
            order = self.order_book.cancel_order(order_id)
            if order:
                order.status = OrderStatus.CANCELLED
                self._bbo_dirty = True
                self._cached_bbo = None
        
        if order:
            self._order_queue.put_nowait(order)
            return True, order
        return False, None

    # Synchronous matching methods (called within lock)
    def _match_market_order_sync(self, order: Order) -> List[Trade]:
        """Market order matching - synchronous for speed"""
        trades: List[Trade] = []
        remaining = order.quantity

        if order.side == OrderSide.BUY:
            while remaining > 0 and self.order_book.ask_side.price_levels:
                best_price = self.order_book.ask_side.get_best_price()
                if best_price is None:
                    break
                level = self.order_book.ask_side.price_levels.get(best_price)
                if not level:
                    break

                for resting_order in list(level.orders):
                    if remaining <= 0:
                        break

                    fill_qty = min(remaining, resting_order.remaining_quantity)
                    trade = self._create_trade_fast(best_price, fill_qty, resting_order, order)
                    trades.append(trade)

                    remaining -= fill_qty
                    order.filled_quantity += fill_qty
                    resting_order.filled_quantity += fill_qty

                    if resting_order.remaining_quantity == 0:
                        resting_order.status = OrderStatus.FILLED
                        self.order_book.remove_filled(resting_order.order_id)
                        self._order_queue.put_nowait(resting_order)
                    else:
                        resting_order.status = OrderStatus.PARTIALLY_FILLED
                        level.update_quantity(resting_order.order_id, fill_qty)
                        self._order_queue.put_nowait(resting_order)
        else:
            while remaining > 0 and self.order_book.bid_side.price_levels:
                best_price = self.order_book.bid_side.get_best_price()
                if best_price is None:
                    break
                level = self.order_book.bid_side.price_levels.get(best_price)
                if not level:
                    break

                for resting_order in list(level.orders):
                    if remaining <= 0:
                        break

                    fill_qty = min(remaining, resting_order.remaining_quantity)
                    trade = self._create_trade_fast(best_price, fill_qty, resting_order, order)
                    trades.append(trade)

                    remaining -= fill_qty
                    order.filled_quantity += fill_qty
                    resting_order.filled_quantity += fill_qty

                    if resting_order.remaining_quantity == 0:
                        resting_order.status = OrderStatus.FILLED
                        self.order_book.remove_filled(resting_order.order_id)
                        self._order_queue.put_nowait(resting_order)
                    else:
                        resting_order.status = OrderStatus.PARTIALLY_FILLED
                        level.update_quantity(resting_order.order_id, fill_qty)
                        self._order_queue.put_nowait(resting_order)

        order.status = (OrderStatus.FILLED if order.filled_quantity == order.quantity
                       else OrderStatus.PARTIALLY_FILLED if order.filled_quantity > 0
                       else OrderStatus.PENDING)
        
        return trades

    def _match_limit_order_sync(self, order: Order) -> List[Trade]:
        """Limit order matching - synchronous"""
        trades: List[Trade] = []
        remaining = order.quantity

        if order.side == OrderSide.BUY:
            best_ask = self.order_book.get_best_ask()
            if best_ask and order.price >= best_ask[0]:
                while remaining > 0 and self.order_book.ask_side.price_levels:
                    best_price = self.order_book.ask_side.get_best_price()
                    if best_price is None or best_price > order.price:
                        break
                    level = self.order_book.ask_side.price_levels.get(best_price)
                    if not level:
                        break

                    for resting_order in list(level.orders):
                        if remaining <= 0:
                            break

                        fill_qty = min(remaining, resting_order.remaining_quantity)
                        trade = self._create_trade_fast(best_price, fill_qty, resting_order, order)
                        trades.append(trade)

                        remaining -= fill_qty
                        order.filled_quantity += fill_qty
                        resting_order.filled_quantity += fill_qty

                        if resting_order.remaining_quantity == 0:
                            resting_order.status = OrderStatus.FILLED
                            self.order_book.remove_filled(resting_order.order_id)
                            self._order_queue.put_nowait(resting_order)
                        else:
                            resting_order.status = OrderStatus.PARTIALLY_FILLED
                            level.update_quantity(resting_order.order_id, fill_qty)
                            self._order_queue.put_nowait(resting_order)
        else:
            best_bid = self.order_book.get_best_bid()
            if best_bid and order.price <= best_bid[0]:
                while remaining > 0 and self.order_book.bid_side.price_levels:
                    best_price = self.order_book.bid_side.get_best_price()
                    if best_price is None or best_price < order.price:
                        break
                    level = self.order_book.bid_side.price_levels.get(best_price)
                    if not level:
                        break

                    for resting_order in list(level.orders):
                        if remaining <= 0:
                            break

                        fill_qty = min(remaining, resting_order.remaining_quantity)
                        trade = self._create_trade_fast(best_price, fill_qty, resting_order, order)
                        trades.append(trade)

                        remaining -= fill_qty
                        order.filled_quantity += fill_qty
                        resting_order.filled_quantity += fill_qty

                        if resting_order.remaining_quantity == 0:
                            resting_order.status = OrderStatus.FILLED
                            self.order_book.remove_filled(resting_order.order_id)
                            self._order_queue.put_nowait(resting_order)
                        else:
                            resting_order.status = OrderStatus.PARTIALLY_FILLED
                            level.update_quantity(resting_order.order_id, fill_qty)
                            self._order_queue.put_nowait(resting_order)

        if remaining > 0:
            order.status = OrderStatus.PARTIALLY_FILLED if trades else OrderStatus.PENDING
            self.order_book.add_order(order)
            self._bbo_dirty = True
            self._cached_bbo = None
        else:
            order.status = OrderStatus.FILLED
        
        return trades

    def _match_ioc_order_sync(self, order: Order) -> List[Trade]:
        """IOC matching"""
        if order.price is None:
            trades = self._match_market_order_sync(order)
        else:
            trades = self._match_limit_constrained_sync(order)
        
        order.status = (OrderStatus.FILLED if order.remaining_quantity == 0
                       else OrderStatus.PARTIALLY_FILLED if trades
                       else OrderStatus.CANCELLED)
        return trades

    def _match_limit_constrained_sync(self, order: Order) -> List[Trade]:
        """Price-constrained matching for IOC"""
        trades: List[Trade] = []
        remaining = order.quantity

        if order.side == OrderSide.BUY:
            while remaining > 0:
                best_price = self.order_book.ask_side.get_best_price()
                if best_price is None or best_price > order.price:
                    break
                level = self.order_book.ask_side.price_levels.get(best_price)
                for resting in list(level.orders):
                    if remaining <= 0:
                        break
                    fq = min(remaining, resting.remaining_quantity)
                    trades.append(self._create_trade_fast(best_price, fq, resting, order))
                    remaining -= fq
                    order.filled_quantity += fq
                    resting.filled_quantity += fq
                    if resting.remaining_quantity == 0:
                        resting.status = OrderStatus.FILLED
                        self.order_book.remove_filled(resting.order_id)
                    else:
                        resting.status = OrderStatus.PARTIALLY_FILLED
                        level.update_quantity(resting.order_id, fq)
                if level.empty():
                    self.order_book.ask_side.prune_empty_levels()
        else:
            while remaining > 0:
                best_price = self.order_book.bid_side.get_best_price()
                if best_price is None or best_price < order.price:
                    break
                level = self.order_book.bid_side.price_levels.get(best_price)
                for resting in list(level.orders):
                    if remaining <= 0:
                        break
                    fq = min(remaining, resting.remaining_quantity)
                    trades.append(self._create_trade_fast(best_price, fq, resting, order))
                    remaining -= fq
                    order.filled_quantity += fq
                    resting.filled_quantity += fq
                    if resting.remaining_quantity == 0:
                        resting.status = OrderStatus.FILLED
                        self.order_book.remove_filled(resting.order_id)
                    else:
                        resting.status = OrderStatus.PARTIALLY_FILLED
                        level.update_quantity(resting.order_id, fq)
                if level.empty():
                    self.order_book.bid_side.prune_empty_levels()
        
        return trades

    def _match_fok_order_sync(self, order: Order) -> List[Trade]:
        """FOK matching: only execute if the full quantity can be filled at or better than the limit price.
        Never rest and never trade through the limit."""
        # 1) Pre-validate full fill at/better than limit
        if not self._check_can_fill_completely(order):
            order.status = OrderStatus.CANCELLED
            return []

        # 2) Execute with price constraint (NOT market!)
        #    This guarantees we never hit worse prices than the limit.
        trades = (self._match_limit_constrained_sync(order)
                if order.price is not None
                else self._match_market_order_sync(order))  # only true FOK market

        # 3) Safety: if anything prevented a full fill, cancel (shouldn’t happen under the lock)
        if order.remaining_quantity > 0:
            # If you want to be extra strict, you could roll back trades here,
            # but given the book lock + precheck this path shouldn’t be hit.
            order.status = OrderStatus.CANCELLED
            return []

        order.status = OrderStatus.FILLED
        return trades

    def _check_can_fill_completely(self, order: Order) -> bool:
        total = Decimal("0")
        if order.side == OrderSide.BUY:
            for price in sorted(self.order_book.ask_side.price_levels.keys()):
                if order.price is not None and price > order.price and order.order_type != OrderType.MARKET:
                    break
                total += self.order_book.ask_side.price_levels[price].total_quantity
                if total >= order.quantity:
                    return True
        else:
            for price in sorted(self.order_book.bid_side.price_levels.keys(), reverse=True):
                if order.price is not None and price < order.price and order.order_type != OrderType.MARKET:
                    break
                total += self.order_book.bid_side.price_levels[price].total_quantity
                if total >= order.quantity:
                    return True
        return False


    def _create_trade_fast(self, price: Decimal, quantity: Decimal,
                          maker_order: Order, taker_order: Order) -> Trade:
        """Optimized trade creation - minimal overhead"""
        trade = Trade(
            symbol=self.symbol,
            price=price,
            quantity=quantity,
            aggressor_side=taker_order.side,
            maker_order_id=maker_order.order_id,
            taker_order_id=taker_order.order_id,
            timestamp=datetime.utcnow(),
            maker_fee=quantity * price * self.maker_fee,
            taker_fee=quantity * price * self.taker_fee,
        )
        self.trades.append(trade)
        return trade

    async def _send_market_data(self):
        """Send batched market data"""
        bbo = self.order_book.get_bbo()
        depth = self.order_book.get_depth()
        payload = {
            "type": "market_data",
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": self.symbol,
            "bbo": bbo,
            "depth": depth,
        }
        for sub in list(self.market_data_subscribers):
            try:
                await sub(payload)
            except Exception as e:
                logger.error(f"Error broadcasting market data: {e}")

    async def _send_trade(self, trade: Trade):
        """Send individual trade - FIXED VERSION"""
        payload = {
            "type": "trade",
            "timestamp": trade.timestamp.isoformat(),
            "symbol": trade.symbol,  # Already present but verify
            "trade_id": trade.trade_id,
            "price": str(trade.price),
            "quantity": str(trade.quantity),
            "aggressor_side": trade.aggressor_side.value,
            "maker_order_id": trade.maker_order_id,
            "taker_order_id": trade.taker_order_id,
        }
        
        for sub in list(self.trade_subscribers):
            try:
                await sub(payload)
            except Exception as e:
                logger.error(f"Error broadcasting trade: {e}")

    def subscribe_market_data(self, callback):
        self.market_data_subscribers.append(callback)

    def subscribe_trades(self, callback):
        self.trade_subscribers.append(callback)

    def get_performance_metrics(self):
        return self.perf.get_metrics()

    def get_performance_report(self) -> str:
        return self.perf.generate_report()