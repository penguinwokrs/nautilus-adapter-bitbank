from typing import Optional
from nautilus_trader.config import LiveDataClientConfig, LiveExecClientConfig

class BitbankDataClientConfig(LiveDataClientConfig):
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    timeout_ms: int = 10000
    proxy_url: Optional[str] = None
    use_pubnub: bool = True  # Enable/Disable real-time PubNub updates (default: True)
    order_book_depth: int = 20  # How many levels to pass from Rust to Python (Top N)

    def __post_init__(self):
        if not self.api_key or not self.api_secret:
            raise ValueError("BitbankDataClientConfig requires both api_key and api_secret")

class BitbankExecClientConfig(LiveExecClientConfig):
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    use_pubnub: bool = True  # Enable/Disable real-time PubNub updates
    pubnub_subscribe_key: str = "sub-c-e12e9174-dd60-11e6-806b-02ee2ddab7fe"
    timeout_ms: int = 10000
    proxy_url: Optional[str] = None
    
    def __post_init__(self):
        if not self.api_key or not self.api_secret:
            raise ValueError("BitbankExecClientConfig requires both api_key and api_secret")
