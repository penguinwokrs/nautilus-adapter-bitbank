from typing import Optional
from nautilus_trader.config import LiveDataClientConfig, LiveExecClientConfig

class BitbankDataClientConfig(LiveDataClientConfig):
    api_key: Optional[str] = None
    api_secret: Optional[str] = None

    def __post_init__(self):
        if not self.api_key or not self.api_secret:
            raise ValueError("BitbankDataClientConfig requires both api_key and api_secret")

class BitbankExecClientConfig(LiveExecClientConfig):
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    use_pubnub: bool = True  # Enable/Disable real-time PubNub updates
    
    def __post_init__(self):
        if not self.api_key or not self.api_secret:
            raise ValueError("BitbankExecClientConfig requires both api_key and api_secret")
