#!/usr/bin/env python3
"""
Example: Simple Moving Average Crossover Strategy for Bitbank

This example demonstrates how to create a simple trading strategy
using the Bitbank adapter with Nautilus Trader.

Requirements:
  - BITBANK_API_KEY and BITBANK_API_SECRET environment variables

Usage:
  python examples/simple_strategy.py
"""
import asyncio
import os
import logging
from decimal import Decimal
from collections import deque

from nautilus_trader.config import TradingNodeConfig, LoggingConfig, StrategyConfig
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.identifiers import Venue, InstrumentId, TraderId
from nautilus_trader.model.data import QuoteTick
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.trading.strategy import Strategy

from nautilus_bitbank.config import BitbankDataClientConfig, BitbankExecClientConfig
from nautilus_bitbank.factories import BitbankLiveFactory

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SimpleMAConfig(StrategyConfig):
    """Configuration for Simple Moving Average Strategy."""
    instrument_id: str = "BTC/JPY.BITBANK"
    short_period: int = 5
    long_period: int = 20
    order_size: str = "0.0001"  # Minimum BTC order size


class SimpleMAStrategy(Strategy):
    """
    A simple Moving Average Crossover strategy.
    
    - BUY when short MA crosses above long MA
    - SELL when short MA crosses below long MA
    
    This is for demonstration purposes only - not for production use!
    """
    
    def __init__(self, config: SimpleMAConfig):
        super().__init__(config)
        self.instrument_id = InstrumentId.from_str(config.instrument_id)
        self.short_period = config.short_period
        self.long_period = config.long_period
        self.order_size = Decimal(config.order_size)
        
        # Price history for MA calculation
        self.prices = deque(maxlen=config.long_period)
        self.position_open = False
        
    def on_start(self):
        """Called when strategy starts."""
        self.log.info(f"Starting SimpleMA Strategy for {self.instrument_id}")
        self.log.info(f"Short MA: {self.short_period}, Long MA: {self.long_period}")
        
        # Subscribe to quote ticks
        self.subscribe_quote_ticks(self.instrument_id)
        
    def on_quote_tick(self, tick: QuoteTick):
        """Called when a new quote tick is received."""
        mid_price = (tick.bid_price + tick.ask_price) / 2
        self.prices.append(float(mid_price))
        
        # Need enough data for long MA
        if len(self.prices) < self.long_period:
            return
        
        # Calculate MAs
        short_ma = sum(list(self.prices)[-self.short_period:]) / self.short_period
        long_ma = sum(self.prices) / len(self.prices)
        
        # Log current state
        self.log.debug(f"Price: {mid_price:.0f}, Short MA: {short_ma:.0f}, Long MA: {long_ma:.0f}")
        
        # Trading logic (demonstration only - no real orders)
        if short_ma > long_ma and not self.position_open:
            self.log.info(f"🔵 BUY SIGNAL: Short MA ({short_ma:.0f}) > Long MA ({long_ma:.0f})")
            # In production, you would place an order here:
            # self.submit_market_order(self.instrument_id, OrderSide.BUY, self.order_size)
            self.position_open = True
            
        elif short_ma < long_ma and self.position_open:
            self.log.info(f"🔴 SELL SIGNAL: Short MA ({short_ma:.0f}) < Long MA ({long_ma:.0f})")
            # In production, you would place an order here:
            # self.submit_market_order(self.instrument_id, OrderSide.SELL, self.order_size)
            self.position_open = False
    
    def on_stop(self):
        """Called when strategy stops."""
        self.log.info("Strategy stopped")


def main():
    api_key = os.getenv("BITBANK_API_KEY")
    api_secret = os.getenv("BITBANK_API_SECRET")
    
    if not api_key or not api_secret:
        print("Error: Set BITBANK_API_KEY and BITBANK_API_SECRET environment variables")
        return

    # Configure the trading node
    node = TradingNode(config=TradingNodeConfig(
        trader_id=TraderId("STRATEGY-001"),
        logging=LoggingConfig(log_level="INFO"),
    ))

    # Add Bitbank adapter
    bitbank_factory = BitbankLiveFactory(
        venue=Venue("BITBANK"),
        data_config=BitbankDataClientConfig(
            api_key=api_key,
            api_secret=api_secret,
        ),
        exec_config=BitbankExecClientConfig(
            api_key=api_key,
            api_secret=api_secret,
            use_pubnub=True,
        ),
    )
    
    node.add_data_client_factory(bitbank_factory)
    node.add_exec_client_factory(bitbank_factory)
    
    # Add strategy
    strategy = SimpleMAStrategy(config=SimpleMAConfig(
        instrument_id="BTC/JPY.BITBANK",
        short_period=5,
        long_period=20,
    ))
    node.trader.add_strategy(strategy)
    
    # Build and run
    node.build()
    
    print("=" * 50)
    print("  Simple MA Strategy - Bitbank BTC/JPY")
    print("  Press Ctrl+C to stop")
    print("=" * 50)
    
    try:
        node.run()
    except KeyboardInterrupt:
        node.stop()
        print("Node stopped.")


if __name__ == "__main__":
    main()
