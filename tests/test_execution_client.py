import pytest
import asyncio
import json
from decimal import Decimal
from unittest.mock import MagicMock, AsyncMock, ANY
from nautilus_trader.model.identifiers import Venue, InstrumentId, ClientOrderId, VenueOrderId, StrategyId, TradeId

from nautilus_trader.model.identifiers import Venue, InstrumentId, ClientOrderId, VenueOrderId
from nautilus_trader.model.objects import Money, Currency, Quantity, Price
from nautilus_trader.model.orders import LimitOrder
from nautilus_trader.model.enums import OrderType, OrderSide, TimeInForce, LiquiditySide
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
    assert kwargs["last_qty"] == Quantity.from_str("0.005")
    assert kwargs["last_px"] == Price.from_str("3000000")
    assert kwargs["commission"] == Money.from_str("100 JPY")
    assert kwargs["trade_id"] == TradeId("9991")
    assert kwargs["order_side"] == OrderSide.BUY
    assert kwargs["order_type"] == OrderType.LIMIT
    assert kwargs["quote_currency"] == Currency.from_str("JPY")
    assert kwargs["liquidity_side"] == LiquiditySide.MAKER

@pytest.mark.asyncio
async def test_process_order_update_fill_taker(exec_client, test_order):
    """Test that liquidity_side is TAKER when maker_taker='taker'."""
    mock_rust = exec_client._rust_client
    venue_order_id = VenueOrderId("123456790")
    exec_client._active_orders[str(venue_order_id)] = test_order
    exec_client._order_states[str(venue_order_id)] = {
        "last_executed_qty": Decimal("0"),
        "reported_trades": set()
    }

    quote_currency = Currency.from_str("JPY")

    mock_rust.get_order.return_value = json.dumps({
        "order_id": 123456790,
        "status": "PARTIALLY_FILLED",
        "executed_amount": "0.003",
        "average_price": "2900000"
    })

    mock_rust.get_trade_history.return_value = json.dumps({
        "trades": [
            {
                "trade_id": 8881,
                "pair": "btc_jpy",
                "order_id": 123456790,
                "side": "buy",
                "type": "limit",
                "amount": "0.003",
                "price": "2900000",
                "maker_taker": "taker",
                "fee_amount_quote": "50",
                "executed_at": 1600000002000
            }
        ]
    })

    exec_client.generate_order_filled = MagicMock()

    await exec_client._process_order_update(
        test_order, venue_order_id, "btc_jpy", quote_currency
    )

    exec_client.generate_order_filled.assert_called_once()
    kwargs = exec_client.generate_order_filled.call_args[1]
    assert kwargs["trade_id"] == TradeId("8881")
    assert kwargs["liquidity_side"] == LiquiditySide.TAKER
    assert kwargs["commission"] == Money.from_str("50 JPY")

@pytest.mark.asyncio
async def test_process_order_update_fill_no_trade_history_fallback(exec_client, test_order):
    """Test that fill uses average_price fallback when trade history fails (#13)."""
    mock_rust = exec_client._rust_client
    venue_order_id = VenueOrderId("123456791")
    exec_client._active_orders[str(venue_order_id)] = test_order
    exec_client._order_states[str(venue_order_id)] = {
        "last_executed_qty": Decimal("0"),
        "reported_trades": set()
    }

    quote_currency = Currency.from_str("JPY")

    # Trade history fetch raises exception on all retries
    mock_rust.get_trade_history.side_effect = Exception("API timeout")

    exec_client.generate_order_filled = MagicMock()

    data = {
        "order_id": 123456791,
        "status": "PARTIALLY_FILLED",
        "executed_amount": "0.002",
        "average_price": "3100000"
    }

    result = await exec_client._process_order_update(
        test_order, venue_order_id, "btc_jpy", quote_currency, data
    )

    # Fill should be generated using average_price fallback
    assert result is False  # Not a terminal status
    exec_client.generate_order_filled.assert_called_once()
    kwargs = exec_client.generate_order_filled.call_args[1]
    assert kwargs["last_px"] == Price.from_str("3100000")
    assert kwargs["last_qty"] == Quantity.from_str("0.002")
    assert kwargs["liquidity_side"] == LiquiditySide.MAKER  # default when no trade history

    # State should be updated to prevent reconciliation
    assert exec_client._order_states[str(venue_order_id)]["last_executed_qty"] == Decimal("0.002")

@pytest.mark.asyncio
async def test_process_order_update_fill_no_trade_history_price_zero(exec_client, test_order):
    """Test that fill is rejected when trade history fails AND average_price=0 (#13)."""
    mock_rust = exec_client._rust_client
    venue_order_id = VenueOrderId("123456792")
    exec_client._active_orders[str(venue_order_id)] = test_order
    exec_client._order_states[str(venue_order_id)] = {
        "last_executed_qty": Decimal("0"),
        "reported_trades": set()
    }

    quote_currency = Currency.from_str("JPY")

    # Trade history fetch fails
    mock_rust.get_trade_history.side_effect = Exception("API timeout")

    exec_client.generate_order_filled = MagicMock()

    data = {
        "order_id": 123456792,
        "status": "PARTIALLY_FILLED",
        "executed_amount": "0.002",
        "average_price": "0"  # No average price available (e.g. race condition)
    }

    result = await exec_client._process_order_update(
        test_order, venue_order_id, "btc_jpy", quote_currency, data
    )

    # Fill should be REJECTED (price=0) but state updated to prevent reconciliation
    assert result is False
    exec_client.generate_order_filled.assert_not_called()
    # State must be updated to prevent ExecEngine reconciliation from generating price=0 fill
    assert exec_client._order_states[str(venue_order_id)]["last_executed_qty"] == Decimal("0.002")

@pytest.mark.asyncio
async def test_process_order_update_trade_history_retry(exec_client, test_order):
    """Test that trade history fetch is retried on transient failure (#13)."""
    mock_rust = exec_client._rust_client
    venue_order_id = VenueOrderId("123456793")
    exec_client._active_orders[str(venue_order_id)] = test_order
    exec_client._order_states[str(venue_order_id)] = {
        "last_executed_qty": Decimal("0"),
        "reported_trades": set()
    }

    quote_currency = Currency.from_str("JPY")

    # First call fails, second succeeds
    mock_rust.get_trade_history.side_effect = [
        Exception("API timeout"),
        json.dumps({
            "trades": [
                {
                    "trade_id": 7771,
                    "pair": "btc_jpy",
                    "order_id": 123456793,
                    "side": "buy",
                    "type": "limit",
                    "amount": "0.003",
                    "price": "2800000",
                    "maker_taker": "maker",
                    "fee_amount_quote": "30",
                    "executed_at": 1600000003000
                }
            ]
        }),
    ]

    exec_client.generate_order_filled = MagicMock()

    data = {
        "order_id": 123456793,
        "status": "PARTIALLY_FILLED",
        "executed_amount": "0.003",
        "average_price": "2800000"
    }

    await exec_client._process_order_update(
        test_order, venue_order_id, "btc_jpy", quote_currency, data
    )

    # Fill should succeed after retry
    exec_client.generate_order_filled.assert_called_once()
    kwargs = exec_client.generate_order_filled.call_args[1]
    assert kwargs["last_px"] == Price.from_str("2800000")
    assert kwargs["trade_id"] == TradeId("7771")

@pytest.mark.asyncio
async def test_process_order_update_trade_history_price_zero_from_trades(exec_client, test_order):
    """Test that fill is rejected when trade history returns price=0 (#13)."""
    mock_rust = exec_client._rust_client
    venue_order_id = VenueOrderId("123456794")
    exec_client._active_orders[str(venue_order_id)] = test_order
    exec_client._order_states[str(venue_order_id)] = {
        "last_executed_qty": Decimal("0"),
        "reported_trades": set()
    }

    quote_currency = Currency.from_str("JPY")

    # Trade history returns trades with price=0 (Bitbank anomaly)
    mock_rust.get_trade_history.return_value = json.dumps({
        "trades": [
            {
                "trade_id": 6661,
                "pair": "btc_jpy",
                "order_id": 123456794,
                "side": "buy",
                "type": "limit",
                "amount": "0.005",
                "price": "0",
                "maker_taker": "maker",
                "fee_amount_quote": "0",
                "executed_at": 1600000004000
            }
        ]
    })

    exec_client.generate_order_filled = MagicMock()

    data = {
        "order_id": 123456794,
        "status": "PARTIALLY_FILLED",
        "executed_amount": "0.005",
        "average_price": "0"
    }

    result = await exec_client._process_order_update(
        test_order, venue_order_id, "btc_jpy", quote_currency, data
    )

    # Fill should be REJECTED (price=0) and state updated
    assert result is False
    exec_client.generate_order_filled.assert_not_called()
    assert exec_client._order_states[str(venue_order_id)]["last_executed_qty"] == Decimal("0.005")

@pytest.mark.asyncio
async def test_fetch_trade_history_json_decode_error_no_retry(exec_client, test_order):
    """Test that JSONDecodeError is not retried (data format issue, not transient) (#13)."""
    mock_rust = exec_client._rust_client
    venue_order_id = VenueOrderId("123456795")
    exec_client._active_orders[str(venue_order_id)] = test_order
    exec_client._order_states[str(venue_order_id)] = {
        "last_executed_qty": Decimal("0"),
        "reported_trades": set()
    }

    quote_currency = Currency.from_str("JPY")

    # Return malformed JSON — should fail immediately without retry
    mock_rust.get_trade_history.return_value = "not valid json {{"

    exec_client.generate_order_filled = MagicMock()

    data = {
        "order_id": 123456795,
        "status": "PARTIALLY_FILLED",
        "executed_amount": "0.003",
        "average_price": "2800000"
    }

    await exec_client._process_order_update(
        test_order, venue_order_id, "btc_jpy", quote_currency, data
    )

    # Should have been called exactly once (no retry for JSONDecodeError)
    assert mock_rust.get_trade_history.call_count == 1
    # Should fallback to average_price
    exec_client.generate_order_filled.assert_called_once()
    kwargs = exec_client.generate_order_filled.call_args[1]
    assert kwargs["last_px"] == Price.from_str("2800000")

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "venue_order_id_str, trade_data, expected_commission_str",
    [
        pytest.param(
            "123456800",
            {
                "trade_id": 5551,
                "pair": "xrp_jpy",
                "order_id": 123456800,
                "side": "buy",
                "type": "limit",
                "amount": "10",
                "price": "350",
                "maker_taker": "maker",
                "fee_amount_base": "-0.002",
                "fee_amount_quote": "0",
                "executed_at": 1600000010000,
            },
            "-1 JPY",
            id="buy_maker_fee_in_base",
        ),
        pytest.param(
            "123456801",
            {
                "trade_id": 5552,
                "pair": "xrp_jpy",
                "order_id": 123456801,
                "side": "sell",
                "type": "limit",
                "amount": "10",
                "price": "350",
                "maker_taker": "maker",
                "fee_amount_base": "0",
                "fee_amount_quote": "-0.7",
                "executed_at": 1600000011000,
            },
            "-1 JPY",
            id="sell_maker_fee_in_quote",
        ),
    ],
)
async def test_process_order_update_fill_fee_calculation(
    exec_client, test_order, venue_order_id_str, trade_data, expected_commission_str
):
    """Test commission calculation for BUY and SELL maker fills.

    On Bitbank:
    - BUY orders: fee/rebate in base currency (fee_amount_base), fee_amount_quote=0
    - SELL orders: fee/rebate in quote currency (fee_amount_quote), fee_amount_base=0
    The adapter must combine both fields, converting base fee via trade price.
    """
    mock_rust = exec_client._rust_client
    venue_order_id = VenueOrderId(venue_order_id_str)
    exec_client._active_orders[str(venue_order_id)] = test_order
    exec_client._order_states[str(venue_order_id)] = {
        "last_executed_qty": Decimal("0"),
        "reported_trades": set(),
    }

    quote_currency = Currency.from_str("JPY")

    mock_rust.get_trade_history.return_value = json.dumps(
        {"trades": [trade_data]}
    )

    exec_client.generate_order_filled = MagicMock()

    data = {
        "order_id": trade_data["order_id"],
        "status": "PARTIALLY_FILLED",
        "executed_amount": trade_data["amount"],
        "average_price": trade_data["price"],
    }

    await exec_client._process_order_update(
        test_order, venue_order_id, "xrp_jpy", quote_currency, data
    )

    exec_client.generate_order_filled.assert_called_once()
    kwargs = exec_client.generate_order_filled.call_args[1]
    assert kwargs["trade_id"] == TradeId(str(trade_data["trade_id"]))
    assert kwargs["liquidity_side"] == LiquiditySide.MAKER
    assert kwargs["commission"] == Money.from_str(expected_commission_str)


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


# --- #17: _parse_order_status_report avg_px tests ---

def test_parse_order_status_report_limit_filled_uses_price_as_avg_px(exec_client):
    """Test that filled LIMIT order uses order price as avg_px (#17)."""
    order_data = {
        "order_id": 55239834019,
        "pair": "xrp_jpy",
        "side": "sell",
        "type": "limit",
        "status": "FULLY_FILLED",
        "start_amount": "2.3431",
        "executed_amount": "2.3431",
        "price": "220.200",
        "ordered_at": 1772476077691,
    }

    report = exec_client._parse_order_status_report(order_data)

    assert report.avg_px is not None
    assert float(report.avg_px) == 220.200


def test_parse_order_status_report_limit_filled_with_average_price(exec_client):
    """Test that average_price from API is preferred over order price (#17)."""
    order_data = {
        "order_id": 55239834020,
        "pair": "xrp_jpy",
        "side": "buy",
        "type": "limit",
        "status": "FULLY_FILLED",
        "start_amount": "10",
        "executed_amount": "10",
        "price": "220.000",
        "average_price": "219.950",
        "ordered_at": 1772476077691,
    }

    report = exec_client._parse_order_status_report(order_data)

    assert report.avg_px is not None
    assert float(report.avg_px) == 219.950


def test_parse_order_status_report_unfilled_has_no_avg_px(exec_client):
    """Test that unfilled orders do not set avg_px (#17)."""
    order_data = {
        "order_id": 55239834021,
        "pair": "xrp_jpy",
        "side": "buy",
        "type": "limit",
        "status": "UNFILLED",
        "start_amount": "5",
        "executed_amount": "0",
        "price": "215.000",
        "ordered_at": 1772476077691,
    }

    report = exec_client._parse_order_status_report(order_data)

    assert report.avg_px is None


def test_parse_order_status_report_market_filled_with_average_price(exec_client):
    """Test that MARKET order uses average_price as avg_px (#17)."""
    order_data = {
        "order_id": 55239834022,
        "pair": "xrp_jpy",
        "side": "buy",
        "type": "market",
        "status": "FULLY_FILLED",
        "start_amount": "3",
        "executed_amount": "3",
        "average_price": "221.500",
        "ordered_at": 1772476077691,
    }

    report = exec_client._parse_order_status_report(order_data)

    assert report.avg_px is not None
    assert float(report.avg_px) == 221.500


def test_parse_order_status_report_zero_average_price_falls_back_to_limit(exec_client):
    """Test that avg_px=0 from API falls back to LIMIT price (#17)."""
    order_data = {
        "order_id": 55239834023,
        "pair": "xrp_jpy",
        "side": "sell",
        "type": "limit",
        "status": "FULLY_FILLED",
        "start_amount": "1",
        "executed_amount": "1",
        "price": "220.100",
        "average_price": "0",
        "ordered_at": 1772476077691,
    }

    report = exec_client._parse_order_status_report(order_data)

    assert report.avg_px is not None
    assert float(report.avg_px) == 220.100
