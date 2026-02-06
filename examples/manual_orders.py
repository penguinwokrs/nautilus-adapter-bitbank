#!/usr/bin/env python3
"""
Example: Manual Order Execution with Bitbank

This example demonstrates how to:
  - Place limit orders
  - Check order status
  - Cancel orders
  - Handle order responses

Requirements:
  - BITBANK_API_KEY and BITBANK_API_SECRET environment variables



Usage:
  python examples/manual_orders.py
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

from nautilus_bitbank.data import BitbankDataClient
from nautilus_bitbank.execution import BitbankExecutionClient
from nautilus_bitbank.config import BitbankDataClientConfig, BitbankExecClientConfig

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def main():
    api_key = os.getenv("BITBANK_API_KEY")
    api_secret = os.getenv("BITBANK_API_SECRET")
    
    if not api_key or not api_secret:
        print("Error: Set BITBANK_API_KEY and BITBANK_API_SECRET")
        return

    # Setup infrastructure
    loop = asyncio.get_event_loop()
    clock = LiveClock()
    trader_id = TraderId("MANUAL-ORDER")
    msgbus = MessageBus(trader_id=trader_id, clock=clock)
    cache = Cache(database=None)
    instrument_provider = InstrumentProvider()
    
    # Create clients
    data_config = BitbankDataClientConfig(api_key=api_key, api_secret=api_secret)
    data_client = BitbankDataClient(
        loop=loop, config=data_config, msgbus=msgbus, cache=cache, clock=clock
    )
    
    exec_config = BitbankExecClientConfig(
        api_key=api_key, 
        api_secret=api_secret, 
        use_pubnub=False  # Not needed for manual order management
    )
    exec_client = BitbankExecutionClient(
        loop=loop, config=exec_config, msgbus=msgbus, cache=cache,
        clock=clock, instrument_provider=instrument_provider
    )

    try:
        # Connect
        await data_client._connect()
        logger.info("Connected to Bitbank")
        
        # Fetch instruments
        instruments = await data_client.fetch_instruments()
        logger.info(f"Available instruments: {len(instruments)}")
        
        # Use XYM/JPY for demonstration (cheap, low minimum order)
        pair = "xym_jpy"
        symbol = "XYM/JPY"
        
        # Get current market price
        ticker_json = await data_client._rest_client.get_ticker_py(pair)
        ticker = json.loads(ticker_json)
        current_price = Decimal(ticker.get("last", "0"))
        
        print("\n" + "=" * 60)
        print(f"  {symbol} Current Price: ¥{current_price}")
        print("=" * 60)
        
        # === Example 1: Place a Limit BUY Order (won't fill) ===
        print("\n--- Example 1: Place Limit BUY Order ---")
        
        # Price 50% below market to avoid execution
        buy_price = str(current_price * Decimal("0.50"))
        order_amount = "1"  # 1 XYM
        
        print(f"Placing BUY order: {order_amount} {symbol} @ ¥{buy_price}")
        
        try:
            resp_json = await exec_client._rust_client.submit_order(
                pair,
                order_amount,
                "buy",           # side
                "limit",         # order_type
                "EXAMPLE-001",   # client_order_id
                buy_price        # price
            )
            resp = json.loads(resp_json)
            order_id = resp.get("order_id")
            status = resp.get("status")
            
            print(f"✅ Order placed!")
            print(f"   Order ID: {order_id}")
            print(f"   Status: {status}")
            
        except Exception as e:
            print(f"❌ Order failed: {e}")
            return
        
        # === Example 2: Check Order Status ===
        print("\n--- Example 2: Check Order Status ---")
        await asyncio.sleep(1)
        
        try:
            status_json = await exec_client._rust_client.get_order(pair, str(order_id))
            status_resp = json.loads(status_json)
            
            print(f"Order Status:")
            print(f"   Status: {status_resp.get('status')}")
            print(f"   Side: {status_resp.get('side')}")
            print(f"   Type: {status_resp.get('type')}")
            print(f"   Price: ¥{status_resp.get('price')}")
            print(f"   Amount: {status_resp.get('start_amount')}")
            print(f"   Executed: {status_resp.get('executed_amount')}")
            print(f"   Remaining: {status_resp.get('remaining_amount')}")
            
        except Exception as e:
            print(f"❌ Status check failed: {e}")
        
        # === Example 3: Cancel Order ===
        print("\n--- Example 3: Cancel Order ---")
        
        try:
            cancel_json = await exec_client._rust_client.cancel_order(pair, str(order_id))
            cancel_resp = json.loads(cancel_json)
            
            print(f"✅ Order cancelled!")
            print(f"   New Status: {cancel_resp.get('status')}")
            
        except Exception as e:
            print(f"❌ Cancel failed: {e}")
        
        # === Example 4: Get Active Orders ===
        print("\n--- Example 4: Get Active Orders ---")
        
        try:
            orders_json = await exec_client._rust_client.get_active_orders(pair)
            orders = json.loads(orders_json)
            
            if orders.get("orders"):
                print(f"Active orders: {len(orders['orders'])}")
                for o in orders["orders"][:5]:  # Show first 5
                    print(f"   - {o.get('order_id')}: {o.get('side')} {o.get('remaining_amount')} @ ¥{o.get('price')}")
            else:
                print("No active orders")
                
        except Exception as e:
            print(f"❌ Failed to get active orders: {e}")
        
        print("\n" + "=" * 60)
        print("  Demo Complete")
        print("=" * 60)
        
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
    finally:
        await data_client._disconnect()


if __name__ == "__main__":
    asyncio.run(main())
