import pytest
import asyncio
import json
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocket
from decimal import Decimal
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.websocket_api import app, ws_manager
from engine.order_types import Order, OrderSide, OrderType

# Create test client
client = TestClient(app)

class TestRESTEndpoints:
    """Test REST API endpoints"""
    
    def test_root_endpoint(self):
        """Test health check endpoint"""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "Running"
        assert "engines" in data
        assert "BTC-USDT" in data["engines"]
    
    def test_get_orderbook(self):
        """Test getting order book via REST"""
        response = client.get("/orderbook/BTC-USDT")
        assert response.status_code == 200
        data = response.json()
        assert "symbol" in data
        assert "bids" in data
        assert "asks" in data
        assert data["symbol"] == "BTC-USDT"
    
    def test_get_orderbook_invalid_symbol(self):
        """Test getting order book with invalid symbol"""
        response = client.get("/orderbook/INVALID-PAIR")
        assert response.status_code == 200
        data = response.json()
        assert "error" in data
    
    def test_get_bbo(self):
        """Test getting BBO via REST"""
        response = client.get("/bbo/BTC-USDT")
        assert response.status_code == 200
        data = response.json()
        assert "symbol" in data
        assert "best_bid" in data
        assert "best_ask" in data
        assert "spread" in data
    
    def test_get_bbo_invalid_symbol(self):
        """Test getting BBO with invalid symbol"""
        response = client.get("/bbo/INVALID-PAIR")
        assert response.status_code == 200
        data = response.json()
        assert "error" in data

class TestWebSocketConnection:
    """Test WebSocket connection and basic messaging"""
    
    def test_websocket_connection(self):
        """Test establishing WebSocket connection"""
        with client.websocket_connect("/ws/test-client-1") as websocket:
            # Should receive connection confirmation
            data = websocket.receive_json()
            assert data["type"] == "connection"
            assert data["status"] == "connected"
            assert data["client_id"] == "test-client-1"
            assert "available_symbols" in data
    
    def test_ping_pong(self):
        """Test ping-pong heartbeat"""
        with client.websocket_connect("/ws/test-client-2") as websocket:
            # Skip connection message
            websocket.receive_json()
            
            # Send ping
            websocket.send_json({"type": "ping"})
            
            # Should receive pong
            data = websocket.receive_json()
            assert data["type"] == "pong"
    
    def test_unknown_message_type(self):
        """Test handling of unknown message type"""
        with client.websocket_connect("/ws/test-client-3") as websocket:
            # Skip connection message
            websocket.receive_json()
            
            # Send unknown message type
            websocket.send_json({"type": "unknown_type"})
            
            # Should receive error
            data = websocket.receive_json()
            assert data["type"] == "error"
            assert "Unknown message type" in data["message"]

class TestOrderSubmission:
    """Test order submission via WebSocket"""
    
    def test_submit_limit_buy_order(self):
        """Test submitting a limit buy order"""
        with client.websocket_connect("/ws/test-client-4") as websocket:
            # Skip connection message
            websocket.receive_json()
            
            # Submit limit buy order
            order_msg = {
                "type": "order",
                "symbol": "BTC-USDT",
                "side": "buy",
                "order_type": "limit",
                "price": 45000,
                "quantity": 1.0
            }
            websocket.send_json(order_msg)
            
            # Should receive order response
            data = websocket.receive_json()
            assert data["type"] == "order_response"
            assert data["success"] == True
            assert "order_id" in data
            assert data["symbol"] == "BTC-USDT"
            assert data["status"] == "pending"
    
    def test_submit_limit_sell_order(self):
        """Test submitting a limit sell order"""
        with client.websocket_connect("/ws/test-client-5") as websocket:
            # Skip connection message
            websocket.receive_json()
            
            # Submit limit sell order
            order_msg = {
                "type": "order",
                "symbol": "BTC-USDT",
                "side": "sell",
                "order_type": "limit",
                "price": 55000,
                "quantity": 0.5
            }
            websocket.send_json(order_msg)
            
            # Should receive order response
            data = websocket.receive_json()
            assert data["type"] == "order_response"
            assert data["success"] == True
            assert data["status"] == "pending"
    
    def test_submit_market_order(self):
        """Test submitting a market order"""
        with client.websocket_connect("/ws/test-client-6") as websocket:
            # Skip connection message
            websocket.receive_json()
            
            # First add a limit order to create liquidity
            limit_order = {
                "type": "order",
                "symbol": "BTC-USDT",
                "side": "sell",
                "order_type": "limit",
                "price": 50000,
                "quantity": 2.0
            }
            websocket.send_json(limit_order)
            websocket.receive_json()  # Skip response
            
            # Submit market buy order
            market_order = {
                "type": "order",
                "symbol": "BTC-USDT",
                "side": "buy",
                "order_type": "market",
                "quantity": 1.0
            }
            websocket.send_json(market_order)
            
            # Should receive order response with trades
            data = websocket.receive_json()
            assert data["type"] == "order_response"
            assert data["success"] == True
            assert data["status"] == "filled"
            assert len(data["trades"]) > 0
            assert data["filled_quantity"] == "1.0"
    
    def test_submit_invalid_order(self):
        """Test submitting an invalid order"""
        with client.websocket_connect("/ws/test-client-7") as websocket:
            # Skip connection message
            websocket.receive_json()
            
            # Submit order with invalid quantity
            order_msg = {
                "type": "order",
                "symbol": "BTC-USDT",
                "side": "buy",
                "order_type": "limit",
                "price": 50000,
                "quantity": -1.0  # Invalid negative quantity
            }
            websocket.send_json(order_msg)
            
            # Should receive error response
            data = websocket.receive_json()
            assert data["type"] == "order_response"
            assert data["success"] == False
            assert "Invalid quantity" in data["message"]
    
    def test_submit_order_invalid_symbol(self):
        """Test submitting order with invalid symbol"""
        with client.websocket_connect("/ws/test-client-8") as websocket:
            # Skip connection message
            websocket.receive_json()
            
            # Submit order with invalid symbol
            order_msg = {
                "type": "order",
                "symbol": "INVALID-PAIR",
                "side": "buy",
                "order_type": "limit",
                "price": 50000,
                "quantity": 1.0
            }
            websocket.send_json(order_msg)
            
            # Should receive error
            data = websocket.receive_json()
            assert data["type"] == "error"
            assert "Invalid symbol" in data["message"]

class TestOrderCancellation:
    """Test order cancellation via WebSocket"""
    
    def test_cancel_existing_order(self):
        """Test cancelling an existing order"""
        with client.websocket_connect("/ws/test-client-9") as websocket:
            # Skip connection message
            websocket.receive_json()
            
            # Submit an order first
            order_msg = {
                "type": "order",
                "symbol": "BTC-USDT",
                "side": "buy",
                "order_type": "limit",
                "price": 45000,
                "quantity": 1.0
            }
            websocket.send_json(order_msg)
            
            # Get order response
            order_response = websocket.receive_json()
            order_id = order_response["order_id"]
            
            # Cancel the order
            cancel_msg = {
                "type": "cancel",
                "symbol": "BTC-USDT",
                "order_id": order_id
            }
            websocket.send_json(cancel_msg)
            
            # Should receive cancel response
            data = websocket.receive_json()
            assert data["type"] == "cancel_response"
            assert data["success"] == True
            assert data["order_id"] == order_id
            assert data["message"] == "Order cancelled"
    
    def test_cancel_nonexistent_order(self):
        """Test cancelling a non-existent order"""
        with client.websocket_connect("/ws/test-client-10") as websocket:
            # Skip connection message
            websocket.receive_json()
            
            # Try to cancel non-existent order
            cancel_msg = {
                "type": "cancel",
                "symbol": "BTC-USDT",
                "order_id": "non-existent-order-id"
            }
            websocket.send_json(cancel_msg)
            
            # Should receive failure response
            data = websocket.receive_json()
            assert data["type"] == "cancel_response"
            assert data["success"] == False
            assert data["message"] == "Order not found"

class TestSubscriptions:
    """Test market data subscriptions"""
    
    def test_subscribe_to_symbol(self):
        """Test subscribing to a symbol's market data"""
        with client.websocket_connect("/ws/test-client-11") as websocket:
            # Skip connection message
            websocket.receive_json()
            
            # Subscribe to BTC-USDT
            subscribe_msg = {
                "type": "subscribe",
                "symbols": ["BTC-USDT"],
                "trades": True,
                "market_data": True
            }
            websocket.send_json(subscribe_msg)
            
            # Should receive subscription response
            data = websocket.receive_json()
            assert data["type"] == "subscription_response"
            assert "BTC-USDT" in data["subscribed"]
            
            # Should receive initial market data
            market_data = websocket.receive_json()
            assert market_data["type"] == "market_data"
            assert market_data["symbol"] == "BTC-USDT"
    
    def test_subscribe_multiple_symbols(self):
        """Test subscribing to multiple symbols"""
        with client.websocket_connect("/ws/test-client-12") as websocket:
            # Skip connection message
            websocket.receive_json()
            
            # Subscribe to multiple symbols
            subscribe_msg = {
                "type": "subscribe",
                "symbols": ["BTC-USDT", "ETH-USDT", "SOL-USDT"]
            }
            websocket.send_json(subscribe_msg)
            
            # Should receive subscription response
            data = websocket.receive_json()
            assert data["type"] == "subscription_response"
            assert len(data["subscribed"]) == 3
            assert "BTC-USDT" in data["subscribed"]
            assert "ETH-USDT" in data["subscribed"]
            assert "SOL-USDT" in data["subscribed"]
    
    def test_unsubscribe_from_symbol(self):
        """Test unsubscribing from a symbol"""
        with client.websocket_connect("/ws/test-client-13") as websocket:
            # Skip connection message
            websocket.receive_json()
            
            # First subscribe
            subscribe_msg = {
                "type": "subscribe",
                "symbols": ["BTC-USDT"]
            }
            websocket.send_json(subscribe_msg)
            websocket.receive_json()  # Skip subscription response
            websocket.receive_json()  # Skip initial market data
            
            # Now unsubscribe
            unsubscribe_msg = {
                "type": "unsubscribe",
                "symbols": ["BTC-USDT"]
            }
            websocket.send_json(unsubscribe_msg)
            
            # Should receive unsubscription response
            data = websocket.receive_json()
            assert data["type"] == "unsubscription_response"
            assert "BTC-USDT" in data["unsubscribed"]
    
    def test_orderbook_request(self):
        """Test requesting order book snapshot"""
        with client.websocket_connect("/ws/test-client-14") as websocket:
            # Skip connection message
            websocket.receive_json()
            
            # Request order book
            request_msg = {
                "type": "get_orderbook",
                "symbol": "BTC-USDT",
                "depth": 5
            }
            websocket.send_json(request_msg)
            
            # Should receive order book response
            data = websocket.receive_json()
            assert data["type"] == "orderbook_response"
            assert data["symbol"] == "BTC-USDT"
            assert "bbo" in data
            assert "depth" in data

class TestTradeExecution:
    """Test trade execution scenarios"""
    
    def test_trade_broadcast(self):
        """Test that trades are broadcast to subscribers"""
        with client.websocket_connect("/ws/test-client-15") as ws1:
            with client.websocket_connect("/ws/test-client-16") as ws2:
                # Skip connection messages
                ws1.receive_json()
                ws2.receive_json()
                
                # Client 2 subscribes to trades
                ws2.send_json({
                    "type": "subscribe",
                    "symbols": ["BTC-USDT"],
                    "trades": True
                })
                ws2.receive_json()  # Skip subscription response
                ws2.receive_json()  # Skip initial market data
                
                # Client 1 submits a limit sell order
                ws1.send_json({
                    "type": "order",
                    "symbol": "BTC-USDT",
                    "side": "sell",
                    "order_type": "limit",
                    "price": 50000,
                    "quantity": 1.0
                })
                ws1.receive_json()  # Skip order response
                
                # Client 1 submits a market buy order to trigger trade
                ws1.send_json({
                    "type": "order",
                    "symbol": "BTC-USDT",
                    "side": "buy",
                    "order_type": "market",
                    "quantity": 0.5
                })
                
                # Client 1 receives order response with trades
                order_response = ws1.receive_json()
                assert order_response["type"] == "order_response"
                assert len(order_response["trades"]) > 0
                
                # Client 2 should receive trade broadcast
                # May need to skip market data updates
                for _ in range(5):  # Try up to 5 messages
                    trade_data = ws2.receive_json()
                    if trade_data["type"] == "trade":
                        assert trade_data["symbol"] == "BTC-USDT"
                        assert "trade_id" in trade_data
                        assert "price" in trade_data
                        assert "quantity" in trade_data
                        break

if __name__ == "__main__":
    pytest.main([__file__, "-v"])