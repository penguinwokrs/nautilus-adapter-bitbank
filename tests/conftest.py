import asyncio
import pytest
import json
from unittest.mock import MagicMock, AsyncMock

from nautilus_trader.config import StreamingConfig
from nautilus_trader.model.identifiers import TraderId, Venue
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.cache.cache import Cache

from nautilus_bitbank.config import BitbankDataClientConfig, BitbankExecClientConfig
from nautilus_bitbank.data import BitbankDataClient
from nautilus_bitbank.execution import BitbankExecutionClient

@pytest.fixture
def mock_clock():
    return LiveClock()

@pytest.fixture(scope="function")
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
def mock_msgbus(event_loop):
    bus = MessageBus(
        trader_id=TraderId("TEST-BUS"),
        clock=LiveClock(),
    )
    # Monkeypatch methods that might be missing or need mocking
    # attributes cannot be set on cython class instance
    return bus

@pytest.fixture
def mock_cache():
    return Cache(database=None)

@pytest.fixture
def data_config():
    return BitbankDataClientConfig(
        api_key="test_key",
        api_secret="test_secret",
    )

@pytest.fixture
def exec_config():
    return BitbankExecClientConfig(
        api_key="test_key",
        api_secret="test_secret",
        use_pubnub=True,
    )

class ManualMockRustDataClient:
    def __init__(self):
        self.connect = AsyncMock()
        self.disconnect = AsyncMock()
        self.subscribe = AsyncMock()
        self.set_data_callback = MagicMock()

@pytest.fixture
def mock_rust_data_client(monkeypatch):
    import nautilus_bitbank.data as data_module
    
    class Factory:
        instance = None
        
    def MockClass():
        inst = ManualMockRustDataClient()
        Factory.instance = inst
        return inst

    monkeypatch.setattr(data_module.bitbank, "BitbankDataClient", MockClass)
    return Factory

class ManualMockRustExecutionClient:
    def __init__(self, key, secret, sub_key, timeout_ms, proxy_url):
        self.key = key
        self.secret = secret
        self.sub_key = sub_key
        self.timeout_ms = timeout_ms
        self.proxy_url = proxy_url
        self.submit_order = AsyncMock()
        self.cancel_order = AsyncMock()
        self.connect = AsyncMock()
        self.set_order_callback = MagicMock()
        self.get_order = AsyncMock()
        self.get_trade_history = AsyncMock()

@pytest.fixture
def mock_rust_execution_client(monkeypatch):
    import nautilus_bitbank.execution as exec_module
    
    class Factory:
        instance = None

    def MockClient(key, secret, sub_key, timeout_ms, proxy_url):
        inst = ManualMockRustExecutionClient(key, secret, sub_key, timeout_ms, proxy_url)
        Factory.instance = inst
        # Default return values
        inst.submit_order.return_value = json.dumps({"order_id": 123456789})
        inst.get_order.return_value = json.dumps({"order_id": 123456789, "status": "UNFILLED"})
        return inst

    monkeypatch.setattr(exec_module.bitbank, "BitbankExecutionClient", MockClient)
    return Factory

@pytest.fixture
def data_client(event_loop, data_config, mock_msgbus, mock_cache, mock_clock, mock_rust_data_client):
    client = BitbankDataClient(
        loop=event_loop,
        config=data_config,
        msgbus=mock_msgbus,
        cache=mock_cache,
        clock=mock_clock,
    )
    
    if mock_rust_data_client.instance:
        client._rust_client = mock_rust_data_client.instance
    
    # Mock _handle_data to avoid dependency on MessageBus implementation details
    client._handle_data = MagicMock()
    return client

@pytest.fixture
def exec_client(event_loop, exec_config, mock_msgbus, mock_cache, mock_clock, mock_rust_execution_client):
    provider = MagicMock(spec=InstrumentProvider)
    
    client = BitbankExecutionClient(
        loop=event_loop,
        config=exec_config,
        msgbus=mock_msgbus,
        cache=mock_cache,
        clock=mock_clock,
        instrument_provider=provider,
    )
    
    # Ensure mocks
    if mock_rust_execution_client.instance:
        client._rust_client = mock_rust_execution_client.instance
    
    # Patch for tests expecting _active_orders
    if not hasattr(client, "_active_orders"):
        client._active_orders = {}
    if not hasattr(client, "_order_states"):
        client._order_states = {}
        
    return client
