import logging
import os
import signal
import sys

from nautilus_trader.config import TradingNodeConfig, LoggingConfig
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.identifiers import Venue, InstrumentId, TraderId

from nautilus_bitbank.config import BitbankDataClientConfig, BitbankExecClientConfig
from nautilus_bitbank.factories import BitbankLiveFactory

def main():
    # Setup Logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    
    api_key = os.getenv("BITBANK_API_KEY")
    api_secret = os.getenv("BITBANK_API_SECRET")
    
    if not api_key or not api_secret:
        print("Error: BITBANK_API_KEY and BITBANK_API_SECRET must be set.")
        sys.exit(1)

    # 1. Configure the Node
    node_config = TradingNodeConfig(
        trader_id=TraderId("TEST-TRADER-001"),
        logging=LoggingConfig(log_level="INFO"),
    )
    
    node = TradingNode(config=node_config)

    # 2. Configure Bitbank Adapter
    # Using the Factory pattern which is standard in Nautilus
    bitbank_factory = BitbankLiveFactory(
        venue=Venue("BITBANK"),
        data_config=BitbankDataClientConfig(
            api_key=api_key,
            api_secret=api_secret,
        ),
        exec_config=BitbankExecClientConfig(
            api_key=api_key,
            api_secret=api_secret,
            use_pubnub=True, # Enable real-time updates
        ),
    )

    # 3. Add to Node
    node.add_data_client_factory(bitbank_factory)
    node.add_exec_client_factory(bitbank_factory)
    
    # 4. Build and Start
    node.build()
    
    # Subscribe to data manually (or usually done by Strategy)
    instrument_id = InstrumentId.from_str("BTC/JPY.BITBANK")
    
    print("Starting Node...")
    # Using run() is blocking for simple scripts, 
    # but we can also use stop() via signals if needed.
    # However, node.run() handles signals by default.
    
    # Before run, we should probably add a strategy or just subscribe directly
    # But for a raw node example, let's just connect.
    
    # Note: connect() is usually automatic in run(), but let's be explicit if needed.
    # Actually, node.run() will start everything.
    
    # To demonstrate data flow, we can't easily hook cleanly without a strategy
    # in this simple script unless we access node.data_engine.
    
    try:
        node.run()
    except KeyboardInterrupt:
        node.stop()
        print("Node stopped.")

if __name__ == "__main__":
    main()
