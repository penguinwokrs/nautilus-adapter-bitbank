#!/usr/bin/env python3
"""
Example: Multi-Symbol Data Subscription

This example demonstrates how to:
  - Fetch all available instruments from Bitbank
  - Subscribe to multiple trading pairs simultaneously
  - Monitor real-time price movements across pairs

Requirements:
  - BITBANK_API_KEY and BITBANK_API_SECRET environment variables

Usage:
  python examples/multi_symbol.py
"""
import asyncio
import os
import json
import logging
from datetime import datetime
from decimal import Decimal

from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.cache.cache import Cache
from nautilus_trader.model.identifiers import TraderId
from nautilus_trader.model.data import QuoteTick

from nautilus_bitbank.data import BitbankDataClient
from nautilus_bitbank.config import BitbankDataClientConfig

logging.basicConfig(level=logging.WARNING)  # Reduce noise
logger = logging.getLogger(__name__)


class MultiSymbolMonitor:
    """Monitor multiple symbols and display price changes."""
    
    def __init__(self):
        self.prices = {}  # symbol -> {bid, ask, last_update}
        self.initial_prices = {}
        
    def update(self, tick: QuoteTick):
        """Update price for a symbol."""
        symbol = str(tick.instrument_id.symbol)
        
        current = {
            "bid": float(tick.bid_price),
            "ask": float(tick.ask_price),
            "time": datetime.now()
        }
        
        if symbol not in self.initial_prices:
            self.initial_prices[symbol] = current["ask"]
        
        self.prices[symbol] = current
        
    def display(self):
        """Display current prices in a formatted table."""
        print("\033[2J\033[H")  # Clear screen
        print("=" * 70)
        print(f"  Bitbank Multi-Symbol Monitor - {datetime.now().strftime('%H:%M:%S')}")
        print("=" * 70)
        print(f"{'Symbol':<12} {'Bid':>14} {'Ask':>14} {'Change':>10}")
        print("-" * 70)
        
        for symbol in sorted(self.prices.keys()):
            data = self.prices[symbol]
            initial = self.initial_prices.get(symbol, data["ask"])
            
            if initial > 0:
                change_pct = ((data["ask"] - initial) / initial) * 100
                change_str = f"{change_pct:+.2f}%"
                
                # Color coding
                if change_pct > 0:
                    change_str = f"\033[92m{change_str}\033[0m"  # Green
                elif change_pct < 0:
                    change_str = f"\033[91m{change_str}\033[0m"  # Red
            else:
                change_str = "N/A"
            
            print(f"{symbol:<12} {data['bid']:>14,.3f} {data['ask']:>14,.3f} {change_str:>10}")
        
        print("-" * 70)
        print(f"Tracking {len(self.prices)} symbols. Press Ctrl+C to stop.")


async def main():
    api_key = os.getenv("BITBANK_API_KEY")
    api_secret = os.getenv("BITBANK_API_SECRET")
    
    if not api_key or not api_secret:
        print("Error: Set BITBANK_API_KEY and BITBANK_API_SECRET")
        return

    loop = asyncio.get_event_loop()
    clock = LiveClock()
    trader_id = TraderId("MULTI-SYMBOL")
    msgbus = MessageBus(trader_id=trader_id, clock=clock)
    cache = Cache(database=None)
    
    config = BitbankDataClientConfig(api_key=api_key, api_secret=api_secret)
    data_client = BitbankDataClient(
        loop=loop, config=config, msgbus=msgbus, cache=cache, clock=clock
    )
    
    monitor = MultiSymbolMonitor()

    try:
        await data_client._connect()
        print("Connected to Bitbank")
        
        # Fetch all instruments
        instruments = await data_client.fetch_instruments()
        print(f"Found {len(instruments)} instruments")
        
        # Select top JPY pairs by volume (or just pick popular ones)
        popular_pairs = [
            "BTC/JPY", "ETH/JPY", "XRP/JPY", "SOL/JPY", 
            "DOGE/JPY", "ADA/JPY", "DOT/JPY", "LINK/JPY"
        ]
        
        selected = [inst for inst in instruments 
                    if inst.id.symbol.value in popular_pairs]
        
        print(f"Subscribing to {len(selected)} pairs...")
        
        # Subscribe to each
        for inst in selected:
            await data_client.subscribe([inst])
            print(f"  Subscribed: {inst.id.symbol}")
        
        # Intercept data handling
        original_handle = data_client._handle_data
        
        def on_data(data):
            if isinstance(data, QuoteTick):
                monitor.update(data)
            original_handle(data)
        
        data_client._handle_data = on_data
        
        print("\nStarting monitor (updates every 2 seconds)...")
        await asyncio.sleep(2)
        
        # Main loop
        while True:
            monitor.display()
            await asyncio.sleep(2)
            
    except KeyboardInterrupt:
        print("\nStopping...")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
    finally:
        await data_client._disconnect()
        print("Disconnected.")


if __name__ == "__main__":
    asyncio.run(main())
