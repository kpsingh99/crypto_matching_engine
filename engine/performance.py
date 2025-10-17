import time
import asyncio
from decimal import Decimal
from typing import Dict, List
import statistics
import json
from dataclasses import dataclass, asdict
from datetime import datetime

@dataclass
class PerformanceMetrics:
    """Container for performance metrics"""
    order_processing_latency_ms: float
    bbo_update_latency_ms: float
    trade_generation_latency_ms: float
    orders_per_second: float
    trades_per_second: float
    memory_usage_mb: float
    timestamp: datetime

class PerformanceMonitor:
    """Monitor and optimize matching engine performance"""
    
    def __init__(self):
        self.order_latencies = []
        self.bbo_latencies = []
        self.trade_latencies = []
        self.order_count = 0
        self.trade_count = 0
        self.start_time = time.time()
        
    def record_order_latency(self, latency_ms: float):
        """Record order processing latency"""
        self.order_latencies.append(latency_ms)
        self.order_count += 1
        # Keep only last 1000 samples
        if len(self.order_latencies) > 1000:
            self.order_latencies.pop(0)
    
    def record_bbo_latency(self, latency_ms: float):
        """Record BBO update latency"""
        self.bbo_latencies.append(latency_ms)
        if len(self.bbo_latencies) > 1000:
            self.bbo_latencies.pop(0)
    
    def record_trade_latency(self, latency_ms: float):
        """Record trade generation latency"""
        self.trade_latencies.append(latency_ms)
        self.trade_count += 1
        if len(self.trade_latencies) > 1000:
            self.trade_latencies.pop(0)
    
    def get_metrics(self) -> PerformanceMetrics:
        """Get current performance metrics"""
        elapsed_time = time.time() - self.start_time
        
        return PerformanceMetrics(
            order_processing_latency_ms=statistics.mean(self.order_latencies) if self.order_latencies else 0,
            bbo_update_latency_ms=statistics.mean(self.bbo_latencies) if self.bbo_latencies else 0,
            trade_generation_latency_ms=statistics.mean(self.trade_latencies) if self.trade_latencies else 0,
            orders_per_second=self.order_count / elapsed_time if elapsed_time > 0 else 0,
            trades_per_second=self.trade_count / elapsed_time if elapsed_time > 0 else 0,
            memory_usage_mb=self._get_memory_usage(),
            timestamp=datetime.utcnow()
        )
    
    def _get_memory_usage(self) -> float:
        """Get current memory usage in MB"""
        try:
            import psutil
            import os
            process = psutil.Process(os.getpid())
            return process.memory_info().rss / 1024 / 1024
        except ImportError:
            return 0.0  # psutil not installed
        except Exception:
            return 0.0
    
    def generate_report(self) -> str:
        """Generate performance analysis report"""
        metrics = self.get_metrics()
        
        # Handle empty latency lists
        if not self.order_latencies:
            return f"""
# Performance Analysis Report
Generated: {metrics.timestamp.isoformat()}

## Status
No orders processed yet. Performance metrics will be available after processing orders.

## Resource Usage
- Memory Usage: {metrics.memory_usage_mb:.2f} MB
"""
        
        report = f"""
# Performance Analysis Report
Generated: {metrics.timestamp.isoformat()}

## Latency Metrics
- Order Processing: {metrics.order_processing_latency_ms:.2f}ms avg
- BBO Update: {metrics.bbo_update_latency_ms:.2f}ms avg
- Trade Generation: {metrics.trade_generation_latency_ms:.2f}ms avg

## Throughput Metrics
- Orders per Second: {metrics.orders_per_second:.2f}
- Trades per Second: {metrics.trades_per_second:.2f}
- Total Orders Processed: {self.order_count}
- Total Trades Generated: {self.trade_count}

## Resource Usage
- Memory Usage: {metrics.memory_usage_mb:.2f} MB

## Latency Distribution (Order Processing)
- P50: {self._percentile(self.order_latencies, 50):.2f}ms
- P95: {self._percentile(self.order_latencies, 95):.2f}ms
- P99: {self._percentile(self.order_latencies, 99):.2f}ms
- Min: {min(self.order_latencies):.2f}ms
- Max: {max(self.order_latencies):.2f}ms

## Recommendations
{self._generate_recommendations(metrics)}
        """
        return report
    
    def _percentile(self, data: List[float], percentile: int) -> float:
        """Calculate percentile value"""
        if not data:
            return 0.0
        sorted_data = sorted(data)
        index = int(len(sorted_data) * percentile / 100)
        return sorted_data[min(index, len(sorted_data) - 1)]
    
    def _generate_recommendations(self, metrics: PerformanceMetrics) -> str:
        """Generate performance optimization recommendations"""
        recommendations = []
        
        if metrics.order_processing_latency_ms > 10:
            recommendations.append("- Consider implementing order caching to reduce latency")
        
        if metrics.memory_usage_mb > 500:
            recommendations.append("- High memory usage detected. Consider implementing order archival")
        
        if metrics.orders_per_second > 0 and metrics.orders_per_second < 1000:
            recommendations.append("- Consider using compiled Cython extensions for critical paths")
        
        if not recommendations:
            recommendations.append("- System performing optimally")
        
        return "\n".join(recommendations)

# Optimized data structures
class OptimizedOrderBook:
    """Memory-efficient order book with O(1) operations"""
    
    def __init__(self):
        self.buy_orders = {}  # price -> list of orders
        self.sell_orders = {}  # price -> list of orders
        self.order_index = {}  # order_id -> (side, price, index)
        
        # Pre-allocated memory pools for common operations
        self._order_pool = []
        self._trade_pool = []
    
    def add_order_optimized(self, order):
        """Add order with O(1) complexity"""
        # Reuse pooled objects when possible
        if self._order_pool:
            pooled = self._order_pool.pop()
            # Copy order data to pooled object
            pooled.__dict__.update(order.__dict__)
            order = pooled
        
        # Add to appropriate side
        orders_dict = self.buy_orders if order.side == "buy" else self.sell_orders
        
        if order.price not in orders_dict:
            orders_dict[order.price] = []
        
        orders_dict[order.price].append(order)
        
        # Update index
        self.order_index[order.order_id] = (
            order.side,
            order.price,
            len(orders_dict[order.price]) - 1
        )
    
    def remove_order_optimized(self, order_id):
        """Remove order with O(1) complexity"""
        if order_id not in self.order_index:
            return None
        
        side, price, index = self.order_index[order_id]
        orders_dict = self.buy_orders if side == "buy" else self.sell_orders
        
        if price in orders_dict and index < len(orders_dict[price]):
            order = orders_dict[price][index]
            
            # Swap with last element and pop (O(1))
            orders_dict[price][index] = orders_dict[price][-1]
            orders_dict[price].pop()
            
            # Update index for swapped order
            if orders_dict[price] and index < len(orders_dict[price]):
                swapped_order = orders_dict[price][index]
                self.order_index[swapped_order.order_id] = (side, price, index)
            
            # Clean up empty price level
            if not orders_dict[price]:
                del orders_dict[price]
            
            # Return to pool for reuse
            self._order_pool.append(order)
            
            del self.order_index[order_id]
            return order
        
        return None