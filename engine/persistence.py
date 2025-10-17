import json
import pickle
from datetime import datetime, timedelta
from typing import List, Optional
from decimal import Decimal
import asyncio
import aiosqlite
import logging
from .order_types import Order, Trade, OrderStatus, OrderSide, OrderType

logger = logging.getLogger(__name__)

class PersistenceManager:
    """
    High-performance async persistence with batched writes and WAL mode
    Optimized for 1000+ orders/sec throughput
    """
    
    def __init__(self, db_path: str = "matching_engine.db"):
        self.db_path = db_path
        self._conn = None
        self._write_lock = asyncio.Lock()
        self._initialized = False
    
    async def _get_connection(self) -> aiosqlite.Connection:
        """Get or create async database connection with optimizations"""
        if self._conn is None:
            self._conn = await aiosqlite.connect(
                self.db_path,
                isolation_level=None,  # Autocommit mode for better control
            )
            
            # CRITICAL: Enable WAL mode for concurrent reads/writes
            await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.execute("PRAGMA synchronous=NORMAL")  # Faster, still safe
            await self._conn.execute("PRAGMA cache_size=10000")  # 10MB cache
            await self._conn.execute("PRAGMA temp_store=MEMORY")  # Use RAM for temp
            await self._conn.execute("PRAGMA mmap_size=268435456")  # 256MB mmap
            await self._conn.execute("PRAGMA page_size=4096")  # Optimal page size
            await self._conn.execute("PRAGMA journal_size_limit=67108864")  # cap WAL at 64 MB
            await self._conn.execute("PRAGMA busy_timeout=2000")
            
            if not self._initialized:
                await self._initialize_database()
                self._initialized = True
        
        return self._conn
    
    async def _initialize_database(self):
        """Create database tables if they don't exist"""
        conn = await self._get_connection()
        
        # Create orders table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                order_type TEXT NOT NULL,
                price REAL,
                quantity REAL NOT NULL,
                filled_quantity REAL DEFAULT 0,
                status TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                user_id TEXT
            )
        """)
        
        # Create trades table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                trade_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                price REAL NOT NULL,
                quantity REAL NOT NULL,
                aggressor_side TEXT NOT NULL,
                maker_order_id TEXT NOT NULL,
                taker_order_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                maker_fee REAL,
                taker_fee REAL
            )
        """)
        
        # Create order book snapshot table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS orderbook_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                snapshot_data BLOB NOT NULL,
                timestamp TEXT NOT NULL
            )
        """)
        
        # Optimized indexes
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_symbol_status ON orders(symbol, status)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_timestamp ON orders(timestamp)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol_timestamp ON trades(symbol, timestamp)")
        
        await conn.commit()
        logger.info(f"Database initialized: {self.db_path}")
    
    def _serialize_order(self, order: Order) -> tuple:
        """Convert order to database row - inline for speed"""
        return (
            order.order_id,
            order.symbol,
            order.side.value,
            order.order_type.value,
            float(order.price) if order.price is not None else None,
            float(order.quantity),
            float(order.filled_quantity),
            order.status.value,
            order.timestamp.isoformat(),
            getattr(order, "user_id", None),
        )
    
    def _serialize_trade(self, trade: Trade) -> tuple:
        """Convert trade to database row - inline for speed"""
        return (
            trade.trade_id,
            trade.symbol,
            float(trade.price),
            float(trade.quantity),
            trade.aggressor_side.value,
            trade.maker_order_id,
            trade.taker_order_id,
            trade.timestamp.isoformat(),
            float(trade.maker_fee),
            float(trade.taker_fee),
        )
    
    async def save_order(self, order: Order):
        """Save single order (use save_orders_batch for better performance)"""
        await self.save_orders_batch([order])
    
    async def save_trade(self, trade: Trade):
        """Save single trade (use save_trades_batch for better performance)"""
        await self.save_trades_batch([trade])
    
    async def save_orders_batch(self, orders: List[Order]):
        """
        Batched order writes with single transaction
        Up to 100x faster than individual writes
        """
        if not orders:
            return
        
        try:
            conn = await self._get_connection()
            
            # Serialize all orders upfront (fast)
            order_rows = [self._serialize_order(o) for o in orders]
            
            # Single transaction for entire batch
            async with self._write_lock:
                await conn.execute("BEGIN IMMEDIATE")
                try:
                    await conn.executemany("""
                        INSERT OR REPLACE INTO orders 
                        (order_id, symbol, side, order_type, price, quantity, 
                         filled_quantity, status, timestamp, user_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, order_rows)
                    await conn.commit()
                    logger.debug(f"Persisted {len(orders)} orders")
                except Exception as e:
                    await conn.rollback()
                    logger.error(f"Order batch write failed: {e}")
                    raise
        
        except Exception as e:
            logger.error(f"Order persistence error: {e}")
    
    async def save_trades_batch(self, trades: List[Trade]):
        """
        Batched trade writes with single transaction
        """
        if not trades:
            return
        
        try:
            conn = await self._get_connection()
            
            # Serialize all trades upfront
            trade_rows = [self._serialize_trade(t) for t in trades]
            
            # Single transaction
            async with self._write_lock:
                await conn.execute("BEGIN IMMEDIATE")
                try:
                    await conn.executemany("""
                        INSERT OR REPLACE INTO trades 
                        (trade_id, symbol, price, quantity, aggressor_side,
                         maker_order_id, taker_order_id, timestamp, maker_fee, taker_fee)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, trade_rows)
                    await conn.commit()
                    logger.debug(f"Persisted {len(trades)} trades")
                except Exception as e:
                    await conn.rollback()
                    logger.error(f"Trade batch write failed: {e}")
                    raise
        
        except Exception as e:
            logger.error(f"Trade persistence error: {e}")
    
    async def save_orderbook_snapshot(self, symbol: str, order_book):
        """Save complete order book snapshot (for recovery)"""
        try:
            conn = await self._get_connection()
            
            # Pickle order book (fast serialization)
            snapshot_data = pickle.dumps(order_book)
            
            async with self._write_lock:
                await conn.execute("""
                    INSERT INTO orderbook_snapshots (symbol, snapshot_data, timestamp)
                    VALUES (?, ?, ?)
                """, (symbol, snapshot_data, datetime.utcnow().isoformat()))
                await conn.commit()
            
            # Cleanup old snapshots (keep last 10)
            await conn.execute("""
                DELETE FROM orderbook_snapshots 
                WHERE symbol = ? AND id NOT IN (
                    SELECT id FROM orderbook_snapshots 
                    WHERE symbol = ? 
                    ORDER BY timestamp DESC 
                    LIMIT 10
                )
            """, (symbol, symbol))
            await conn.commit()
            
            logger.info(f"Saved snapshot for {symbol}")
        
        except Exception as e:
            logger.error(f"Snapshot save failed: {e}")
    
    async def load_orderbook_snapshot(self, symbol: str):
        """Load most recent order book snapshot + timestamp"""
        try:
            conn = await self._get_connection()
            
            async with conn.execute("""
                SELECT snapshot_data, timestamp 
                FROM orderbook_snapshots 
                WHERE symbol = ? 
                ORDER BY timestamp DESC 
                LIMIT 1
            """, (symbol,)) as cursor:
                result = await cursor.fetchone()
                
                if result:
                    snapshot = pickle.loads(result[0])
                    snap_ts = datetime.fromisoformat(result[1])
                    logger.info(f"Loaded snapshot for {symbol} from {snap_ts}")
                    return snapshot, snap_ts
                
                return None, None
        
        except Exception as e:
            logger.error(f"Snapshot load failed: {e}")
            return None, None
    
    async def get_orders_by_status(self, status: str) -> List[dict]:
        """Get orders by status"""
        conn = await self._get_connection()
        
        async with conn.execute(
            "SELECT * FROM orders WHERE status = ?", 
            (status,)
        ) as cursor:
            rows = await cursor.fetchall()
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in rows]
    
    async def get_trade_history(self, symbol: str, limit: int = 100) -> List[dict]:
        """Get recent trade history"""
        conn = await self._get_connection()
        
        async with conn.execute("""
            SELECT * FROM trades 
            WHERE symbol = ? 
            ORDER BY timestamp DESC 
            LIMIT ?
        """, (symbol, limit)) as cursor:
            rows = await cursor.fetchall()
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in rows]
    
    async def cleanup_old_data(self, days_to_keep: int = 30):
        """Clean up old data from database (run periodically)"""
        try:
            conn = await self._get_connection()
            cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)
            cutoff_str = cutoff_date.isoformat()
            
            async with self._write_lock:
                # Delete old filled/cancelled orders
                await conn.execute("""
                    DELETE FROM orders 
                    WHERE status IN ('filled', 'cancelled') 
                    AND timestamp < ?
                """, (cutoff_str,))
                
                # Delete old trades
                await conn.execute("""
                    DELETE FROM trades 
                    WHERE timestamp < ?
                """, (cutoff_str,))
                
                # Delete old snapshots
                await conn.execute("""
                    DELETE FROM orderbook_snapshots 
                    WHERE timestamp < ?
                """, (cutoff_str,))
                
                await conn.commit()
            
            logger.info(f"Cleaned up data older than {days_to_keep} days")
        
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
    
    async def vacuum_database(self):
        """Optimize database (run during low traffic)"""
        try:
            conn = await self._get_connection()
            await conn.execute("VACUUM")
            logger.info("Database vacuumed successfully")
        except Exception as e:
            logger.error(f"Vacuum failed: {e}")
    
    async def close(self):
        """Close database connection gracefully"""
        if self._conn:
            await self._conn.close()
            self._conn = None
            logger.info("Database connection closed")


class StateRecoveryManager:
    """
    Handles recovery of matching engine state after restart
    Optimized for fast startup with minimal blocking
    """
    
    def __init__(self, persistence_manager: PersistenceManager):
        self.persistence = persistence_manager
    
    async def recover_state(self, matching_engine):
        """
        Fast recovery with snapshot + incremental replay
        """
        try:
            symbol = matching_engine.symbol
            logger.info(f"Starting recovery for {symbol}")
            
            # 1) Load snapshot (if any)
            snapshot, snap_ts = await self.persistence.load_orderbook_snapshot(symbol)
            if snapshot:
                matching_engine.order_book = snapshot
                logger.info(f"Recovered order book snapshot for {symbol}")
            
            # 2) Replay only resting orders (LIMIT with price) newer than snapshot
            restored = await self._replay_orders(matching_engine, snap_ts)
            
            logger.info(f"Recovery complete for {symbol}: {restored} orders restored")
            return True
        
        except Exception as e:
            logger.error(f"Recovery failed for {matching_engine.symbol}: {e}")
            return False
    
    async def _replay_orders(self, matching_engine, snap_ts: Optional[datetime]) -> int:
        """
        Replay resting orders from database
        Only LIMIT orders with status pending/partially_filled
        """
        conn = await self.persistence._get_connection()
        
        # Build query
        query = """
            SELECT order_id, symbol, side, order_type, price, quantity, 
                   filled_quantity, status, timestamp, user_id
            FROM orders
            WHERE symbol = ?
              AND status IN ('pending', 'partially_filled')
              AND order_type = 'limit'
              AND price IS NOT NULL
        """
        params = [matching_engine.symbol]
        
        if snap_ts:
            query += " AND timestamp > ?"
            params.append(snap_ts.isoformat())
        
        query += " ORDER BY timestamp ASC"  # Replay in order
        
        restored = 0
        
        async with conn.execute(query, tuple(params)) as cursor:
            columns = [col[0] for col in cursor.description]
            
            async for row in cursor:
                order_dict = dict(zip(columns, row))
                
                # Skip if already in book (from snapshot)
                if order_dict['order_id'] in matching_engine.order_book.orders:
                    continue
                
                # Rebuild order object
                try:
                    order = Order(
                        order_id=order_dict['order_id'],
                        symbol=order_dict['symbol'],
                        side=OrderSide(order_dict['side']),
                        order_type=OrderType(order_dict['order_type']), 
                        price=Decimal(str(order_dict['price'])) if order_dict['price'] else None,
                        quantity=Decimal(str(order_dict['quantity'])),
                        filled_quantity=Decimal(str(order_dict['filled_quantity'])),
                        status=OrderStatus(order_dict['status']),
                        timestamp=datetime.fromisoformat(order_dict['timestamp']),
                        user_id=order_dict['user_id'],
                    )
                    
                    # Safety check
                    if order.price is None or order.remaining_quantity <= 0:
                        continue
                    
                    # Add to order book
                    if matching_engine.order_book.add_order(order):
                        restored += 1
                
                except Exception as e:
                    logger.error(f"Failed to restore order {order_dict['order_id']}: {e}")
                    continue
        
        return restored
    
    async def verify_recovery(self, matching_engine) -> dict:
        """
        Verify recovery completed successfully
        Returns statistics about recovered state
        """
        try:
            stats = {
                "symbol": matching_engine.symbol,
                "bid_levels": len(matching_engine.order_book.bid_side.price_levels),
                "ask_levels": len(matching_engine.order_book.ask_side.price_levels),
                "total_orders": len(matching_engine.order_book.orders),
                "bbo": matching_engine.order_book.get_bbo(),
            }
            
            logger.info(f"Recovery verification: {stats}")
            return stats
        
        except Exception as e:
            logger.error(f"Recovery verification failed: {e}")
            return {}