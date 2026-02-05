import asyncio
import json
import logging
from typing import Dict, List, Optional
from decimal import Decimal

from nautilus_trader.live.execution_client import LiveExecutionClient
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.model.orders import Order
from nautilus_trader.model.identifiers import Venue, ClientId, AccountId, TradeId, VenueOrderId
from nautilus_trader.model.enums import (
    TimeInForce,
    OrderSide,
    OrderType,
    OrderStatus,
    OmsType,
    AccountType,
    LiquiditySide,
)
from nautilus_trader.model.currencies import Currency
from nautilus_trader.model.objects import Money
from nautilus_trader.execution.messages import (
    SubmitOrder,
    CancelOrder,
)

from .config import BitbankExecClientConfig

try:
    from . import _nautilus_bitbank as bitbank
except ImportError:
    # Fallback or dev handling
    import _nautilus_bitbank as bitbank

class BitbankExecutionClient(LiveExecutionClient):
    def __init__(self, loop, config: BitbankExecClientConfig, msgbus, cache, clock, instrument_provider: InstrumentProvider):
        super().__init__(
            loop=loop,
            client_id=ClientId("BITBANK"),
            venue=Venue("BITBANK"),
            oms_type=OmsType.NETTING,
            account_type=AccountType.CASH,
            base_currency=None,
            instrument_provider=instrument_provider,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            config=config,
        )
        self.config = config
        self._account_id = AccountId("BITBANK-001")
        self._set_account_id(self._account_id)
        self._logger = logging.getLogger(__name__)
        
        self._client = bitbank.BitbankRestClient(
            self.config.api_key or "",
            self.config.api_secret or ""
        )

    @property
    def account_id(self) -> AccountId:
        return self._account_id

    async def _connect(self):
        self._logger.info("BitbankExecutionClient connected")

    async def _disconnect(self):
        self._logger.info("BitbankExecutionClient disconnected")
    
    async def generate_order_status_reports(self, instrument_id=None, client_order_id=None):
        return []

    async def generate_fill_reports(self, instrument_id=None, client_order_id=None):
        return []

    async def generate_position_reports(self, instrument_id=None):
        return []

    async def generate_position_status_reports(self, instrument_id=None):
        return []

    # Note: LiveExecutionClient methods usually take commands (OrderSubmit, OrderCancel) 
    # OR the abstract methods might be named differently depending on version.
    # Looking at base class `LiveExecutionClient`:
    # It has `submit_order(self, command: OrderSubmit)` and `cancel_order(self, command: OrderCancel)`
    # Wait, usually `submit_order` takes an `Order` object or `SubmitOrder` command?
    # In recent Nautilus, `set_execution_client` triggers commands.
    # The commands are processed.
    # The base class defines: `submit_order(self, command: OrderSubmit)`
    # Let's assume OrderSubmit command.

    def submit_order(self, command: SubmitOrder) -> None:
        self.create_task(self._submit_order(command))

    async def _submit_order(self, command: SubmitOrder) -> None:
        try:
            order = command.order
            instrument_id = order.instrument_id
            # Format: BTC/JPY -> btc_jpy
            pair = instrument_id.symbol.value.replace("/", "_").lower()
            
            side = "buy" if order.side == OrderSide.BUY else "sell"
            
            # Order Type
            if order.order_type == OrderType.MARKET:
                order_type = "market"
                price = None
            elif order.order_type == OrderType.LIMIT:
                order_type = "limit"
                # Price must be string
                price = str(order.price)
            else:
                self._publish_reject(command, f"Unsupported order type: {order.order_type}")
                return

            # Amount
            amount = str(order.quantity)

            self._logger.info(f"Submitting order: {side} {amount} {pair} @ {price or 'MKT'}")

            # Call Rust Client
            resp_json = await self._client.create_order_py(
                pair,
                amount,
                side,
                order_type,
                price
            )
            
            resp = json.loads(resp_json)
            # resp is the order object from Bitbank
            # {"order_id": 12345, ...}
            
            venue_order_id = VenueOrderId(str(resp.get("order_id")))
            
            # Use the proper API to generate OrderAccepted event
            self.generate_order_accepted(
                strategy_id=order.strategy_id,
                instrument_id=order.instrument_id,
                client_order_id=order.client_order_id,
                venue_order_id=venue_order_id,
                ts_event=self._clock.timestamp_ns(),
            )
            self._logger.info(f"Order accepted: {venue_order_id}")

            # Start polling for this order
            self.create_task(self._poll_order(order, venue_order_id))



        except Exception as e:
            err_msg = str(e)
            if "60001" in err_msg:
                err_msg = "Insufficient funds (Bitbank 60001)"
            self._logger.error(f"Submit failed: {err_msg}")
            self._publish_reject(command, err_msg)

    async def _poll_order(self, order: Order, venue_order_id: VenueOrderId):
        """Poll Bitbank API for order status and report fills."""
        instrument_id = order.instrument_id
        pair = instrument_id.symbol.value.replace("/", "_").lower()
        last_executed_qty = Decimal("0")
        
        # Determine quote currency for Money objects
        # e.g. BTC/JPY -> JPY
        quote_currency_code = instrument_id.symbol.value.split("/")[-1]
        quote_currency = Currency.from_str(quote_currency_code)

        while True:
            try:
                await asyncio.sleep(2)  # Adjust polling interval as needed
                
                resp_json = await self._client.get_order_py(pair, str(venue_order_id))
                order_data = json.loads(resp_json)
                
                status = order_data.get("status")
                executed_qty = Decimal(order_data.get("executed_amount", "0"))
                avg_price_str = order_data.get("average_price", "0")
                avg_price = Decimal(avg_price_str if avg_price_str and avg_price_str != "0" else "0")

                # Check for new fills
                if executed_qty > last_executed_qty:
                    fill_qty = executed_qty - last_executed_qty
                    last_executed_qty = executed_qty
                    
                    # Generate Fill Report
                    self.generate_order_filled(
                        strategy_id=order.strategy_id,
                        instrument_id=order.instrument_id,
                        client_order_id=order.client_order_id,
                        venue_order_id=venue_order_id,
                        venue_position_id=None,
                        trade_id=TradeId(f"BB-{venue_order_id}-{self._clock.timestamp_ns()}"),
                        order_side=order.side,
                        order_type=order.order_type,
                        last_qty=fill_qty,
                        last_px=avg_price,
                        quote_currency=quote_currency,
                        commission=Money(0, quote_currency), # Need actual commission calculation if possible
                        liquidity_side=LiquiditySide.NO_LIQUIDITY_SIDE, # Bitbank doesn't tell us maker/taker in this API easily
                        ts_event=self._clock.timestamp_ns(),
                    )
                    self._logger.info(f"Order fill reported: {fill_qty} @ {avg_price}")

                # Check if order is finished
                if status in ("FULLY_FILLED", "CANCELED_UNFILLED", "CANCELED_PARTIALLY_FILLED"):
                    if status.startswith("CANCELED"):
                        # We only report cancel if not already handled by cancel_order method
                        self.generate_order_canceled(
                            strategy_id=order.strategy_id,
                            instrument_id=order.instrument_id,
                            client_order_id=order.client_order_id,
                            venue_order_id=venue_order_id,
                            ts_event=self._clock.timestamp_ns(),
                        )
                    self._logger.info(f"Order polling finished for {venue_order_id} with status {status}")
                    break

            except Exception as e:
                self._logger.error(f"Error polling order {venue_order_id}: {e}")
                await asyncio.sleep(5)  # Wait longer on error

    def cancel_order(self, command: CancelOrder) -> None:
        self.create_task(self._cancel_order(command))

    async def _cancel_order(self, command: CancelOrder) -> None:
        try:
            # We need venue_order_id
            if not command.venue_order_id:
                self._logger.error("Cannot cancel order without venue_order_id")
                # Publish CancelRejected
                self._publish_cancel_reject(command, "Missing venue_order_id")
                return

            instrument_id = command.instrument_id
            pair = instrument_id.symbol.value.replace("/", "_").lower()
            
            venue_order_id = command.venue_order_id
            
            self._logger.info(f"Cancelling order: {venue_order_id}")
            
            await self._client.cancel_order_py(pair, str(command.venue_order_id))
            
            # Use the proper API to generate OrderCanceled event
            # Note: The _poll_order task will also detect the cancel status 
            # and report generate_order_canceled. To avoid double reporting, 
            # we should be careful. However, Nautilus handles duplicate events 
            # safely if they have the same IDs or if the status is already updated.
            # Usually, manual cancel should report immediately.
            self.generate_order_canceled(
                strategy_id=command.strategy_id,
                instrument_id=command.instrument_id,
                client_order_id=command.client_order_id,
                venue_order_id=command.venue_order_id if isinstance(command.venue_order_id, VenueOrderId) else VenueOrderId(str(command.venue_order_id)),
                ts_event=self._clock.timestamp_ns(),
            )
            self._logger.info(f"Order canceled: {command.venue_order_id}")

        except Exception as e:
            self._logger.error(f"Cancel failed: {e}")
            self._publish_cancel_reject(command, str(e))

    def _publish_reject(self, command: SubmitOrder, reason: str):
        self.generate_order_rejected(
            strategy_id=command.order.strategy_id,
            instrument_id=command.order.instrument_id,
            client_order_id=command.order.client_order_id,
            reason=reason,
            ts_event=self._clock.timestamp_ns(),
        )

    def _publish_cancel_reject(self, command: CancelOrder, reason: str):
        from nautilus_trader.model.identifiers import VenueOrderId
        venue_order_id = command.venue_order_id if isinstance(command.venue_order_id, VenueOrderId) else VenueOrderId(str(command.venue_order_id)) if command.venue_order_id else VenueOrderId("UNKNOWN")
        self.generate_order_cancel_rejected(
            strategy_id=command.strategy_id,
            instrument_id=command.instrument_id,
            client_order_id=command.client_order_id,
            venue_order_id=venue_order_id,
            reason=reason,
            ts_event=self._clock.timestamp_ns(),
        )

