"""
Factory classes for Bitbank Data and Execution clients.
These are used by TradingNode to instantiate the clients.
"""

from nautilus_trader.live.factories import LiveDataClientFactory, LiveExecClientFactory
from nautilus_trader.common.providers import InstrumentProvider

from .data import BitbankDataClient
from .execution import BitbankExecutionClient


class BitbankDataClientFactory(LiveDataClientFactory):
    """Factory for creating BitbankDataClient instances."""
    
    @classmethod
    def create(cls, loop, msgbus, cache, clock, name=None, config=None, **kwargs):
        if config is None:
            raise ValueError("Config required for BitbankDataClient")
        return BitbankDataClient(loop, config, msgbus, cache, clock)


class BitbankExecutionClientFactory(LiveExecClientFactory):
    """Factory for creating BitbankExecutionClient instances."""
    
    @classmethod
    def create(cls, loop, msgbus, cache, clock, instrument_provider=None, name=None, config=None, **kwargs):
        if config is None:
            raise ValueError("Config required for BitbankExecutionClient")
        
        if instrument_provider is None:
            if isinstance(cache, InstrumentProvider):
                instrument_provider = cache
            else:
                # Create a wrapper that adapts Cache to InstrumentProvider
                class CacheWrapper(InstrumentProvider):
                    def __init__(self, inner_cache):
                        self._cache = inner_cache
                    
                    def instrument(self, instrument_id):
                        return self._cache.instrument(instrument_id)

                instrument_provider = CacheWrapper(cache)

        return BitbankExecutionClient(loop, config, msgbus, cache, clock, instrument_provider)
