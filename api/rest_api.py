from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict
from decimal import Decimal

class OrderRequest(BaseModel):
    symbol: str
    side: str
    order_type: str
    quantity: float
    price: Optional[float] = None
    user_id: Optional[str] = None

def create_rest_app(matching_engines: Dict):
    """Create REST API application"""
    app = FastAPI(title="Crypto Matching Engine REST API")
    
    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    @app.get("/")
    async def root():
        """Health check endpoint"""
        return {
            "status": "Running",
            "engines": list(matching_engines.keys()),
            "version": "1.0.0"
        }
    
    @app.get("/symbols")
    async def get_symbols():
        """Get available trading symbols"""
        return {"symbols": list(matching_engines.keys())}
    
    @app.get("/orderbook/{symbol}")
    async def get_orderbook(symbol: str, depth: int = 10):
        """Get current order book for a symbol"""
        if symbol not in matching_engines:
            raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")
        
        engine = matching_engines[symbol]
        return engine.order_book.get_depth(depth)
    
    @app.get("/bbo/{symbol}")
    async def get_bbo(symbol: str):
        """Get Best Bid and Offer for a symbol"""
        if symbol not in matching_engines:
            raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")
        
        engine = matching_engines[symbol]
        return engine.order_book.get_bbo()
    
    @app.get("/trades/{symbol}")
    async def get_recent_trades(symbol: str, limit: int = 100):
        """Get recent trades for a symbol"""
        if symbol not in matching_engines:
            raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")
        
        engine = matching_engines[symbol]
        trades = list(engine.trades)[-limit:]
        
        return {
            "symbol": symbol,
            "trades": [
                {
                    "trade_id": trade.trade_id,
                    "price": str(trade.price),
                    "quantity": str(trade.quantity),
                    "aggressor_side": trade.aggressor_side.value,
                    "timestamp": trade.timestamp.isoformat()
                } for trade in trades
            ]
        }
    
    @app.post("/order")
    async def submit_order(order: OrderRequest):
        """Submit a new order via REST"""
        if order.symbol not in matching_engines:
            raise HTTPException(status_code=404, detail=f"Symbol {order.symbol} not found")
        
        # This endpoint is mainly for demonstration
        # In production, orders would typically come through WebSocket
        return {
            "message": "Please use WebSocket connection for order submission",
            "websocket_url": "ws://localhost:8000/ws/{client_id}"
        }
    
    return app