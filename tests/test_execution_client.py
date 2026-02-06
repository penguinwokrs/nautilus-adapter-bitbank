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
    order.side = OrderSide.BUY
    order.order_type = OrderType.LIMIT
    order.quantity = Quantity.from_str("0.01")
    order.price = Price.from_str("3000000")
    order.time_in_force = TimeInForce.GTC
    # order.ts_init = 1600000000000_000_000 # Read-only property in Cython? MagicMock accepts it.
    return order

@pytest.mark.asyncio
async def test_submit_order(exec_client, test_order, test_instrument):
    """Test converting SubmitOrder command to Bitbank API call."""
    mock_rest = exec_client._client
    
    # Setup mock return for create_order_py
    # ManualMockRestClient wraps inner AsyncMock
    mock_rest.create_order_py_mock.return_value = json.dumps({
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
    # Configure command.order properties accessed by execution.py
    command.order = MagicMock()
    command.order.client_order_id = test_order.client_order_id
    command.order.instrument_id = test_order.instrument_id
    command.order.strategy_id = StrategyId("TEST-STRAT")
    
    command.client_order_id = test_order.client_order_id
    command.strategy_id = StrategyId("TEST-STRAT")
    command.instrument_id = test_order.instrument_id
    command.order_side = test_order.side
    command.order_type = test_order.order_type
    command.quantity = test_order.quantity
    command.price = test_order.price
    command.time_in_force = test_order.time_in_force
    
    # Verify API call
    expected_pair = "btc_jpy"
    expected_side = "buy"
    expected_type = "limit"
    
    await exec_client._submit_order(command)

    mock_rest.create_order_py_mock.assert_called_with(
        expected_pair,
        "0.01",
        "3000000",
        expected_side,
        expected_type
    )
    
    # Verify OrderAccepted generated
    assert exec_client._active_orders.get("123456789") == test_order

@pytest.mark.asyncio
async def test_cancel_order(exec_client, test_order):
    """Test converting CancelOrder command."""
    mock_rest = exec_client._client
    
    # Register order as active first
    venue_order_id = VenueOrderId("123456789")
    exec_client._active_orders[str(venue_order_id)] = test_order
    
    mock_rest.cancel_order_py_mock.return_value = json.dumps({"order_id": 123456789, "status": "CANCELED_UNFILLED"})
    
    command = MagicMock(spec=CancelOrder)
    command.client_order_id = test_order.client_order_id
    command.venue_order_id = venue_order_id
    command.instrument_id = test_order.instrument_id
    command.strategy_id = StrategyId("TEST-STRAT")
    
    await exec_client._cancel_order(command)
    
    mock_rest.cancel_order_py_mock.assert_called_with(
        "btc_jpy",
        "123456789"
    )

@pytest.mark.asyncio
async def test_process_order_update_fill(exec_client, test_order):
    """Test process_order_update logic for detecting fills."""
    mock_rest = exec_client._client
    venue_order_id = VenueOrderId("123456789")
    exec_client._active_orders[str(venue_order_id)] = test_order
    exec_client._order_states[str(venue_order_id)] = {
        "last_executed_qty": Decimal("0"),
        "reported_trades": set()
    }
    
    quote_currency = Currency.from_str("JPY")
    
    # Mock `get_order_py` response: Partially filled
    mock_rest.get_order_py.return_value = json.dumps({
        "order_id": 123456789,
        "status": "PARTIALLY_FILLED",
        "executed_amount": "0.005",
        "average_price": "3000000"
    })
    
    # Mock `get_trade_history_py` response
    mock_rest.get_trade_history_py.return_value = json.dumps({
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
    venue_order_id = "123456789"
    exec_client._active_orders[venue_order_id] = test_order
    
    # Mock `_process_order_update` to verifies it gets called
    exec_client._process_order_update = AsyncMock(return_value=False)
    
    # PubNub message with status FILLED
    msg = json.dumps({
        "data": {
            "order_id": 123456789,
            "status": "FILLED",
            "executed_amount": "0.01"
        }
    })
    
    exec_client._handle_pubnub_message(msg)
    
    # Wait for task to be scheduled? _handle_pubnub_message calls create_task.
    await asyncio.sleep(0.1) 
    
    exec_client._process_order_update.assert_called()
