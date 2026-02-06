import asyncio
import os
import signal
from typing import Optional

from nautilus_trader.model.identifiers import Venue, InstrumentId
from nautilus_trader.release import __version__
from nautilus_trader.common.component import MessageBus, LiveClock
from nautilus_trader.common.actor import Actor
from nautilus_trader.live.msgbus import LiveMessageBus
from nautilus_trader.cache.cache import Cache
from nautilus_trader.config import StreamingConfig

from nautilus_bitbank.config import BitbankDataClientConfig
from nautilus_bitbank.data import BitbankDataClient

# Simple printer to show received data
class DataPrinter(Actor):
    def on_start(self):
        self.msgbus.subscribe_instrument_data(self.process_msg)

    def process_msg(self, msg):
        print(f"[DataPrinter] Received: {msg}")

async def main():
    print(f"Nautilus Trader v{__version__}")
    
    api_key = os.getenv("BITBANK_API_KEY")
    api_secret = os.getenv("BITBANK_API_SECRET")
    
    if not api_key or not api_secret:
        print("Please set BITBANK_API_KEY and BITBANK_API_SECRET env vars.")
        return

    # 1. Setup Infrastructure
    clock = LiveClock()
    msgbus = LiveMessageBus()
    cache = Cache(database=None)
    
    # 2. Configure Bitbank Client
    config = BitbankDataClientConfig(
        api_key=api_key,
        api_secret=api_secret,
    )
    
    client = BitbankDataClient(
        loop=asyncio.get_running_loop(),
        config=config,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
    )

    # 3. Setup Printer Actor
    printer = DataPrinter(clock, msgbus, cache)
    await printer.start()

    # 4. Connect and Subscribe
    await client.connect()
    
    # Needs valid InstrumentId. Bitbank symbols are usually lower case in API, 
    # but Nautilus uses generic Symbol objects.
    # The adapter handles parsing "BTC/JPY" -> "btc_jpy" internally.
    instrument_id = InstrumentId.from_str("BTC/JPY.BITBANK")
    
    print("Subscribing to Quote Ticks (Ticker)...")
    await client.subscribe_quote_ticks(instrument_id)
    
    print("Subscribing to Order Book (Whole Depth)...")
    await client.subscribe_order_book_snapshots(instrument_id)

    # 5. Run until interrupted
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)
        
    print("Press Ctrl+C to stop...")
    await stop_event.wait()
    
    await client.disconnect()
    await printer.stop()

if __name__ == "__main__":
    asyncio.run(main())
