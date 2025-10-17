import pytest
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decimal import Decimal
from datetime import datetime
from engine.order_book import OrderBook
from engine.order_types import Order, OrderSide, OrderType, OrderStatus
from engine.data_structures import PriceLevel, OrderBookSide

class TestPriceLevel:
    """Test PriceLevel functionality"""
    
    def test_price_level_creation(self):
        """Test creating a price level"""
        price_level = PriceLevel(Decimal("50000"))
        assert price_level.price == Decimal("50000")
        assert price_level.orders == []
        assert price_level.total_quantity == Decimal("0")
    
    def test_add_order_to_price_level(self):
        """Test adding orders to a price level"""
        price_level = PriceLevel(Decimal("50000"))
        
        order1 = Order(
            symbol="BTC-USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("50000"),
            quantity=Decimal("1.0")
        )
        
        order2 = Order(
            symbol="BTC-USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("50000"),
            quantity=Decimal("0.5")
        )
        
        price_level.add_order(order1)
        price_level.add_order(order2)
        
        assert len(price_level.orders) == 2
        assert price_level.total_quantity == Decimal("1.5")
        assert price_level.orders[0] == order1  # FIFO order
        assert price_level.orders[1] == order2
    
    def test_remove_order_from_price_level(self):
        """Test removing orders from a price level"""
        price_level = PriceLevel(Decimal("50000"))
        
        order = Order(
            order_id="test-order-1",
            symbol="BTC-USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("50000"),
            quantity=Decimal("1.0")
        )
        
        price_level.add_order(order)
        assert price_level.total_quantity == Decimal("1.0")
        
        success = price_level.remove_order("test-order-1")
        assert success == True
        assert len(price_level.orders) == 0
        assert price_level.total_quantity == Decimal("0")
        
        # Try removing non-existent order
        success = price_level.remove_order("non-existent")
        assert success == False
    
    def test_update_quantity_after_partial_fill(self):
        """Test updating quantity after partial fill"""
        price_level = PriceLevel(Decimal("50000"))
        
        order = Order(
            order_id="test-order-1",
            symbol="BTC-USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("50000"),
            quantity=Decimal("1.0")
        )
        
        price_level.add_order(order)
        assert price_level.total_quantity == Decimal("1.0")
        
        # Simulate partial fill
        price_level.update_quantity("test-order-1", Decimal("0.3"))
        assert price_level.total_quantity == Decimal("0.7")

class TestOrderBookSide:
    """Test OrderBookSide functionality"""
    
    def test_bid_side_creation(self):
        """Test creating bid side of order book"""
        bid_side = OrderBookSide(is_bid=True)
        assert bid_side.is_bid == True
        assert len(bid_side.price_levels) == 0
        assert len(bid_side.price_heap) == 0
    
    def test_ask_side_creation(self):
        """Test creating ask side of order book"""
        ask_side = OrderBookSide(is_bid=False)
        assert ask_side.is_bid == False
        assert len(ask_side.price_levels) == 0
        assert len(ask_side.price_heap) == 0
    
    def test_add_orders_to_bid_side(self):
        """Test adding orders to bid side maintains price priority"""
        bid_side = OrderBookSide(is_bid=True)
        
        order1 = Order(
            symbol="BTC-USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("49000"),
            quantity=Decimal("1.0")
        )
        
        order2 = Order(
            symbol="BTC-USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("50000"),
            quantity=Decimal("0.5")
        )
        
        order3 = Order(
            symbol="BTC-USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("48000"),
            quantity=Decimal("2.0")
        )
        
        bid_side.add_order(order1)
        bid_side.add_order(order2)
        bid_side.add_order(order3)
        
        # Best bid should be highest price
        best_price = bid_side.get_best_price()
        assert best_price == Decimal("50000")
        
        assert len(bid_side.price_levels) == 3
        assert Decimal("49000") in bid_side.price_levels
        assert Decimal("50000") in bid_side.price_levels
        assert Decimal("48000") in bid_side.price_levels
    
    def test_add_orders_to_ask_side(self):
        """Test adding orders to ask side maintains price priority"""
        ask_side = OrderBookSide(is_bid=False)
        
        order1 = Order(
            symbol="BTC-USDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            price=Decimal("51000"),
            quantity=Decimal("1.0")
        )
        
        order2 = Order(
            symbol="BTC-USDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            price=Decimal("50000"),
            quantity=Decimal("0.5")
        )
        
        order3 = Order(
            symbol="BTC-USDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            price=Decimal("52000"),
            quantity=Decimal("2.0")
        )
        
        ask_side.add_order(order1)
        ask_side.add_order(order2)
        ask_side.add_order(order3)
        
        # Best ask should be lowest price
        best_price = ask_side.get_best_price()
        assert best_price == Decimal("50000")
        
        assert len(ask_side.price_levels) == 3

class TestOrderBook:
    """Test OrderBook functionality"""
    
    def test_order_book_creation(self):
        """Test creating an order book"""
        order_book = OrderBook("BTC-USDT")
        assert order_book.symbol == "BTC-USDT"
        assert len(order_book.orders) == 0
        assert order_book.bid_side is not None
        assert order_book.ask_side is not None
    
    def test_add_buy_order(self):
        """Test adding a buy order to the book"""
        order_book = OrderBook("BTC-USDT")
        
        order = Order(
            order_id="buy-1",
            symbol="BTC-USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("50000"),
            quantity=Decimal("1.0")
        )
        
        success = order_book.add_order(order)
        assert success == True
        assert "buy-1" in order_book.orders
        assert order_book.orders["buy-1"] == order
        
        # Check order is in bid side
        assert Decimal("50000") in order_book.bid_side.price_levels
        
    def test_add_sell_order(self):
        """Test adding a sell order to the book"""
        order_book = OrderBook("BTC-USDT")
        
        order = Order(
            order_id="sell-1",
            symbol="BTC-USDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            price=Decimal("51000"),
            quantity=Decimal("1.0")
        )
        
        success = order_book.add_order(order)
        assert success == True
        assert "sell-1" in order_book.orders
        
        # Check order is in ask side
        assert Decimal("51000") in order_book.ask_side.price_levels
    
    def test_duplicate_order_rejection(self):
        """Test that duplicate order IDs are rejected"""
        order_book = OrderBook("BTC-USDT")
        
        order1 = Order(
            order_id="duplicate-id",
            symbol="BTC-USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("50000"),
            quantity=Decimal("1.0")
        )
        
        order2 = Order(
            order_id="duplicate-id",
            symbol="BTC-USDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            price=Decimal("51000"),
            quantity=Decimal("1.0")
        )
        
        success1 = order_book.add_order(order1)
        success2 = order_book.add_order(order2)
        
        assert success1 == True
        assert success2 == False
        assert len(order_book.orders) == 1
    
    def test_cancel_order(self):
        """Test cancelling an order"""
        order_book = OrderBook("BTC-USDT")
        
        order = Order(
            order_id="cancel-me",
            symbol="BTC-USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("50000"),
            quantity=Decimal("1.0")
        )
        
        order_book.add_order(order)
        assert "cancel-me" in order_book.orders
        
        cancelled = order_book.cancel_order("cancel-me")
        assert cancelled is not None
        assert cancelled.status == OrderStatus.CANCELLED
        assert "cancel-me" not in order_book.orders
        assert Decimal("50000") not in order_book.bid_side.price_levels
    
    def test_cancel_nonexistent_order(self):
        """Test cancelling a non-existent order"""
        order_book = OrderBook("BTC-USDT")
        cancelled = order_book.cancel_order("does-not-exist")
        assert cancelled is None
    
    def test_get_best_bid(self):
        """Test getting best bid"""
        order_book = OrderBook("BTC-USDT")
        
        # Empty book
        best_bid = order_book.get_best_bid()
        assert best_bid is None
        
        # Add buy orders
        order1 = Order(
            symbol="BTC-USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("49000"),
            quantity=Decimal("1.0")
        )
        
        order2 = Order(
            symbol="BTC-USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("50000"),
            quantity=Decimal("2.0")
        )
        
        order_book.add_order(order1)
        order_book.add_order(order2)
        
        best_bid = order_book.get_best_bid()
        assert best_bid is not None
        assert best_bid[0] == Decimal("50000")  # Best price
        assert best_bid[1] == Decimal("2.0")    # Total quantity at best price
    
    def test_get_best_ask(self):
        """Test getting best ask"""
        order_book = OrderBook("BTC-USDT")
        
        # Empty book
        best_ask = order_book.get_best_ask()
        assert best_ask is None
        
        # Add sell orders
        order1 = Order(
            symbol="BTC-USDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            price=Decimal("51000"),
            quantity=Decimal("1.5")
        )
        
        order2 = Order(
            symbol="BTC-USDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            price=Decimal("50500"),
            quantity=Decimal("0.5")
        )
        
        order_book.add_order(order1)
        order_book.add_order(order2)
        
        best_ask = order_book.get_best_ask()
        assert best_ask is not None
        assert best_ask[0] == Decimal("50500")  # Best price
        assert best_ask[1] == Decimal("0.5")    # Total quantity at best price
    
    def test_get_bbo(self):
        """Test getting Best Bid and Offer"""
        order_book = OrderBook("BTC-USDT")
        
        # Empty book
        bbo = order_book.get_bbo()
        assert bbo["symbol"] == "BTC-USDT"
        assert bbo["best_bid"] is None
        assert bbo["best_ask"] is None
        assert bbo["spread"] is None
        
        # Add orders
        buy_order = Order(
            symbol="BTC-USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("50000"),
            quantity=Decimal("2.0")
        )
        
        sell_order = Order(
            symbol="BTC-USDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            price=Decimal("50100"),
            quantity=Decimal("1.5")
        )
        
        order_book.add_order(buy_order)
        order_book.add_order(sell_order)
        
        bbo = order_book.get_bbo()
        assert bbo["symbol"] == "BTC-USDT"
        assert bbo["best_bid"]["price"] == "50000"
        assert bbo["best_bid"]["quantity"] == "2.0"
        assert bbo["best_ask"]["price"] == "50100"
        assert bbo["best_ask"]["quantity"] == "1.5"
        assert bbo["spread"] == "100"
    
    def test_get_depth(self):
        """Test getting order book depth"""
        order_book = OrderBook("BTC-USDT")
        
        # Add multiple buy orders
        for i in range(5):
            order = Order(
                symbol="BTC-USDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                price=Decimal(f"{50000 - i*100}"),
                quantity=Decimal(f"{i+1}.0")
            )
            order_book.add_order(order)
        
        # Add multiple sell orders
        for i in range(5):
            order = Order(
                symbol="BTC-USDT",
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                price=Decimal(f"{50100 + i*100}"),
                quantity=Decimal(f"{i+1}.5")
            )
            order_book.add_order(order)
        
        depth = order_book.get_depth(levels=3)
        
        assert depth["symbol"] == "BTC-USDT"
        assert len(depth["bids"]) == 3
        assert len(depth["asks"]) == 3
        
        # Check bid levels are sorted correctly (highest first)
        assert depth["bids"][0][0] == "50000"  # Best bid
        assert depth["bids"][1][0] == "49900"
        assert depth["bids"][2][0] == "49800"
        
        # Check ask levels are sorted correctly (lowest first)
        assert depth["asks"][0][0] == "50100"  # Best ask
        assert depth["asks"][1][0] == "50200"
        assert depth["asks"][2][0] == "50300"
    
    def test_time_priority_at_same_price(self):
        """Test that orders at the same price maintain time priority"""
        order_book = OrderBook("BTC-USDT")
        
        # Add multiple orders at the same price
        order1 = Order(
            order_id="first",
            symbol="BTC-USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("50000"),
            quantity=Decimal("1.0")
        )
        
        order2 = Order(
            order_id="second",
            symbol="BTC-USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("50000"),
            quantity=Decimal("2.0")
        )
        
        order3 = Order(
            order_id="third",
            symbol="BTC-USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("50000"),
            quantity=Decimal("3.0")
        )
        
        order_book.add_order(order1)
        order_book.add_order(order2)
        order_book.add_order(order3)
        
        # Check orders are maintained in time priority
        price_level = order_book.bid_side.price_levels[Decimal("50000")]
        assert len(price_level.orders) == 3
        assert price_level.orders[0].order_id == "first"
        assert price_level.orders[1].order_id == "second"
        assert price_level.orders[2].order_id == "third"
        assert price_level.total_quantity == Decimal("6.0")
    
    def test_price_level_cleanup(self):
        """Test that empty price levels are removed"""
        order_book = OrderBook("BTC-USDT")
        
        order = Order(
            order_id="cleanup-test",
            symbol="BTC-USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("50000"),
            quantity=Decimal("1.0")
        )
        
        order_book.add_order(order)
        assert Decimal("50000") in order_book.bid_side.price_levels
        
        order_book.cancel_order("cleanup-test")
        assert Decimal("50000") not in order_book.bid_side.price_levels