import time
import json
import asyncio
import psutil
from nautilus_bitbank.data import BitbankDataClient
from nautilus_bitbank.config import BitbankDataClientConfig
from nautilus_trader.model.identifiers import TraderId
from nautilus_trader.common.component import MessageBus, LiveClock
from nautilus_trader.cache.cache import Cache

async def benchmark_throughput():
    print("Starting Performance Benchmark...")
    
    # Setup
    config = BitbankDataClientConfig(api_key="bench", api_secret="bench")
    
    # Real Nautilus components to satisfy typed arguments
    clock = LiveClock()
    trader_id = TraderId("BENCH-001")
    msgbus = MessageBus(trader_id=trader_id, clock=clock)
    cache = Cache(database=None)
    
    client = BitbankDataClient(
        loop=asyncio.get_event_loop(),
        config=config,
        msgbus=msgbus,
        cache=cache,
        clock=clock
    )
    
    # Mock the internal handle_data to measure speed
    processed_count = 0
    def mock_handle_data(snapshot):
        nonlocal processed_count
        processed_count += 1
        
    client._handle_data = mock_handle_data
    
    # Create objects directly from Rust classes
    try:
        from nautilus_bitbank import OrderBook, Depth
    except ImportError:
        from _nautilus_bitbank import OrderBook, Depth

    book = OrderBook("btc_jpy")
    asks = [[str(10000 + i), "0.1"] for i in range(100)]
    bids = [[str(9999 - i), "0.1"] for i in range(100)]
    ts = time.time_ns() // 1000000
    
    depth = Depth(asks, bids, ts, 100)
    book.apply_whole(depth)
    
    room_name = "depth_whole_btc_jpy"
    
    print(f"Benchmark using Rust-managed OrderBook object...")
    
    # Warm up
    for _ in range(100):
        client._handle_rust_data(room_name, book)
        
    # Measure
    start_time = time.time()
    iterations = 10000
    
    process = psutil.Process()
    cpu_before = process.cpu_percent()
    mem_before = process.memory_info().rss / (1024 * 1024)
    
    for i in range(iterations):
        client._handle_rust_data(room_name, book)
        if i % 1000 == 0:
            print(f"Processed {i} items...")
            
    end_time = time.time()
    cpu_after = process.cpu_percent()
    mem_after = process.memory_info().rss / (1024 * 1024)
    
    duration = end_time - start_time
    ops_per_sec = iterations / duration
    
    print("\n--- Results ---")
    print(f"Total Iterations: {iterations}")
    print(f"Total Duration: {duration:.4f} seconds")
    print(f"Throughput: {ops_per_sec:.2f} messages/sec")
    print(f"Avgerage Latency: {(duration/iterations)*1000:.4f} ms/message")
    print(f"Memory Usage: {mem_before:.2f} MB -> {mem_after:.2f} MB")
    print(f"CPU Usage Change: {cpu_before}% -> {cpu_after}% (Note: cpu_percent() is sampled)")

if __name__ == "__main__":
    asyncio.run(benchmark_throughput())
