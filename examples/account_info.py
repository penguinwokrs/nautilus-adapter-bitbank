#!/usr/bin/env python3
"""
Example: Account Balance and Asset Management

This example demonstrates how to:
  - Fetch account balances
  - View available and locked assets
  - Display deposit/withdrawal addresses (if available)

Requirements:
  - BITBANK_API_KEY and BITBANK_API_SECRET environment variables

Usage:
  python examples/account_info.py
"""
import asyncio
import os
import json
import logging
from decimal import Decimal

from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.cache.cache import Cache
from nautilus_trader.model.identifiers import TraderId
from nautilus_trader.common.providers import InstrumentProvider

from nautilus_bitbank.execution import BitbankExecutionClient
from nautilus_bitbank.config import BitbankExecClientConfig

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def main():
    api_key = os.getenv("BITBANK_API_KEY")
    api_secret = os.getenv("BITBANK_API_SECRET")
    
    if not api_key or not api_secret:
        print("Error: Set BITBANK_API_KEY and BITBANK_API_SECRET")
        return

    loop = asyncio.get_event_loop()
    clock = LiveClock()
    trader_id = TraderId("ACCOUNT-INFO")
    msgbus = MessageBus(trader_id=trader_id, clock=clock)
    cache = Cache(database=None)
    instrument_provider = InstrumentProvider()
    
    exec_config = BitbankExecClientConfig(
        api_key=api_key, 
        api_secret=api_secret, 
        use_pubnub=False
    )
    exec_client = BitbankExecutionClient(
        loop=loop, config=exec_config, msgbus=msgbus, cache=cache,
        clock=clock, instrument_provider=instrument_provider
    )

    try:
        print("\n" + "=" * 60)
        print("  Bitbank Account Information")
        print("=" * 60)
        
        # Fetch assets
        print("\n--- Account Balances ---")
        
        try:
            assets_json = await exec_client._rust_client.get_assets()
            assets = json.loads(assets_json)
            
            if not assets.get("assets"):
                print("No assets found")
            else:
                print(f"\n{'Asset':<10} {'Available':>18} {'Locked':>18} {'Total':>18}")
                print("-" * 64)
                
                total_jpy_value = Decimal("0")
                
                for asset in assets["assets"]:
                    symbol = asset.get("asset", "").upper()
                    available = Decimal(asset.get("free_amount", "0") or "0")
                    locked = Decimal(asset.get("locked_amount", "0") or "0")
                    total = available + locked
                    
                    # Only show non-zero balances
                    if total > 0:
                        print(f"{symbol:<10} {available:>18.8f} {locked:>18.8f} {total:>18.8f}")
                        
                        # Track JPY value
                        if symbol == "JPY":
                            total_jpy_value += total
                
                print("-" * 64)
                if total_jpy_value > 0:
                    print(f"Total JPY Balance: ¥{total_jpy_value:,.0f}")
                    
        except Exception as e:
            print(f"❌ Failed to fetch assets: {e}")
        
        # Fetch active orders summary
        print("\n--- Active Orders Summary ---")
        
        pairs_to_check = ["btc_jpy", "eth_jpy", "xrp_jpy"]
        total_orders = 0
        
        for pair in pairs_to_check:
            try:
                orders_json = await exec_client._rust_client.get_active_orders(pair)
                orders = json.loads(orders_json)
                
                order_list = orders.get("orders", [])
                if order_list:
                    print(f"\n{pair.upper().replace('_', '/')}: {len(order_list)} active order(s)")
                    for o in order_list[:3]:  # Show first 3
                        side = o.get("side", "").upper()
                        price = o.get("price", "")
                        remaining = o.get("remaining_amount", "")
                        print(f"  • {side} {remaining} @ ¥{price}")
                    if len(order_list) > 3:
                        print(f"  ... and {len(order_list) - 3} more")
                    total_orders += len(order_list)
                    
            except Exception as e:
                # May fail if pair doesn't have orders, that's OK
                pass
        
        if total_orders == 0:
            print("No active orders")
        else:
            print(f"\nTotal active orders: {total_orders}")
        
        # Trade history summary
        print("\n--- Recent Trade Summary ---")
        
        for pair in pairs_to_check[:1]:  # Just BTC/JPY for brevity
            try:
                trades_json = await exec_client._rust_client.get_trade_history(pair, "0")
                trades = json.loads(trades_json)
                
                trade_list = trades.get("trades", [])
                if trade_list:
                    print(f"\n{pair.upper().replace('_', '/')}: Last {min(5, len(trade_list))} trades")
                    for t in trade_list[:5]:
                        side = t.get("side", "").upper()
                        price = t.get("price", "")
                        amount = t.get("amount", "")
                        print(f"  • {side} {amount} @ ¥{price}")
                        
            except Exception as e:
                print(f"Could not fetch trade history: {e}")
        
        print("\n" + "=" * 60)
        
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
