import pytest
import asyncio
import json
from unittest.mock import MagicMock

from nautilus_trader.model.identifiers import Venue, InstrumentId
from nautilus_trader.model.data import QuoteTick, TradeTick
from nautilus_trader.model.currencies import JPY

@pytest.mark.asyncio
async def test_connect_subscribe(data_client, mock_rust_websocket):
    """Test connection and subscription logic."""
    data_client.connect()
    # connect() is synchronous but launches a task. Wait a bit for the task to run.
    await asyncio.sleep(0.1)
    
    # Check if connect was called on the underlying Rust client
    assert data_client._ws_client.connect_py_called
    # assert data_client._ws_client.set_callback_called # This is called in __init__, so always true
    # assert data_client._ws_client.set_disconnect_callback_called

    instrument = InstrumentId.from_str("BTC/JPY.BITBANK")
    
    await data_client.subscribe_quote_ticks(instrument)
    # Ensure it's in the internal map for the handler to find it
    data_client._subscribed_instruments[instrument.value] = MagicMock()
    data_client._subscribed_instruments[instrument.value].id = instrument
    
    # Bitbank uses lower case pair names: btc_jpy
    expected_pair = "btc_jpy"
    
    # Verify subscribe called
    assert data_client._ws_client.subscribe_called
    
    last_call = data_client._ws_client.calls[-1]
    assert last_call[0] == "subscribe"
    
@pytest.mark.asyncio
async def test_handle_ticker(data_client, mock_clock):
    """Test parsing of ticker messages."""
    instrument = InstrumentId.from_str("BTC/JPY.BITBANK")
    data_client._subscribed_instruments[instrument.value] = MagicMock()
    data_client._subscribed_instruments[instrument.value].id = instrument

    data_client.connect()
    await asyncio.sleep(0.1)
    
    # Simulate incoming JSON message
    # Ticker format: {"room_name": "ticker_btc_jpy", "message": {"data": {...}}}
    msg_json = json.dumps({
        "room_name": "ticker_btc_jpy",
        "message": {
            "data": {
                "sell": "1000000",
                "buy": "999000",
                "timestamp": 1600000000000
            }
        }
    })
    
    # Manually trigger callback
    data_client._handle_message(msg_json)
    
    # Verify QuoteTick emitted via _handle_data
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
    data_client._subscribed_instruments[instrument.value] = MagicMock()
    data_client._subscribed_instruments[instrument.value].id = instrument

    data_client.connect()
    await asyncio.sleep(0.1)
    
    msg_json = json.dumps({
        "room_name": "transactions_btc_jpy",
        "message": {
            "data": {
                "transactions": [
                    {
                        "transaction_id": 12345,
                        "side": "buy",
                        "price": "1000000",
                        "amount": "0.01",
                        "executed_at": 1600000000000
                    }
                ]
            }
        }
    })
    
    data_client._handle_message(msg_json)
    
    assert data_client._handle_data.called
    args = data_client._handle_data.call_args[0]
    tick: TradeTick = args[0]
    
    assert tick.price == 1000000
    assert tick.qty == 0.01
    assert tick.trade_id == "12345"
