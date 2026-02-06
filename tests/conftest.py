import asyncio
import pytest
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

class ManualMockWebSocketClient:
    def __init__(self):
        self.connect_py_called = False
        self.subscribe_called = False
        self.set_callback_called = False
        self.set_disconnect_callback_called = False
        self.calls = []

    async def connect_py(self):
        print("DEBUG: ManualMockWebSocketClient.connect_py called")
        self.connect_py_called = True
        self.calls.append(("connect_py", ()))
        return "CONNECTED"

    async def connect(self, uri=None):
        print("DEBUG: ManualMockWebSocketClient.connect called")
        self.calls.append(("connect", (uri,)))
        return "CONNECTED"

    async def disconnect(self):
        pass

    async def subscribe(self, *args):
        self.subscribe_called = True
        self.calls.append(("subscribe", args))

    def set_callback(self, cb):
        self.set_callback_called = True

    def set_disconnect_callback(self, cb):
        self.set_disconnect_callback_called = True

    # helper to check if called (mock interface)
    @property
    def called(self):
        return len(self.calls) > 0 # generic called check

@pytest.fixture
def mock_rust_websocket(monkeypatch):
    import nautilus_bitbank.data as data_module
    
    # We return the class, but monkeypatch needs the class name 
    # to be instantiated by BitbankDataClient. 
    # But BitbankDataClient instantiates it as bitbank.BitbankWebSocketClient()
    
    # We need a way to return the instance to the test
    
    # Strategy: define a global or closure variable to hold the last instance
    
    class Factory:
        instance = None
        
    def MockClass():
        instance = ManualMockWebSocketClient()
        Factory.instance = instance
        return instance

    monkeypatch.setattr(data_module.bitbank, "BitbankWebSocketClient", MockClass)
    return Factory # returns a factory/holder so tests can access the instance

class ManualMockRestClient:
    def __init__(self, key, secret):
        self.key = key
        self.secret = secret
        self.create_order_py_calls = []
        self.cancel_order_py_calls = []
        self.create_order_py_return = "{}"
        self.cancel_order_py_return = "{}"
        # For methods that need standard Mock interface
        self.create_order_py_mock = MagicMock() 
        self.cancel_order_py_mock = MagicMock()
        self.get_order_py = AsyncMock()
        self.get_trade_history_py = AsyncMock()
        self.get_pubnub_auth_py = AsyncMock(return_value='{"pubnub_channel": "ch", "pubnub_token": "tk"}')

    async def create_order_py(self, *args):
        self.create_order_py_calls.append(args)
        # Delegate to MagicMock for assertions or return value
        self.create_order_py_mock(*args) # record call
        return self.create_order_py_mock.return_value or self.create_order_py_return

    async def cancel_order_py(self, *args):
        self.cancel_order_py_calls.append(args)
        self.cancel_order_py_mock(*args)
        return self.cancel_order_py_mock.return_value or self.cancel_order_py_return

class ManualMockPubNubClient:
    def __init__(self):
        self.connect_py = AsyncMock()
        self.stop_py = AsyncMock()
        self.set_callback = MagicMock()

@pytest.fixture
def mock_rust_rest_and_pubnub(monkeypatch):
    import nautilus_bitbank.execution as exec_module
    
    class Factory:
        rest_instance = None
        pubnub_instance = None

    def RestMock(key, secret):
        inst = ManualMockRestClient(key, secret)
        Factory.rest_instance = inst
        # Connect the inner AsyncMock's return_value to attribute for easier setting in tests
        inst.create_order_py_mock.return_value = None 
        inst.cancel_order_py_mock.return_value = None
        return inst
        
    def PubNubMock():
        inst = ManualMockPubNubClient()
        Factory.pubnub_instance = inst
        return inst

    monkeypatch.setattr(exec_module.bitbank, "BitbankRestClient", RestMock)
    monkeypatch.setattr(exec_module.bitbank, "PubNubClient", PubNubMock, raising=False)
    
    return Factory

@pytest.fixture
def data_client(event_loop, data_config, mock_msgbus, mock_cache, mock_clock, mock_rust_websocket):
    client = BitbankDataClient(
        loop=event_loop,
        config=data_config,
        msgbus=mock_msgbus,
        cache=mock_cache,
        clock=mock_clock,
    )
    # Ensure client uses our mock instance
    # Since we monkeypatched the class, client._ws_client should be our ManualMockWebSocketClient
    # Monkeypatching extension modules is flaky. Ensure the mock is used.
    client._ws_client = mock_rust_websocket.instance
    
    # Mock _handle_data to avoid dependency on MessageBus implementation details
    client._handle_data = MagicMock()
    return client

@pytest.fixture
def exec_client(event_loop, exec_config, mock_msgbus, mock_cache, mock_clock, mock_rust_rest_and_pubnub):
    provider = MagicMock(spec=InstrumentProvider)
    # provider needs to pass strict type checks?
    # If MagicMock fails, we might need a real stub. 
    # But let's assume monkeypatching Rest/PubNub works.
    
    client = BitbankExecutionClient(
        loop=event_loop,
        config=exec_config,
        msgbus=mock_msgbus,
        cache=mock_cache,
        clock=mock_clock,
        instrument_provider=provider,
    )
    
    # Ensure mocks
    if mock_rust_rest_and_pubnub.rest_instance:
        client._client = mock_rust_rest_and_pubnub.rest_instance
    if mock_rust_rest_and_pubnub.pubnub_instance:
        client._pubnub_client = mock_rust_rest_and_pubnub.pubnub_instance
        
    return client
