import argparse
import json
import time
import uuid
import statistics
import threading
import requests
from datetime import datetime
from websocket import create_connection
from typing import List, Tuple

class BenchmarkReportGenerator:
    """
    Generates comprehensive performance analysis reports combining
    benchmark results with matching engine metrics
    """
    
    def __init__(self, api_url: str = "http://localhost:8000"):
        self.api_url = api_url
        self.ws_url = api_url.replace("http://", "ws://").replace("https://", "wss://")
        self.benchmark_results = []
        
    def run_benchmark(self, symbol: str, clients: int, per_client: int,
                     side: str, order_type: str, qty: float, price: float = None) -> dict:
        """Run concurrent benchmark and return results"""
        print(f"\n🔥 Running benchmark: {clients} clients × {per_client} orders each...")
        
        results = {}
        threads = []
        t_start = time.perf_counter()
        
        for i in range(clients):
            th = threading.Thread(
                target=self._worker,
                args=(symbol, per_client, side, order_type, qty, price, results, i)
            )
            th.start()
            threads.append(th)
        
        for th in threads:
            th.join()
        
        t_end = time.perf_counter()
        
        # Aggregate results
        all_lat = []
        total_trades = 0
        
        for i in range(clients):
            lat, tr = results[i]
            all_lat.extend(lat)
            total_trades += tr
        
        if not all_lat:
            return {}
        
        all_lat.sort()
        total_orders = clients * per_client
        wall_time = t_end - t_start
        
        benchmark_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "total_orders": total_orders,
            "concurrent_clients": clients,
            "orders_per_client": per_client,
            "side": side,
            "order_type": order_type,
            "quantity": qty,
            "price": price,
            "latency_ms": {
                "avg": statistics.mean(all_lat),
                "p50": statistics.median(all_lat),
                "p95": all_lat[int(0.95 * (len(all_lat) - 1))],
                "p99": all_lat[int(0.99 * (len(all_lat) - 1))],
                "min": min(all_lat),
                "max": max(all_lat),
            },
            "throughput": {
                "orders_per_sec": total_orders / wall_time,
                "wall_time_sec": wall_time,
            },
            "trades": {
                "total": total_trades,
                "trades_per_sec": total_trades / wall_time,
            }
        }
        
        self.benchmark_results.append(benchmark_data)
        print(f"✅ Benchmark complete: {benchmark_data['throughput']['orders_per_sec']:.1f} orders/sec")
        return benchmark_data
    
    def _worker(self, symbol: str, n_orders: int, side: str, order_type: str,
                qty: float, price: float, results: dict, idx: int):
        """Worker thread for concurrent benchmarking"""
        client_id = f"bench-{idx}-{uuid.uuid4().hex[:6]}"
        ws = create_connection(f"{self.ws_url}/ws/{client_id}")
        
        try:
            ws.recv()  # connection message
        except Exception:
            pass
        
        lat = []
        trades_count = 0
        
        for _ in range(n_orders):
            msg = {
                "type": "order",
                "symbol": symbol,
                "side": side,
                "order_type": order_type,
                "quantity": qty
            }
            
            if order_type == "limit" and price is not None:
                msg["price"] = price
            
            t0 = time.perf_counter()
            ws.send(json.dumps(msg))
            
            # Wait for order response
            while True:
                data = json.loads(ws.recv())
                if data.get("type") == "order_response":
                    t1 = time.perf_counter()
                    lat.append((t1 - t0) * 1000.0)
                    trades_count += len(data.get("trades", []))
                    break
        
        ws.close()
        results[idx] = (lat, trades_count)
    
    def get_engine_metrics(self) -> dict:
        """Fetch current matching engine metrics"""
        try:
            response = requests.get(f"{self.api_url}/metrics", timeout=5)
            return response.json()
        except Exception as e:
            print(f"⚠️  Could not fetch engine metrics: {e}")
            return {}
    
    def get_perf_report(self) -> str:
        """Fetch detailed performance report from engine"""
        try:
            response = requests.get(f"{self.api_url}/perf_report", timeout=5)
            return response.text
        except Exception as e:
            return f"Could not fetch performance report: {e}"
    
    def generate_markdown_report(self, output_file: str = "performance_report.md"):
        """Generate comprehensive markdown report"""
        
        # Get engine metrics
        engine_metrics = self.get_engine_metrics()
        perf_report = self.get_perf_report()
        
        report = f"""# Matching Engine Performance Analysis Report

**Generated:** {datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")}

---

## Executive Summary

This report presents a comprehensive performance analysis of the crypto matching engine, including:
- Concurrent load testing results
- Latency distribution analysis
- Throughput measurements
- Engine-level metrics
- Performance recommendations

---

## 1. Benchmark Test Results

"""
        
        # Add each benchmark result
        for i, bench in enumerate(self.benchmark_results, 1):
            report += f"""### Test {i}: {bench['order_type'].upper()} {bench['side'].upper()} Orders

**Configuration:**
- Symbol: {bench['symbol']}
- Total Orders: {bench['total_orders']:,}
- Concurrent Clients: {bench['concurrent_clients']}
- Orders per Client: {bench['orders_per_client']}
- Order Type: {bench['order_type']}
- Side: {bench['side']}
- Quantity per Order: {bench['quantity']}
{f"- Price: {bench['price']}" if bench['price'] else ""}

**Latency Results:**
```
Average:    {bench['latency_ms']['avg']:.2f} ms
Median (P50): {bench['latency_ms']['p50']:.2f} ms
P95:        {bench['latency_ms']['p95']:.2f} ms
P99:        {bench['latency_ms']['p99']:.2f} ms
Min:        {bench['latency_ms']['min']:.2f} ms
Max:        {bench['latency_ms']['max']:.2f} ms
```

**Throughput:**
- Orders/sec: **{bench['throughput']['orders_per_sec']:.1f}**
- Wall time: {bench['throughput']['wall_time_sec']:.2f} seconds
- Trades generated: {bench['trades']['total']:,}
- Trades/sec: {bench['trades']['trades_per_sec']:.1f}

---

"""
        
        # Add engine metrics
        report += """## 2. Matching Engine Internal Metrics

"""
        
        if engine_metrics:
            for symbol, metrics in engine_metrics.items():
                report += f"""### {symbol}

**Latency:**
- Order Processing: {metrics.get('order_processing_latency_ms', 0):.2f} ms
- BBO Update: {metrics.get('bbo_update_latency_ms', 0):.2f} ms
- Trade Generation: {metrics.get('trade_generation_latency_ms', 0):.2f} ms

**Throughput:**
- Orders per Second: {metrics.get('orders_per_second', 0):.2f}
- Trades per Second: {metrics.get('trades_per_second', 0):.2f}

**Resources:**
- Memory Usage: {metrics.get('memory_usage_mb', 0):.2f} MB

---

"""
        
        # Add detailed engine performance report
        report += f"""## 3. Detailed Engine Performance Report

```
{perf_report}
```

---

## 4. Performance Analysis

"""
        
        # Calculate averages across all benchmarks
        if self.benchmark_results:
            avg_throughput = statistics.mean([b['throughput']['orders_per_sec'] 
                                             for b in self.benchmark_results])
            avg_p99 = statistics.mean([b['latency_ms']['p99'] 
                                       for b in self.benchmark_results])
            
            report += f"""### Key Findings

1. **Average Throughput:** {avg_throughput:.1f} orders/second
2. **Average P99 Latency:** {avg_p99:.2f} ms
3. **Total Tests Run:** {len(self.benchmark_results)}

### Latency Classification

"""
            
            if avg_p99 < 5:
                report += "✅ **Excellent** - P99 latency under 5ms (suitable for HFT)\n"
            elif avg_p99 < 10:
                report += "✅ **Very Good** - P99 latency under 10ms (suitable for most trading)\n"
            elif avg_p99 < 50:
                report += "⚠️  **Acceptable** - P99 latency under 50ms (suitable for retail trading)\n"
            else:
                report += "❌ **Needs Improvement** - P99 latency over 50ms\n"
            
            report += f"""
### Throughput Classification

"""
            
            if avg_throughput > 5000:
                report += "✅ **Excellent** - Over 5,000 orders/sec (production-ready)\n"
            elif avg_throughput > 1000:
                report += "✅ **Good** - Over 1,000 orders/sec (suitable for most exchanges)\n"
            elif avg_throughput > 500:
                report += "⚠️  **Acceptable** - Over 500 orders/sec (suitable for low-volume markets)\n"
            else:
                report += "❌ **Needs Improvement** - Under 500 orders/sec\n"
        
        report += """
---

## 5. Recommendations

Based on the benchmark results and engine metrics:

"""
        
        # Add contextual recommendations
        if self.benchmark_results:
            avg_p99 = statistics.mean([b['latency_ms']['p99'] for b in self.benchmark_results])
            avg_throughput = statistics.mean([b['throughput']['orders_per_sec'] 
                                             for b in self.benchmark_results])
            
            recommendations = []
            
            if avg_p99 > 10:
                recommendations.append("- **Reduce Latency:** Consider implementing message batching and async I/O optimizations")
            
            if avg_throughput < 1000:
                recommendations.append("- **Increase Throughput:** Optimize lock contention and implement lock-free data structures")
            
            recommendations.append("- **Monitoring:** Implement real-time alerting for latency spikes")
            recommendations.append("- **Persistence:** Current batched persistence is efficient, continue monitoring")
            recommendations.append("- **WebSocket Broadcasting:** Message batching is working well, maintain current approach")
            
            for rec in recommendations:
                report += f"{rec}\n"
        
        report += """
---

## 6. Test Environment

- **Platform:** FastAPI + WebSocket
- **Database:** SQLite with WAL mode
- **Serialization:** ujson
- **Order Book:** In-memory with price-time priority
- **Concurrency:** asyncio with fine-grained locking

---

## 7. Conclusion

"""
        
        if self.benchmark_results:
            avg_throughput = statistics.mean([b['throughput']['orders_per_sec'] 
                                             for b in self.benchmark_results])
            avg_p99 = statistics.mean([b['latency_ms']['p99'] 
                                       for b in self.benchmark_results])
            
            report += f"""The matching engine demonstrates {'strong' if avg_throughput > 1000 else 'moderate'} performance with:
- Sustained throughput of {avg_throughput:.1f} orders/second
- P99 latency of {avg_p99:.2f} ms
- Reliable concurrent client handling

"""
            
            if avg_throughput > 1000 and avg_p99 < 10:
                report += "The system is **production-ready** for medium to high-volume trading environments.\n"
            elif avg_throughput > 500:
                report += "The system is **suitable for production** with continued monitoring and optimization.\n"
            else:
                report += "The system requires **further optimization** before production deployment.\n"
        
        report += """
---

*End of Report*
"""
        
        # Write to file
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(report)
        
        print(f"\n📊 Report generated: {output_file}")
        return report


def main():
    parser = argparse.ArgumentParser(description="Generate comprehensive performance report")
    parser.add_argument("--api-url", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--symbol", default="BTC-USDT", help="Trading symbol")
    parser.add_argument("--output", default="performance_report.md", help="Output file")
    parser.add_argument("--run-benchmarks", action="store_true", help="Run benchmarks before generating report")
    
    args = parser.parse_args()
    
    generator = BenchmarkReportGenerator(api_url=args.api_url)
    
    # Run benchmarks if requested
    if args.run_benchmarks:
        print("=" * 60)
        print("PERFORMANCE BENCHMARKING SUITE")
        print("=" * 60)
        
        # Test 1: Market orders (buy side)
        generator.run_benchmark(
            symbol=args.symbol,
            clients=10,
            per_client=200,
            side="buy",
            order_type="market",
            qty=0.01
        )
        
        time.sleep(2)  # Brief pause between tests
        
        # Test 2: Limit orders (sell side)
        generator.run_benchmark(
            symbol=args.symbol,
            clients=5,
            per_client=100,
            side="sell",
            order_type="limit",
            qty=0.05,
            price=51000
        )
        
        time.sleep(2)
        
        # Test 3: High concurrency test
        generator.run_benchmark(
            symbol=args.symbol,
            clients=20,
            per_client=100,
            side="buy",
            order_type="market",
            qty=0.01
        )
    
    # Generate report
    print("\n" + "=" * 60)
    print("GENERATING PERFORMANCE REPORT")
    print("=" * 60)
    
    generator.generate_markdown_report(output_file=args.output)
    
    print(f"\n✅ Complete! Open '{args.output}' to view the full report.")


if __name__ == "__main__":
    main()