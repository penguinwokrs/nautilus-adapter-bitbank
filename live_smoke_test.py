import asyncio
import os
import logging
from decimal import Decimal
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.cache.cache import Cache
from nautilus_trader.model.identifiers import TraderId, Venue
from nautilus_trader.common.providers import InstrumentProvider

from nautilus_bitbank.data import BitbankDataClient
from nautilus_bitbank.execution import BitbankExecutionClient
from nautilus_bitbank.config import BitbankDataClientConfig, BitbankExecClientConfig

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("LiveSmokeTest")

# Load credentials from environment variables
API_KEY = os.environ.get("BITBANK_API_KEY", "")
API_SECRET = os.environ.get("BITBANK_API_SECRET", "")

if not API_KEY or not API_SECRET:
    raise EnvironmentError("BITBANK_API_KEY and BITBANK_API_SECRET environment variables must be set")

async def main():
    logger.info("Starting Live Smoke Test...")
    
    loop = asyncio.get_event_loop()
    clock = LiveClock()
    trader_id = TraderId("SMOKE-TEST")
    msgbus = MessageBus(trader_id=trader_id, clock=clock)
    cache = Cache(database=None)
    
    # 1. Data Client Setup
    data_config = BitbankDataClientConfig(
        api_key=API_KEY,
        api_secret=API_SECRET,
    )
    data_client = BitbankDataClient(
        loop=loop,
        config=data_config,
        msgbus=msgbus,
        cache=cache,
        clock=clock
    )

    # 2. Execution Client Setup
    exec_config = BitbankExecClientConfig(
        api_key=API_KEY,
        api_secret=API_SECRET,
        use_pubnub=True
    )
    
    # We need an instrument provider for ExecutionClient
    instrument_provider = InstrumentProvider()
    
    exec_client = BitbankExecutionClient(
        loop=loop,
        config=exec_config,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
        instrument_provider=instrument_provider
    )

    try:
        # Connect Data Client
        logger.info("Connecting Data Client...")
        await data_client._connect()
        
        # Fetch Instruments
        logger.info("Fetching instruments...")
        instruments = await data_client.fetch_instruments()
        for inst in instruments:
            instrument_provider.add(inst)
        
        btc_jpy = [inst for inst in instruments if inst.id.symbol.value == "BTC/JPY"][0]
        logger.info(f"Found BTC/JPY: {btc_jpy.id}")

        # Subscribe to BTC/JPY
        logger.info("Subscribing to BTC/JPY...")
        await data_client.subscribe([btc_jpy])

        # Connect Execution Client
        logger.info("Connecting Execution Client...")
        await exec_client._connect()

        # Monitor for a while
        logger.info("Monitoring for 30 seconds... (Check for data flow in logs)")
        
        # Intercept handle_data to show we are getting things
        original_handle_data = data_client._handle_data
        received_types = set()
        
        def display_handle_data(data):
            type_name = type(data).__name__
            if type_name not in received_types:
                logger.info(f"FIRST RECEIVED DATA TYPE: {type_name}")
                received_types.add(type_name)
            original_handle_data(data)
            
        data_client._handle_data = display_handle_data

        await asyncio.sleep(30)
        
        logger.info(f"Received data types during test: {received_types}")
        
    except Exception as e:
        logger.error(f"Error during smoke test: {e}", exc_info=True)
    finally:
        logger.info("Cleaning up...")
        await data_client._disconnect()
        # exec_client doesn't have a full disconnect implemented yet but we'll stop the loop
        logger.info("Test finished.")

if __name__ == "__main__":
    asyncio.run(main())
