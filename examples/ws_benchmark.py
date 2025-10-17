# examples/ws_benchmark.py
import argparse, json, time, uuid, statistics
from websocket import create_connection

def bench(url, symbol, n_orders, side, order_type, price=None, qty=0.01):
    client_id = f"bench-{uuid.uuid4().hex[:8]}"
    ws = create_connection(f"{url}/{client_id}")
    # read the initial connection message
    try:
        ws.recv()
    except Exception:
        pass

    # subscribe (optional, but keeps server flow consistent)
    sub = {"type": "subscribe", "symbols": [symbol], "trades": True, "market_data": True}
    ws.send(json.dumps(sub))
    try:
        ws.recv()  # subscription_response
        ws.recv()  # initial market_data
    except Exception:
        pass

    latencies = []
    trades = 0
    for i in range(n_orders):
        msg = {
            "type": "order",
            "symbol": symbol,
            "side": side,                  # "buy" or "sell"
            "order_type": order_type,      # "market" or "limit"
            "quantity": qty
        }
        if order_type == "limit" and price is not None:
            msg["price"] = price

        t0 = time.perf_counter()
        ws.send(json.dumps(msg))
        # We wait for the corresponding order_response; skip other notifications
        while True:
            data = json.loads(ws.recv())
            if data.get("type") == "order_response":
                t1 = time.perf_counter()
                latencies.append((t1 - t0) * 1000.0)  # ms
                trades += len(data.get("trades", []))
                break
            # ignore "market_data" / "trade" interleavings

    ws.close()

    if not latencies:
        print("No latencies recorded.")
        return

    latencies.sort()
    p50 = statistics.median(latencies)
    p95 = latencies[int(0.95 * (len(latencies)-1))]
    p99 = latencies[int(0.99 * (len(latencies)-1))]
    avg = statistics.mean(latencies)
    ops = n_orders / sum(l/1000 for l in latencies)  # crude ops/sec over pure sum of per-req times

    print(f"Results for {n_orders} {order_type.upper()} {side.upper()} orders on {symbol}")
    print(f"Avg: {avg:.2f} ms  |  P50: {p50:.2f} ms  |  P95: {p95:.2f} ms  |  P99: {p99:.2f} ms")
    print(f"Approx orders/sec (seq): {ops:.1f}")
    print(f"Total trades reported in responses: {trades}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://localhost:8000/ws", help="WS base URL (no client id)")
    ap.add_argument("--symbol", default="BTC-USDT")
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--side", default="buy", choices=["buy","sell"])
    ap.add_argument("--type", dest="order_type", default="market", choices=["market","limit"])
    ap.add_argument("--price", type=float, default=None)
    ap.add_argument("--qty", type=float, default=0.01)
    args = ap.parse_args()
    bench(args.url, args.symbol, args.n, args.side, args.order_type, args.price, args.qty)
