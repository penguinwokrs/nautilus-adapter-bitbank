import asyncio
import os
import json
import logging
from decimal import Decimal
from typing import List

from nautilus_trader.live.data_client import LiveDataClient
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue, ClientId
from nautilus_trader.model.currencies import Currency, JPY
from nautilus_trader.model.objects import Price, Quantity

# Import our adapter
from nautilus_bitbank.data import BitbankDataClient
from nautilus_bitbank.config import BitbankDataClientConfig

async def test_reconnection():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("test_reconnect")

    api_key = os.getenv("BITBANK_API_KEY", "")
    api_secret = os.getenv("BITBANK_API_SECRET", "")

    config = BitbankDataClientConfig(api_key=api_key, api_secret=api_secret)
    
    # Mock dependencies
    loop = asyncio.get_event_loop()
    msgbus = None 
    cache = None
    clock = None

    # We need real cache for subscribe potentially, or just mock it.
    class MockCache:
        def add_instrument(self, x): pass
        def instrument(self, x): return None

    class MockClock:
        def timestamp_ns(self): return 0

    client = BitbankDataClient(loop, config, msgbus, MockCache(), MockClock())

    logger.info("Starting initial connection...")
    await client._connect()
    
    logger.info("Initial connection successful. Waiting 5s...")
    await asyncio.sleep(5)

    logger.info("Simulating disconnect by calling the internal callback...")
    # This should trigger _on_ws_disconnect -> _reconnect_safe -> _connect
    client._on_ws_disconnect()

    logger.info("Reconnection should be happening in background with exponential backoff if it fails...")
    await asyncio.sleep(15)
    
    logger.info("Shutting down...")
    await client._disconnect()

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    asyncio.run(test_reconnection())
