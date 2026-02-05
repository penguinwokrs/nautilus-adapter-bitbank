from typing import Optional
from nautilus_trader.config import LiveDataClientConfig, LiveExecClientConfig

class BitbankDataClientConfig(LiveDataClientConfig):
    api_key: str  # Mandatory
    api_secret: str  # Mandatory

class BitbankExecClientConfig(LiveExecClientConfig):
    api_key: str  # Mandatory
    api_secret: str  # Mandatory
