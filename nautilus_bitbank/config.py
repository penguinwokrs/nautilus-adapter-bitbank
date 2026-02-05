from typing import Optional

from nautilus_trader.config import LiveDataClientConfig
from nautilus_trader.config import LiveExecClientConfig


class BitbankDataClientConfig(LiveDataClientConfig):
    api_key: Optional[str] = None
    api_secret: Optional[str] = None


class BitbankExecClientConfig(LiveExecClientConfig):
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
