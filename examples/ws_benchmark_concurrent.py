import argparse, json, time, uuid, statistics, threading
from websocket import create_connection

def worker(url, symbol, n_orders, side, order_type, qty, price, results, idx):
    client_id = f"bench-{idx}-{uuid.uuid4().hex[:6]}"
    ws = create_connection(f"{url}/{client_id}")
    try:
        ws.recv()  # connection
    except Exception:
        pass
    
    lat = []
    trades_count = 0
    for _ in range(n_orders):
        msg = {
            "type":"order",
            "symbol": symbol,
            "side": side,
            "order_type": order_type,
            "quantity": qty
        }
        if order_type == "limit" and price is not None:
            msg["price"] = price

        t0 = time.perf_counter()
        ws.send(json.dumps(msg))
        # Wait for this order's response (ignore market_data/trade noise)
        while True:
            data = json.loads(ws.recv())
            if data.get("type") == "order_response":
                t1 = time.perf_counter()
                lat.append((t1 - t0) * 1000.0)
                trades_count += len(data.get("trades", []))
                break
    ws.close()
    results[idx] = (lat, trades_count)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://localhost:8000/ws")
    ap.add_argument("--symbol", default="BTC-USDT")
    ap.add_argument("--clients", type=int, default=10)
    ap.add_argument("--per_client", type=int, default=200)
    ap.add_argument("--side", default="buy", choices=["buy","sell"])
    ap.add_argument("--type", dest="order_type", default="market", choices=["market","limit"])
    ap.add_argument("--qty", type=float, default=0.01)
    ap.add_argument("--price", type=float, default=None)
    args = ap.parse_args()

    results = {}
    threads = []
    t_start = time.perf_counter()
    for i in range(args.clients):
        th = threading.Thread(target=worker,
            args=(args.url, args.symbol, args.per_client, args.side, args.order_type, args.qty, args.price, results, i))
        th.start()
        threads.append(th)
    for th in threads:
        th.join()
    t_end = time.perf_counter()

    # Aggregate
    all_lat = []
    total_trades = 0
    for i in range(args.clients):
        lat, tr = results[i]
        all_lat.extend(lat)
        total_trades += tr

    if not all_lat:
        print("No latencies recorded.")
        return

    all_lat.sort()
    p50 = statistics.median(all_lat)
    p95 = all_lat[int(0.95 * (len(all_lat)-1))]
    p99 = all_lat[int(0.99 * (len(all_lat)-1))]
    avg = statistics.mean(all_lat)

    total_orders = args.clients * args.per_client
    wall_time = (t_end - t_start)
    throughput = total_orders / wall_time

    print(f"Concurrent results for {total_orders} {args.order_type.upper()} {args.side.upper()} orders")
    print(f"Avg: {avg:.2f} ms  |  P50: {p50:.2f} ms  |  P95: {p95:.2f} ms  |  P99: {p99:.2f} ms")
    print(f"Throughput (orders/sec across all clients): {throughput:.1f}")
    print(f"Total trades reported: {total_trades}")

if __name__ == "__main__":
    main()
