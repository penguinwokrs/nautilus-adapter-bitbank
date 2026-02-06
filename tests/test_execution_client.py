import pytest
import asyncio
import json
from decimal import Decimal
from unittest.mock import MagicMock, AsyncMock, ANY
from nautilus_trader.model.identifiers import Venue, InstrumentId, ClientOrderId, VenueOrderId, StrategyId

from nautilus_trader.model.identifiers import Venue, InstrumentId, ClientOrderId, VenueOrderId
from nautilus_trader.model.objects import Money, Currency, Quantity, Price
from nautilus_trader.model.orders import LimitOrder
from nautilus_trader.model.enums import OrderType, OrderSide, TimeInForce
from nautilus_trader.execution.messages import SubmitOrder, CancelOrder

@pytest.fixture
def test_instrument():
    return InstrumentId.from_str("BTC/JPY.BITBANK")

@pytest.fixture
def test_order(test_instrument):
    order = MagicMock(spec=LimitOrder)
    order.client_order_id = ClientOrderId("TEST-OID-1")
    order.venue_order_id = None
    order.instrument_id = test_instrument
    order.strategy_id = StrategyId("TEST-STRAT")
    order.side = OrderSide.BUY
    order.order_type = OrderType.LIMIT
    order.quantity = Quantity.from_str("0.01")
    order.price = Price.from_str("3000000")
    order.time_in_force = TimeInForce.GTC
    return order

@pytest.mark.asyncio
async def test_submit_order(exec_client, test_order, test_instrument):
    """Test converting SubmitOrder command to Bitbank API call."""
    mock_rust = exec_client._rust_client
    
    # Setup mock return
    mock_rust.submit_order.return_value = json.dumps({
        "order_id": 123456789,
        "pair": "btc_jpy",
        "side": "buy",
        "type": "limit",
        "start_amount": "0.01",
        "remaining_amount": "0.01",
        "executed_amount": "0.00",
        "price": "3000000",
        "status": "UNFILLED",
        "ordered_at": 1600000000000
    })

    command = MagicMock(spec=SubmitOrder)
    command.order = test_order
    command.client_order_id = test_order.client_order_id
    command.strategy_id = StrategyId("TEST-STRAT")
    command.instrument_id = test_order.instrument_id
    command.order_side = test_order.side
    command.order_type = test_order.order_type
    command.quantity = test_order.quantity
    command.price = test_order.price
    command.time_in_force = test_order.time_in_force
    
    await exec_client._submit_order(command)

    # Verify rust client called
    mock_rust.submit_order.assert_called_with(
        "btc_jpy",
        "0.01",
        "buy",
        "limit",
        "TEST-OID-1", # client_order_id
        "3000000"     # price
    )
    
    # Verify OrderAccepted generated
    # (Checking internal active_orders map if logic adds it there, 
    # but submit_order in execution.py mostly generates events)
    # The current code in execution.py generates OrderAccepted.


@pytest.mark.asyncio
async def test_cancel_order(exec_client, test_order):
    """Test converting CancelOrder command."""
    mock_rust = exec_client._rust_client
    
    # Register order as active first
    venue_order_id = VenueOrderId("123456789")
    # exec_client._active_orders[str(venue_order_id)] = test_order
    # Note: _cancel_order logic in execution.py uses venue_order_id from command
    
    mock_rust.cancel_order.return_value = json.dumps({"order_id": 123456789, "status": "CANCELED_UNFILLED"})
    
    command = MagicMock(spec=CancelOrder)
    command.client_order_id = test_order.client_order_id
    command.venue_order_id = venue_order_id
    command.instrument_id = test_order.instrument_id
    command.strategy_id = StrategyId("TEST-STRAT")
    
    await exec_client._cancel_order(command)
    
    mock_rust.cancel_order.assert_called_with(
        "btc_jpy",
        "123456789"
    )

@pytest.mark.asyncio
async def test_process_order_update_fill(exec_client, test_order):
    """Test process_order_update logic for detecting fills."""
    mock_rust = exec_client._rust_client
    venue_order_id = VenueOrderId("123456789")
    exec_client._active_orders[str(venue_order_id)] = test_order
    exec_client._order_states[str(venue_order_id)] = {
        "last_executed_qty": Decimal("0"),
        "reported_trades": set()
    }
    
    quote_currency = Currency.from_str("JPY")
    
    # Mock `get_order_py` response: Partially filled
    mock_rust.get_order.return_value = json.dumps({
        "order_id": 123456789,
        "status": "PARTIALLY_FILLED",
        "executed_amount": "0.005",
        "average_price": "3000000"
    })
    
    # Mock `get_trade_history_py` response
    mock_rust.get_trade_history.return_value = json.dumps({
        "trades": [
            {
                "trade_id": 9991,
                "pair": "btc_jpy",
                "order_id": 123456789,
                "side": "buy",
                "type": "limit",
                "amount": "0.005",
                "price": "3000000",
                "maker_taker": "maker",
                "fee_amount_quote": "100", # JPY
                "executed_at": 1600000001000
            }
        ]
    })
    
    # We patch generate_order_filled to verify calls
    exec_client.generate_order_filled = MagicMock()
    
    is_closed = await exec_client._process_order_update(
        test_order, venue_order_id, "btc_jpy", quote_currency
    )
    
    assert is_closed is False
    exec_client.generate_order_filled.assert_called_once()
    kwargs = exec_client.generate_order_filled.call_args[1]
    assert kwargs["last_qty"] == Decimal("0.005")
    assert kwargs["last_px"] == Decimal("3000000")
    assert kwargs["commission"] == Money.from_str("100 JPY")

@pytest.mark.asyncio
async def test_handle_pubnub_message_trigger(exec_client, test_order):
    """Test PubNub message parsing triggering update."""
    # Mock the internal processing method to avoid cache lookups in this test
    exec_client._process_order_update_from_data = AsyncMock()
    
    # PubNub data
    msg = json.dumps({
        "data": {
            "order_id": 123456789,
            "pair": "btc_jpy",
            "status": "FILLED",
            "executed_amount": "0.01"
        }
    })
    
    # Trigger
    exec_client._handle_pubnub_message("OrderUpdate", msg)
    
    # Execution is async task, wait a bit
    await asyncio.sleep(0.01)
    
    assert exec_client._process_order_update_from_data.called
    args = exec_client._process_order_update_from_data.call_args[0]
    assert str(args[0]) == "123456789"
    assert args[1] == "btc_jpy"
    assert args[2]["status"] == "FILLED"
