import pytest
import pytest_asyncio
from decimal import Decimal
from datetime import datetime
from engine.matching_engine import MatchingEngine
from engine.order_types import Order, OrderSide, OrderType, OrderStatus

@pytest_asyncio.fixture
async def engine():
    """Create a test matching engine"""
    return MatchingEngine("BTC-USDT")

@pytest.mark.asyncio
async def test_market_order_execution(engine):
    """Test market order execution with price-time priority"""
    # Add limit orders to book
    sell_order1 = Order(
        symbol="BTC-USDT",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        price=Decimal("50000"),
        quantity=Decimal("1.0")
    )
    
    sell_order2 = Order(
        symbol="BTC-USDT",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        price=Decimal("50100"),
        quantity=Decimal("0.5")
    )
    
    await engine.submit_order(sell_order1)
    await engine.submit_order(sell_order2)
    
    # Submit market buy order
    buy_order = Order(
        symbol="BTC-USDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1.2")
    )
    
    success, msg, trades = await engine.submit_order(buy_order)
    
    assert success
    assert len(trades) == 2
    assert trades[0].price == Decimal("50000")  # Best price first
    assert trades[0].quantity == Decimal("1.0")
    assert trades[1].price == Decimal("50100")  # Then next best
    assert trades[1].quantity == Decimal("0.2")
    assert buy_order.status == OrderStatus.FILLED

@pytest.mark.asyncio
async def test_limit_order_as_maker(engine):
    """Test limit order resting on book"""
    order = Order(
        symbol="BTC-USDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        price=Decimal("49000"),
        quantity=Decimal("2.0")
    )
    
    success, msg, trades = await engine.submit_order(order)
    
    assert success
    assert len(trades) == 0  # No immediate match
    assert order.order_id in engine.order_book.orders
    assert order.status == OrderStatus.PENDING

@pytest.mark.asyncio
async def test_ioc_order_partial_fill(engine):
    """Test IOC order with partial fill"""
    # Add liquidity
    sell_order = Order(
        symbol="BTC-USDT",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        price=Decimal("50000"),
        quantity=Decimal("0.5")
    )
    await engine.submit_order(sell_order)
    
    # Submit IOC order for more than available
    ioc_order = Order(
        symbol="BTC-USDT",
        side=OrderSide.BUY,
        order_type=OrderType.IOC,
        quantity=Decimal("1.0")
    )
    
    success, msg, trades = await engine.submit_order(ioc_order)
    
    assert success
    assert len(trades) == 1
    assert trades[0].quantity == Decimal("0.5")
    assert ioc_order.filled_quantity == Decimal("0.5")
    assert ioc_order.status == OrderStatus.PARTIALLY_FILLED

@pytest.mark.asyncio
async def test_fok_order_full_execution(engine):
    """Test FOK order that can be fully filled"""
    # Add sufficient liquidity
    sell_order = Order(
        symbol="BTC-USDT",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        price=Decimal("50000"),
        quantity=Decimal("2.0")
    )
    await engine.submit_order(sell_order)
    
    # Submit FOK order
    fok_order = Order(
        symbol="BTC-USDT",
        side=OrderSide.BUY,
        order_type=OrderType.FOK,
        quantity=Decimal("1.5")
    )
    
    success, msg, trades = await engine.submit_order(fok_order)
    
    assert success
    assert len(trades) == 1
    assert trades[0].quantity == Decimal("1.5")
    assert fok_order.status == OrderStatus.FILLED

@pytest.mark.asyncio
async def test_fok_order_cancellation(engine):
    """Test FOK order cancellation when cannot fill completely"""
    # Add insufficient liquidity
    sell_order = Order(
        symbol="BTC-USDT",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        price=Decimal("50000"),
        quantity=Decimal("0.5")
    )
    await engine.submit_order(sell_order)
    
    # Submit FOK order for more than available
    fok_order = Order(
        symbol="BTC-USDT",
        side=OrderSide.BUY,
        order_type=OrderType.FOK,
        quantity=Decimal("1.0")
    )
    
    success, msg, trades = await engine.submit_order(fok_order)
    
    assert success
    assert len(trades) == 0  # No trades executed
    assert fok_order.status == OrderStatus.CANCELLED

@pytest.mark.asyncio
async def test_price_time_priority(engine):
    """Test strict price-time priority in matching"""
    # Add multiple orders at same price
    order1 = Order(
        symbol="BTC-USDT",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        price=Decimal("50000"),
        quantity=Decimal("1.0")
    )
    
    await asyncio.sleep(0.001)  # Ensure different timestamps
    
    order2 = Order(
        symbol="BTC-USDT",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        price=Decimal("50000"),
        quantity=Decimal("1.0")
    )
    
    await engine.submit_order(order1)
    await engine.submit_order(order2)
    
    # Submit market buy
    buy_order = Order(
        symbol="BTC-USDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.5")
    )
    
    success, msg, trades = await engine.submit_order(buy_order)
    
    assert trades[0].maker_order_id == order1.order_id  # First order matched first

@pytest.mark.asyncio
async def test_bbo_calculation(engine):
    """Test Best Bid and Offer calculation"""
    # Add orders
    buy_order = Order(
        symbol="BTC-USDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        price=Decimal("49900"),
        quantity=Decimal("2.0")
    )
    
    sell_order = Order(
        symbol="BTC-USDT",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        price=Decimal("50100"),
        quantity=Decimal("1.5")
    )
    
    await engine.submit_order(buy_order)
    await engine.submit_order(sell_order)
    
    bbo = engine.order_book.get_bbo()
    
    assert bbo["best_bid"]["price"] == "49900"
    assert bbo["best_bid"]["quantity"] == "2.0"
    assert bbo["best_ask"]["price"] == "50100"
    assert bbo["best_ask"]["quantity"] == "1.5"
    assert bbo["spread"] == "200"

@pytest.mark.asyncio
async def test_fee_calculation(engine):
    """Test maker-taker fee calculation"""
    # Add maker order
    maker_order = Order(
        symbol="BTC-USDT",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        price=Decimal("50000"),
        quantity=Decimal("1.0")
    )
    await engine.submit_order(maker_order)
    
    # Submit taker order
    taker_order = Order(
        symbol="BTC-USDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1.0")
    )
    
    success, msg, trades = await engine.submit_order(taker_order)
    
    trade = trades[0]
    expected_maker_fee = Decimal("50000") * Decimal("1.0") * Decimal("0.001")
    expected_taker_fee = Decimal("50000") * Decimal("1.0") * Decimal("0.002")
    
    assert trade.maker_fee == expected_maker_fee
    assert trade.taker_fee == expected_taker_fee