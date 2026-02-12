import pytest
import asyncio
import json
from unittest.mock import MagicMock

from nautilus_trader.model.identifiers import Venue, InstrumentId
from nautilus_trader.model.data import QuoteTick, TradeTick
from nautilus_trader.model.currencies import JPY

@pytest.mark.asyncio
async def test_connect_subscribe(data_client, mock_rust_data_client):
    """Test connection and subscription logic."""
    await data_client._connect()

    # Check if connect was called on the underlying Rust client
    assert data_client._rust_client.connect.called

    instrument = InstrumentId.from_str("BTC/JPY.BITBANK")

    from nautilus_trader.model.instruments import Instrument
    mock_instrument = MagicMock(spec=Instrument)
    mock_instrument.id = instrument

    await data_client.subscribe([mock_instrument])
    # Ensure it's in the internal map for the handler to find it
    data_client._subscribed_instruments["btc_jpy"] = MagicMock()
    data_client._subscribed_instruments["btc_jpy"].id = instrument

    # Verify subscribe called
    assert data_client._rust_client.subscribe.called
    expected_rooms = ["ticker_btc_jpy", "transactions_btc_jpy", "depth_whole_btc_jpy", "depth_diff_btc_jpy"]
    data_client._rust_client.subscribe.assert_called_with(expected_rooms)

@pytest.mark.asyncio
async def test_handle_ticker(data_client, mock_clock):
    """Test parsing of ticker messages."""
    instrument = InstrumentId.from_str("BTC/JPY.BITBANK")
    data_client._subscribed_instruments["btc_jpy"] = MagicMock()
    data_client._subscribed_instruments["btc_jpy"].id = instrument

    await data_client._connect()

    # Make call_soon_threadsafe execute synchronously for testing
    # (PubNub callbacks normally run on a background thread)
    data_client._loop = MagicMock()
    data_client._loop.call_soon_threadsafe = lambda fn, *args: fn(*args)

    from nautilus_bitbank import Ticker
    # Simulate incoming Rust object
    data_obj = Ticker(
        sell="1000000",
        buy="999000",
        high="1005000",
        low="990000",
        last="999500",
        vol="12.5",
        timestamp=1600000000000
    )

    # Manually trigger callback from Rust
    data_client._handle_rust_data("ticker_btc_jpy", data_obj)

    # Verify QuoteTick emitted via _handle_data (dispatched via call_soon_threadsafe)
    assert data_client._handle_data.called
    args = data_client._handle_data.call_args[0]
    tick: QuoteTick = args[0]

    assert tick.instrument_id.value == "BTC/JPY.BITBANK"
    assert tick.ask_price == 1000000
    assert tick.bid_price == 999000
    # Expected timestamp in ns: 1600000000000 * 1_000_000
    assert tick.ts_event == 1600000000000 * 1_000_000

@pytest.mark.asyncio
async def test_handle_transactions(data_client):
    """Test parsing of transaction messages."""
    instrument = InstrumentId.from_str("BTC/JPY.BITBANK")
    data_client._subscribed_instruments["btc_jpy"] = MagicMock()
    data_client._subscribed_instruments["btc_jpy"].id = instrument

    await data_client._connect()

    # Capture call_soon_threadsafe calls instead of executing them,
    # because _cache is a Cython property and cannot be replaced with a mock.
    threadsafe_calls = []
    data_client._loop = MagicMock()
    data_client._loop.call_soon_threadsafe = lambda fn, *args: threadsafe_calls.append((fn, args))

    from nautilus_bitbank import Transaction, Transactions
    tx = Transaction(
        transaction_id=12345,
        side="buy",
        price="1000000",
        amount="0.01",
        executed_at=1600000000000
    )
    data_obj = Transactions(transactions=[tx])

    data_client._handle_rust_data("transactions_btc_jpy", data_obj)

    # Verify _dispatch_trade was scheduled via call_soon_threadsafe
    assert len(threadsafe_calls) == 1
    fn, args = threadsafe_calls[0]
    # args = (client, tick) — extract the TradeTick
    tick: TradeTick = args[1]

    from nautilus_trader.model.objects import Quantity
    assert tick.price == 1000000
    assert tick.size == Quantity.from_str("0.01")
    from nautilus_trader.model.identifiers import TradeId
    assert tick.trade_id == TradeId("12345")

@pytest.mark.asyncio
async def test_handle_depth(data_client):
    """Test parsing of depth messages using OrderBook object."""
    instrument = InstrumentId.from_str("BTC/JPY.BITBANK")
    data_client._subscribed_instruments["btc_jpy"] = MagicMock()
    data_client._subscribed_instruments["btc_jpy"].id = instrument

    await data_client._connect()

    from nautilus_bitbank import OrderBook, Depth
    # Create a Rust managed OrderBook
    book = OrderBook("btc_jpy")
    depth = Depth(
        asks=[["1000001", "1.0"], ["1000002", "2.0"]],
        bids=[["999999", "3.0"], ["999998", "4.0"]],
        timestamp=1600000000000,
        s=100
    )
    book.apply_whole(depth)

    # Trigger callback
    data_client._handle_rust_data("depth_whole_btc_jpy", book)

    assert data_client._handle_data.called
    args = data_client._handle_data.call_args[0]
    from nautilus_trader.model.data import OrderBookDeltas
    snapshot: OrderBookDeltas = args[0]

    assert snapshot.instrument_id.value == "BTC/JPY.BITBANK"
    # CLEAR + 2 asks + 2 bids = 5 deltas
    assert len(snapshot.deltas) == 5
    from nautilus_trader.model.enums import BookAction
    assert snapshot.deltas[0].action == BookAction.CLEAR
