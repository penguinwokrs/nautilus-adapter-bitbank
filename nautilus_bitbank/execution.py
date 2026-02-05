import asyncio
import json
import logging
from typing import Dict, List, Optional
from decimal import Decimal

from nautilus_trader.live.execution_client import LiveExecutionClient
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.model.orders import Order
from nautilus_trader.model.identifiers import Venue, ClientId, AccountId
from nautilus_trader.model.enums import (
    TimeInForce,
    OrderSide,
    OrderType,
    OrderStatus,
    OmsType,
    AccountType,
)
from nautilus_trader.model.events import (
    OrderAccepted,
    OrderRejected,
    OrderCanceled,
    OrderCancelRejected,
)
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
            client_id=ClientId("BITBANK-EXEC"),
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

    async def submit_order(self, command: SubmitOrder) -> None:
        try:
            instrument_id = command.instrument_id
            # Format: BTC/JPY -> btc_jpy
            pair = instrument_id.symbol.value.replace("/", "_").lower()
            
            side = "buy" if command.side == OrderSide.BUY else "sell"
            
            # Order Type
            if command.order_type == OrderType.MARKET:
                order_type = "market"
                price = None
            elif command.order_type == OrderType.LIMIT:
                order_type = "limit"
                # Price must be string
                # msgspec command.limit_price is float/Decimal?
                if command.limit_price is None:
                    # Should not verify here, but fail
                     self._logger.error(f"Limit order requires price: {command.client_order_id}")
                     self._publish_reject(command, "Limit order requires price")
                     return
                price = str(command.limit_price)
            else:
                self._publish_reject(command, f"Unsupported order type: {command.order_type}")
                return

            # Amount
            # command.quantity
            amount = str(command.quantity)

            self._logger.info(f"Submitting order: {side} {amount} {pair} @ {price or 'MKT'}")

            # Call Rust Client
            # Returns JSON string
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
            
            venue_order_id = str(resp.get("order_id"))
            
            # Publish OrderAccepted
            # We need to create an event with correct matching IDs
            # The base class or `Cache` tracks orders.
            # We should publish `OrderAccepted`
            
            report = OrderAccepted(
                instrument_id=command.instrument_id,
                client_order_id=command.client_order_id,
                venue_order_id=venue_order_id,
                account_id=self.account_id, # Optional?
                event_id=self._clock.timestamp_ns(), # using unique ID ideally
                ts_event=self._clock.timestamp_ns(),
                ts_init=self._clock.timestamp_ns(),
            )
            self._msgbus.publish(report)
            self._logger.info(f"Order accepted: {venue_order_id}")

        except Exception as e:
            self._logger.error(f"Submit failed: {e}")
            self._publish_reject(command, str(e))

    async def cancel_order(self, command: CancelOrder) -> None:
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
            
            await self._client.cancel_order_py(pair, venue_order_id)
            
            # Publish OrderCanceled
            report = OrderCanceled(
                instrument_id=command.instrument_id,
                client_order_id=command.client_order_id,
                venue_order_id=venue_order_id,
                account_id=self.account_id,
                event_id=self._clock.timestamp_ns(),
                ts_event=self._clock.timestamp_ns(),
                ts_init=self._clock.timestamp_ns(),
            )
            self._msgbus.publish(report)
            self._logger.info(f"Order canceled: {venue_order_id}")

        except Exception as e:
            self._logger.error(f"Cancel failed: {e}")
            self._publish_cancel_reject(command, str(e))

    def _publish_reject(self, command: SubmitOrder, reason: str):
        report = OrderRejected(
            instrument_id=command.instrument_id,
            client_order_id=command.client_order_id,
            account_id=self.account_id,
            reason=reason,
            event_id=self._clock.timestamp_ns(),
            ts_event=self._clock.timestamp_ns(),
            ts_init=self._clock.timestamp_ns(),
        )
        self._msgbus.publish(report)

    def _publish_cancel_reject(self, command: CancelOrder, reason: str):
        report = OrderCancelRejected(
            instrument_id=command.instrument_id,
            client_order_id=command.client_order_id,
            venue_order_id=command.venue_order_id,
            account_id=self.account_id,
            reason=reason,
            event_id=self._clock.timestamp_ns(),
            ts_event=self._clock.timestamp_ns(),
            ts_init=self._clock.timestamp_ns(),
        )
        self._msgbus.publish(report)
