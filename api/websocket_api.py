from dataclasses import asdict
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
import ujson  # WINDOWS-COMPATIBLE: 2-3x faster than json
import asyncio
from typing import Dict, Set
from decimal import Decimal
from datetime import datetime
import logging
import sys
import os
from collections import deque
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.matching_engine import MatchingEngine
from engine.order_types import Order, OrderSide, OrderType  


logger = logging.getLogger(__name__)

class WebSocketManager:
    """
    High-performance WebSocket manager
    Key optimizations:
    - Message batching (5ms window)
    - Separate send/recv tasks per connection
    - ujson for 2-3x faster serialization (Windows compatible)
    - Fire-and-forget broadcasts
    """
    
    def __init__(self):
        # Connection pools organized by symbol for efficient broadcasting
        self.connections_by_symbol: Dict[str, Set[WebSocket]] = {}
        self.client_websockets: Dict[str, WebSocket] = {}
        self.client_subscriptions: Dict[str, Dict[str, dict]] = {}
        
        self.matching_engines: Dict[str, MatchingEngine] = {}
        
        # Message batching for performance
        self.pending_messages: Dict[str, deque] = {}  # per-symbol message queues
        self.batch_interval = 0.005  # 5ms batching window
        self.batch_tasks: Dict[str, asyncio.Task] = {}
        
        # Stats
        self.total_messages_sent = 0
        self.total_bytes_sent = 0
        
    async def connect(self, websocket: WebSocket, client_id: str):
        """Accept new WebSocket connection"""
        await websocket.accept()
        self.client_websockets[client_id] = websocket
        self.client_subscriptions[client_id] = {}
        logger.info(f"Client {client_id} connected. Total: {len(self.client_websockets)}")
        
        # Send initial connection confirmation
        await self._send_to_client(client_id, {
            "type": "connection",
            "status": "connected",
            "client_id": client_id,
            "available_symbols": list(self.matching_engines.keys())
        })
    
    def disconnect(self, client_id: str):
        """Remove disconnected client and clean up subscriptions"""
        # Remove from all symbol subscriptions
        if client_id in self.client_subscriptions:
            for symbol in list(self.client_subscriptions[client_id].keys()):
                if symbol in self.connections_by_symbol:
                    ws = self.client_websockets.get(client_id)
                    if ws in self.connections_by_symbol[symbol]:
                        self.connections_by_symbol[symbol].discard(ws)
        
        if client_id in self.client_websockets:
            del self.client_websockets[client_id]
        if client_id in self.client_subscriptions:
            del self.client_subscriptions[client_id]
        
        logger.info(f"Client {client_id} disconnected. Remaining: {len(self.client_websockets)}")
    
    async def subscribe_client(self, client_id: str, symbol: str):
        """Subscribe client to a symbol's updates"""
        if symbol not in self.connections_by_symbol:
            self.connections_by_symbol[symbol] = set()
            self.pending_messages[symbol] = deque(maxlen=1000)
            # Start batch sender for this symbol
            self.batch_tasks[symbol] = asyncio.create_task(self._batch_sender(symbol))
        
        ws = self.client_websockets.get(client_id)
        if ws:
            self.connections_by_symbol[symbol].add(ws)
            if client_id not in self.client_subscriptions:
                self.client_subscriptions[client_id] = {}
            self.client_subscriptions[client_id][symbol] = True
    
    async def unsubscribe_client(self, client_id: str, symbol: str):
        """Unsubscribe client from a symbol"""
        ws = self.client_websockets.get(client_id)
        if ws and symbol in self.connections_by_symbol:
            self.connections_by_symbol[symbol].discard(ws)
        
        if client_id in self.client_subscriptions:
            self.client_subscriptions[client_id].pop(symbol, None)
    
    async def broadcast_to_symbol(self, symbol: str, message: dict):
        """
        Queue message for batched broadcast
        Much faster than immediate sending
        """
        if symbol not in self.pending_messages:
            return
        
        self.pending_messages[symbol].append(message)
    
    async def _batch_sender(self, symbol: str):
        """
        Dedicated sender task that batches messages
        Sends accumulated messages every 5ms to reduce overhead
        """
        while True:
            try:
                await asyncio.sleep(self.batch_interval)
                
                if symbol not in self.pending_messages:
                    break
                
                messages = self.pending_messages[symbol]
                if not messages or symbol not in self.connections_by_symbol:
                    continue
                
                # Collect all pending messages
                batch = []
                while messages:
                    batch.append(messages.popleft())
                
                if not batch or not self.connections_by_symbol[symbol]:
                    continue
                
                # CRITICAL: Serialize once for all clients (huge performance win!)
                serialized = self._fast_serialize(batch)
                
                # Broadcast to all connections concurrently (fire-and-forget)
                connections = list(self.connections_by_symbol[symbol])
                await asyncio.gather(
                    *[self._send_safe(ws, serialized) for ws in connections],
                    return_exceptions=True
                )
                
                self.total_messages_sent += len(batch)
                self.total_bytes_sent += len(serialized) * len(connections)
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Batch sender error for {symbol}: {e}")
    
    def _fast_serialize(self, data) -> str:
        """
        Fast serialization using ujson (Windows compatible)
        2-3x faster than standard json.dumps
        """
        try:
            return ujson.dumps(data, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Serialization error: {e}")
            return "[]"
    
    async def _send_safe(self, websocket: WebSocket, data: str):
        """Send text with error handling, don't crash on client disconnect"""
        try:
            await websocket.send_text(data)
        except Exception:
            pass  # Client disconnected, ignore silently
    
    async def _send_to_client(self, client_id: str, message: dict):
        """Send message to specific client (for control messages)"""
        if client_id in self.client_websockets:
            try:
                serialized = ujson.dumps(message, ensure_ascii=False)
                await self.client_websockets[client_id].send_text(serialized)
            except Exception as e:
                logger.error(f"Failed to send to {client_id}: {e}")
                self.disconnect(client_id)

# Initialize FastAPI app
app = FastAPI(title="Crypto Matching Engine WebSocket API")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize WebSocket manager and matching engines
ws_manager = WebSocketManager()

# Create matching engines for different trading pairs
TRADING_PAIRS = ["BTC-USDT", "ETH-USDT", "SOL-USDT"]
for pair in TRADING_PAIRS:
    ws_manager.matching_engines[pair] = MatchingEngine(pair)

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """
    Main WebSocket endpoint for order submission and data streaming
    Optimized for minimal latency
    """
    await ws_manager.connect(websocket, client_id)
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            
            # Parse with ujson (faster)
            try:
                message = ujson.loads(data)
            except:
                logger.error(f"Failed to parse message from {client_id}")
                continue
            
            # Process message based on type
            message_type = message.get("type")
            
            if message_type == "order":
                await handle_order_submission(ws_manager, client_id, message)
                
            elif message_type == "cancel":
                await handle_order_cancellation(ws_manager, client_id, message)
                
            elif message_type == "subscribe":
                await handle_subscription(ws_manager, client_id, message)
                
            elif message_type == "unsubscribe":
                await handle_unsubscription(ws_manager, client_id, message)
                
            elif message_type == "get_orderbook":
                await handle_orderbook_request(ws_manager, client_id, message)
                
            elif message_type == "ping":
                await ws_manager._send_to_client(client_id, {"type": "pong"})
                
            else:
                await ws_manager._send_to_client(client_id, {
                    "type": "error",
                    "message": f"Unknown message type: {message_type}"
                })
    
    except WebSocketDisconnect:
        ws_manager.disconnect(client_id)
        
    except Exception as e:
        logger.error(f"WebSocket error for client {client_id}: {e}")
        ws_manager.disconnect(client_id)

async def handle_order_submission(ws_manager: WebSocketManager, client_id: str, message: dict):
    """FIXED VERSION - Better trade broadcasting"""
    try:
        symbol = message.get("symbol")
        if symbol not in ws_manager.matching_engines:
            await ws_manager._send_to_client(client_id, {
                "type": "error",
                "message": f"Invalid symbol: {symbol}"
            })
            return
        
        # Create order object
        order = Order(
            symbol=symbol,
            side=OrderSide(message.get("side")),
            order_type=OrderType(message.get("order_type")),
            quantity=Decimal(str(message.get("quantity"))),
            price=Decimal(str(message.get("price"))) if message.get("price") else None,
            user_id=client_id
        )
        
        # Submit to matching engine
        engine = ws_manager.matching_engines[symbol]
        success, msg, trades = await engine.submit_order(order)
        
        # Send response to THIS client
        response = {
            "type": "order_response",
            "success": success,
            "message": msg,
            "order_id": order.order_id,
            "symbol": symbol,
            "status": order.status.value,
            "filled_quantity": str(order.filled_quantity),
            "remaining_quantity": str(order.remaining_quantity),
            "trades": [
                {
                    "trade_id": t.trade_id,
                    "price": str(t.price),
                    "quantity": str(t.quantity),
                    "fee": str(t.taker_fee)
                } for t in trades
            ]
        }
        
        await ws_manager._send_to_client(client_id, response)
        
        # Trades are already broadcast via engine's trade subscribers
        # Market data updates are already broadcast via engine's market_data subscribers
        
    except Exception as e:
        logger.error(f"Error handling order submission: {e}")
        await ws_manager._send_to_client(client_id, {
            "type": "error",
            "message": str(e)
        })

async def handle_order_cancellation(ws_manager: WebSocketManager, client_id: str, message: dict):
    """Handle order cancellation request"""
    try:
        order_id = message.get("order_id")
        symbol = message.get("symbol")
        
        if symbol not in ws_manager.matching_engines:
            await ws_manager._send_to_client(client_id, {
                "type": "error",
                "message": f"Invalid symbol: {symbol}"
            })
            return
        
        engine = ws_manager.matching_engines[symbol]
        success, order = await engine.cancel_order(order_id)

        await ws_manager._send_to_client(client_id, {
            "type": "cancel_response",
            "success": success,
            "order_id": order_id,
            "message": "Order cancelled" if success else "Order not found"
        })
        
    except Exception as e:
        logger.error(f"Error handling order cancellation: {e}")
        await ws_manager._send_to_client(client_id, {
            "type": "error",
            "message": str(e)
        })

async def handle_subscription(ws_manager: WebSocketManager, client_id: str, message: dict):
    """
    Subscribe a client to one or more symbols.
    - Sends subscription ack FIRST, then initial market data snapshots.
    - Initializes per-engine broadcast callbacks once (both trades & market data).
    """
    symbols = message.get("symbols", [])
    subscribed: list[str] = []

    for symbol in symbols:
        if symbol not in ws_manager.matching_engines:
            continue

        engine = ws_manager.matching_engines[symbol]

        # Track this client in the symbol's connection set
        await ws_manager.subscribe_client(client_id, symbol)

        # Initialize engine → WS broadcast bridges ONCE per engine
        if not getattr(engine, "_ws_broadcast_initialized", False):

            async def market_data_callback(data: dict):
                # data already contains "symbol"
                await ws_manager.broadcast_to_symbol(data["symbol"], data)

            async def trade_callback(data: dict):
                # data already contains "symbol"
                await ws_manager.broadcast_to_symbol(data["symbol"], data)

            # Always subscribe both streams at the engine level
            engine.subscribe_market_data(market_data_callback)
            engine.subscribe_trades(trade_callback)

            engine._ws_broadcast_initialized = True

        subscribed.append(symbol)

    # Send subscription confirmation FIRST
    await ws_manager._send_to_client(client_id, {
        "type": "subscription_response",
        "subscribed": subscribed,
        "message": f"Subscribed to {', '.join(subscribed)}" if subscribed else "No valid symbols"
    })

    # Then send initial snapshots for each subscribed symbol
    for symbol in subscribed:
        engine = ws_manager.matching_engines[symbol]
        bbo = engine.order_book.get_bbo()
        depth = engine.order_book.get_depth()
        await ws_manager._send_to_client(client_id, {
            "type": "market_data",
            "symbol": symbol,
            "timestamp": datetime.utcnow().isoformat(),
            "bbo": bbo,
            "depth": depth
        })


async def handle_unsubscription(ws_manager: WebSocketManager, client_id: str, message: dict):
    """Handle unsubscription requests"""
    symbols = message.get("symbols", [])
    unsubscribed = []
    
    for symbol in symbols:
        await ws_manager.unsubscribe_client(client_id, symbol)
        unsubscribed.append(symbol)
    
    await ws_manager._send_to_client(client_id, {
        "type": "unsubscription_response",
        "unsubscribed": unsubscribed,
        "message": f"Unsubscribed from {', '.join(unsubscribed)}" if unsubscribed else "No symbols to unsubscribe"
    })

async def handle_orderbook_request(ws_manager: WebSocketManager, client_id: str, message: dict):
    """Handle order book snapshot request"""
    symbol = message.get("symbol")
    depth = message.get("depth", 10)
    
    if symbol not in ws_manager.matching_engines:
        await ws_manager._send_to_client(client_id, {
            "type": "error",
            "message": f"Invalid symbol: {symbol}"
        })
        return
    
    engine = ws_manager.matching_engines[symbol]
    orderbook = engine.order_book.get_depth(depth)
    bbo = engine.order_book.get_bbo()
    
    await ws_manager._send_to_client(client_id, {
        "type": "orderbook_response",
        "symbol": symbol,
        "bbo": bbo,
        "depth": orderbook
    })

@app.post("/save_snapshot")
async def save_snapshot(request: Request):
    """Manually trigger a persistence snapshot for all active matching engines"""
    try:
        results = []
        for symbol, engine in ws_manager.matching_engines.items():
            await engine.persistence.save_orderbook_snapshot(symbol, engine.order_book)
            results.append(f"Snapshot saved for {symbol}")
        
        return JSONResponse(
            content={"status": "ok", "details": results},
            status_code=200
        )

    except Exception as e:
        return JSONResponse(
            content={"status": "error", "message": str(e)},
            status_code=500
        )

@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "Running",
        "engines": list(ws_manager.matching_engines.keys()),
        "active_connections": len(ws_manager.client_websockets),
        "total_messages_sent": ws_manager.total_messages_sent,
        "total_bytes_sent": ws_manager.total_bytes_sent
    }

@app.get("/orderbook/{symbol}")
async def get_orderbook(symbol: str, depth: int = 10):
    """REST endpoint to get current order book"""
    if symbol not in ws_manager.matching_engines:
        return {"error": f"Invalid symbol: {symbol}"}
    
    engine = ws_manager.matching_engines[symbol]
    return engine.order_book.get_depth(depth)

@app.get("/bbo/{symbol}")
async def get_bbo(symbol: str):
    """REST endpoint to get Best Bid and Offer"""
    if symbol not in ws_manager.matching_engines:
        return {"error": f"Invalid symbol: {symbol}"}
    
    engine = ws_manager.matching_engines[symbol]
    return engine.order_book.get_bbo()

@app.get("/metrics")
async def metrics():
    """Return per-symbol performance metrics"""
    out = {}
    for symbol, eng in ws_manager.matching_engines.items():
        m = eng.get_performance_metrics()
        md = asdict(m)
        md["timestamp"] = m.timestamp.isoformat()
        out[symbol] = md
    return out

@app.get("/perf_report", response_class=PlainTextResponse)
async def perf_report():
    """Get detailed performance report"""
    lines = []
    for symbol, eng in ws_manager.matching_engines.items():
        lines.append(f"=== {symbol} ===\n{eng.get_performance_report()}")
    
    # Add WebSocket stats
    lines.append(f"\n=== WebSocket Stats ===")
    lines.append(f"Active connections: {len(ws_manager.client_websockets)}")
    lines.append(f"Total messages sent: {ws_manager.total_messages_sent}")
    lines.append(f"Total bytes sent: {ws_manager.total_bytes_sent}")
    
    return "\n\n".join(lines)

@app.on_event("startup")
async def startup_event():
    """Initialize system on startup"""
    logger.info("Starting Crypto Matching Engine WebSocket Server")
    logger.info(f"Available trading pairs: {', '.join(TRADING_PAIRS)}")
    
    # Start background tasks for all engines
    for eng in ws_manager.matching_engines.values():
        await eng.start()

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("Shutting down Crypto Matching Engine WebSocket Server")
    
    # Cancel all batch senders
    for task in ws_manager.batch_tasks.values():
        task.cancel()
    
    # Close all WebSocket connections
    for client_id in list(ws_manager.client_websockets.keys()):
        ws_manager.disconnect(client_id)
    
    # Close persistence connections
    for engine in ws_manager.matching_engines.values():
        await engine.persistence.close()