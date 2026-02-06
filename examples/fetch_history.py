#!/usr/bin/env python3
"""
Example: Fetch and Save Historical Trade Data

This example demonstrates how to:
  - Connect to Bitbank API
  - Fetch recent trade history for a pair
  - Save data to CSV for backtesting

Requirements:
  - BITBANK_API_KEY and BITBANK_API_SECRET environment variables

Usage:
  python examples/fetch_history.py
"""
import asyncio
import os
import json
import csv
import logging
from datetime import datetime, timezone
from pathlib import Path

from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.cache.cache import Cache
from nautilus_trader.model.identifiers import TraderId

from nautilus_bitbank.data import BitbankDataClient
from nautilus_bitbank.config import BitbankDataClientConfig

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def fetch_trades(data_client, pair: str, count: int = 1000):
    """Fetch recent trades for a pair."""
    try:
        # Use the underlying REST client
        trades_json = await data_client._rest_client.get_transactions_py(pair)
        trades = json.loads(trades_json)
        
        if isinstance(trades, list):
            return trades[:count]
        elif isinstance(trades, dict) and "transactions" in trades:
            return trades["transactions"][:count]
        else:
            return []
    except Exception as e:
        logger.error(f"Failed to fetch trades: {e}")
        return []


async def fetch_orderbook(data_client, pair: str):
    """Fetch current order book snapshot."""
    try:
        ob_json = await data_client._rest_client.get_depth_py(pair)
        return json.loads(ob_json)
    except Exception as e:
        logger.error(f"Failed to fetch orderbook: {e}")
        return None


def save_trades_csv(trades: list, pair: str, output_dir: Path):
    """Save trades to CSV file."""
    filename = output_dir / f"{pair}_trades_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    with open(filename, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'trade_id', 'side', 'price', 'amount'])
        
        for trade in trades:
            timestamp = trade.get('executed_at', '')
            if isinstance(timestamp, int):
                # Convert milliseconds to datetime
                dt = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
                timestamp = dt.isoformat()
            
            writer.writerow([
                timestamp,
                trade.get('transaction_id', ''),
                trade.get('side', ''),
                trade.get('price', ''),
                trade.get('amount', '')
            ])
    
    return filename


def save_orderbook_csv(orderbook: dict, pair: str, output_dir: Path):
    """Save order book snapshot to CSV."""
    filename = output_dir / f"{pair}_orderbook_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    with open(filename, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['side', 'price', 'amount'])
        
        # Bids (buy orders)
        for bid in orderbook.get('bids', []):
            writer.writerow(['bid', bid[0], bid[1]])
        
        # Asks (sell orders)
        for ask in orderbook.get('asks', []):
            writer.writerow(['ask', ask[0], ask[1]])
    
    return filename


async def main():
    api_key = os.getenv("BITBANK_API_KEY")
    api_secret = os.getenv("BITBANK_API_SECRET")
    
    if not api_key or not api_secret:
        print("Error: Set BITBANK_API_KEY and BITBANK_API_SECRET")
        return

    # Create output directory
    output_dir = Path("data")
    output_dir.mkdir(exist_ok=True)
    
    loop = asyncio.get_event_loop()
    clock = LiveClock()
    trader_id = TraderId("DATA-FETCH")
    msgbus = MessageBus(trader_id=trader_id, clock=clock)
    cache = Cache(database=None)
    
    config = BitbankDataClientConfig(api_key=api_key, api_secret=api_secret)
    data_client = BitbankDataClient(
        loop=loop, config=config, msgbus=msgbus, cache=cache, clock=clock
    )

    try:
        await data_client._connect()
        print("Connected to Bitbank")
        
        # List of pairs to fetch
        pairs = ["btc_jpy", "eth_jpy", "xrp_jpy"]
        
        print("\n" + "=" * 50)
        print("  Fetching Historical Data")
        print("=" * 50)
        
        for pair in pairs:
            symbol = pair.upper().replace("_", "/")
            print(f"\n--- {symbol} ---")
            
            # Fetch recent trades
            print("Fetching recent trades...")
            trades = await fetch_trades(data_client, pair, count=500)
            
            if trades:
                filename = save_trades_csv(trades, pair, output_dir)
                print(f"✅ Saved {len(trades)} trades to {filename}")
            else:
                print("❌ No trades fetched")
            
            # Fetch order book
            print("Fetching order book snapshot...")
            orderbook = await fetch_orderbook(data_client, pair)
            
            if orderbook:
                filename = save_orderbook_csv(orderbook, pair, output_dir)
                bid_count = len(orderbook.get('bids', []))
                ask_count = len(orderbook.get('asks', []))
                print(f"✅ Saved orderbook ({bid_count} bids, {ask_count} asks) to {filename}")
            else:
                print("❌ No orderbook fetched")
            
            # Small delay between pairs
            await asyncio.sleep(0.5)
        
        print("\n" + "=" * 50)
        print(f"  Data saved to {output_dir.absolute()}")
        print("=" * 50)
        
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
    finally:
        await data_client._disconnect()


if __name__ == "__main__":
    asyncio.run(main())
