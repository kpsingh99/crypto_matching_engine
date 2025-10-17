import asyncio
import json
import websockets
from datetime import datetime

async def main():
    uri = "ws://localhost:8000/ws/demo-client"
    
    async with websockets.connect(uri, ping_interval=20, ping_timeout=20) as ws:
        print("=" * 60)
        print("CONNECTED TO MATCHING ENGINE")
        print("=" * 60)
        
        # 1. Wait for connection confirmation
        conn_msg = await ws.recv()
        conn_data = json.loads(conn_msg)
        print(f"\n✓ Connection: {conn_data}")
        print(f"  Available symbols: {conn_data.get('available_symbols', [])}")
        
        # 2. Subscribe to market data + trades
        print("\n📡 Subscribing to BTC-USDT...")
        await ws.send(json.dumps({
            "type": "subscribe",
            "symbols": ["BTC-USDT"],
            "trades": True,
            "market_data": True
        }))
        
        # Wait for subscription response
        sub_msg = await ws.recv()
        sub_data = json.loads(sub_msg)
        print(f"✓ Subscription: {sub_data}")
        
        # Wait for initial market data
        init_md = await ws.recv()
        init_data = json.loads(init_md)
        print(f"\n📊 Initial Market Data:")
        print(f"  BBO: {init_data.get('bbo', {})}")
        print(f"  Depth: Bids={len(init_data.get('depth', {}).get('bids', []))}, Asks={len(init_data.get('depth', {}).get('asks', []))}")
        
        # 3. Add liquidity (maker order)
        print("\n💰 Placing SELL limit order (maker)...")
        await ws.send(json.dumps({
            "type": "order",
            "symbol": "BTC-USDT",
            "side": "sell",
            "order_type": "limit",
            "price": 50000,
            "quantity": 1.0
        }))
        
        maker_response = json.loads(await ws.recv())
        print(f"✓ Maker Order Response:")
        print(f"  Order ID: {maker_response.get('order_id', '')[:8]}...")
        print(f"  Status: {maker_response.get('status')}")
        print(f"  Filled: {maker_response.get('filled_quantity')}")
        
        # Small delay to let market data update
        await asyncio.sleep(0.1)
        
        # 4. Take liquidity (taker order)
        print("\n🎯 Placing BUY market order (taker)...")
        await ws.send(json.dumps({
            "type": "order",
            "symbol": "BTC-USDT",
            "side": "buy",
            "order_type": "market",
            "quantity": 0.4
        }))
        
        taker_response = json.loads(await ws.recv())
        print(f"✓ Taker Order Response:")
        print(f"  Order ID: {taker_response.get('order_id', '')[:8]}...")
        print(f"  Status: {taker_response.get('status')}")
        print(f"  Filled: {taker_response.get('filled_quantity')}")
        print(f"  Trades: {len(taker_response.get('trades', []))}")
        
        # 5. Listen for broadcasts
        print("\n📻 Listening for broadcasts (trade + market data updates)...")
        print("-" * 60)
        
        for i in range(5):  # Listen for next 5 messages
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                data = json.loads(msg)
                msg_type = data.get("type", "unknown")
                
                if msg_type == "trade":
                    print(f"\n🔔 TRADE BROADCAST:")
                    print(f"   Price: {data.get('price')}")
                    print(f"   Quantity: {data.get('quantity')}")
                    print(f"   Side: {data.get('aggressor_side')}")
                    print(f"   Time: {data.get('timestamp', '')[:19]}")
                    
                elif msg_type == "market_data":
                    bbo = data.get('bbo', {})
                    print(f"\n📈 MARKET DATA UPDATE:")
                    print(f"   Best Bid: {bbo.get('best_bid', {}).get('price', 'N/A')}")
                    print(f"   Best Ask: {bbo.get('best_ask', {}).get('price', 'N/A')}")
                    print(f"   Spread: {bbo.get('spread', 'N/A')}")
                    
                else:
                    print(f"\n📨 {msg_type.upper()}: {data}")
                    
            except asyncio.TimeoutError:
                print(f"\n⏱️  No more broadcasts (timeout)")
                break
        
        print("\n" + "=" * 60)
        print("TEST COMPLETE")
        print("=" * 60)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")