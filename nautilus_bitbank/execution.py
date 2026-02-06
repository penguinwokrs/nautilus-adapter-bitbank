import asyncio
import json
import logging
from typing import Dict, List, Optional
from decimal import Decimal

from nautilus_trader.live.execution_client import LiveExecutionClient
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.model.orders import Order
from nautilus_trader.model.objects import Money, Currency
from nautilus_trader.model.currencies import JPY
from nautilus_trader.model.identifiers import Venue, ClientId, AccountId, VenueOrderId
from nautilus_trader.model.enums import OrderSide, OrderType, OmsType, AccountType
from nautilus_trader.execution.messages import SubmitOrder, CancelOrder

from .config import BitbankExecClientConfig

try:
    from . import _nautilus_bitbank as bitbank
except ImportError:
    import _nautilus_bitbank as bitbank

class BitbankExecutionClient(LiveExecutionClient):
    """
    Rust-First implementation wrapper.
    Actual logic resides in bitbank.BitbankExecutionClient (Rust).
    """
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
        self._instrument_provider = instrument_provider
        self._logger = logging.getLogger(__name__)
        self._account_id = AccountId("BITBANK-001")
        self._set_account_id(self._account_id)
        self._order_states = {} # Track fill state per order
        
        self._rust_client = bitbank.BitbankExecutionClient(
            self.config.api_key or "",
            self.config.api_secret or "",
            self.config.pubnub_subscribe_key,
            self.config.timeout_ms,
            self.config.proxy_url
        )
        self._rust_client.set_order_callback(self._handle_pubnub_message)

    @property
    def account_id(self) -> AccountId:
        return self._account_id

    async def _connect(self):
        self._logger.info("BitbankExecutionClient connected (via Rust)")
        
        if self.config.use_pubnub:
            try:
                # Delegate Auth and Connect to Rust
                await self._rust_client.connect()
                self._logger.info("PubNub stream started via Rust client")
            except Exception as e:
                self._logger.error(f"Failed to connect PubNub via Rust: {e}")

    async def _disconnect(self):
        self._logger.info("BitbankExecutionClient disconnected")
        # TODO: Implement disconnect in Rust if needed to stop PubNub loop cleanly
        # self._rust_client.disconnect(self.loop)

    def submit_order(self, command: SubmitOrder) -> None:
        self.create_task(self._submit_order(command))

    async def _submit_order(self, command: SubmitOrder) -> None:
        try:
            order = command.order
            instrument_id = order.instrument_id
            pair = instrument_id.symbol.value.replace("/", "_").lower()
            
            side = "buy" if order.side == OrderSide.BUY else "sell"
            
            order_type = "market"
            price = None
            if order.order_type == OrderType.LIMIT:
                order_type = "limit"
                price = str(order.price)
            elif order.order_type != OrderType.MARKET:
                # Reject unsupported
                return

            amount = str(order.quantity)
            
            client_id = str(command.client_order_id)
            resp_json = await self._rust_client.submit_order(
                pair,
                amount,
                side,
                order_type,
                client_id,
                price
            )
            
            resp = json.loads(resp_json)
            venue_order_id = VenueOrderId(str(resp.get("order_id")))
            
            self.generate_order_accepted(
                strategy_id=order.strategy_id,
                instrument_id=order.instrument_id,
                client_order_id=order.client_order_id,
                venue_order_id=venue_order_id,
                ts_event=self._clock.timestamp_ns(),
            )
            
        except Exception as e:
            self._logger.error(f"Submit failed: {e}")
            # Generate rejected event...

    def cancel_order(self, command: CancelOrder) -> None:
        self.create_task(self._cancel_order(command))

    async def _cancel_order(self, command: CancelOrder) -> None:
        try:
            if not command.venue_order_id:
                return

            instrument_id = command.instrument_id
            pair = instrument_id.symbol.value.replace("/", "_").lower()
            
            await self._rust_client.cancel_order(
                pair,
                str(command.venue_order_id)
            )
            
            self.generate_order_canceled(
                strategy_id=command.strategy_id,
                instrument_id=command.instrument_id,
                client_order_id=command.client_order_id,
                venue_order_id=command.venue_order_id, # type: ignore
                ts_event=self._clock.timestamp_ns(),
            )
            
        except Exception as e:
            self._logger.error(f"Cancel failed: {e}")

    def _handle_pubnub_message(self, event_type: str, message: str):
        """
        Callback from Rust.
        Args:
            event_type: str (e.g. "OrderUpdate")
            message: str (JSON payload)
        """
        try:
            if event_type == "OrderUpdate":
                data = json.loads(message).get("data")
                if not data:
                    return
                
                venue_order_id = VenueOrderId(str(data.get("order_id")))
                pair = data.get("pair")
                
                # Trigger processing with the data we got from Rust
                self.create_task(self._process_order_update_from_data(venue_order_id, pair, data))
            else:
                self._logger.debug(f"Unknown PubNub Event: {event_type} - {message}")
        except Exception as e:
            self._logger.error(f"Error handling PubNub message: {e}")

    async def _process_order_update_from_data(self, venue_order_id: VenueOrderId, pair: str, data: dict):
        # Find the order in cache
        client_oid = self._cache.client_order_id(venue_order_id)
        if not client_oid:
            # We might not have it yet if PubNub is faster than our submit acknowledgement
            self._logger.warning(f"ClientOrderId not found for venue_order_id: {venue_order_id}")
            return
            
        order = self._cache.order(client_oid)
        if not order:
            self._logger.warning(f"Order not found in cache for client_order_id: {client_oid}")
            return
            
        # Instrument to get quote currency for commission Money object
        instrument = self._instrument_provider.find(order.instrument_id)
        quote_currency = JPY if not instrument else instrument.quote_currency
        
        await self._process_order_update(order, venue_order_id, pair, quote_currency, data)

    async def _process_order_update(self, order: Order, venue_order_id: VenueOrderId, pair: str, quote_currency, data: dict = None) -> bool:
        """
        Check order status and generate fill events if needed.
        Returns True if order is closed (FILLED/CANCELED).
        """
        try:
            if data is None:
                resp_json = await self._rust_client.get_order(pair, str(venue_order_id))
                data = json.loads(resp_json)
            
            status = data.get("status")
            
            # Check executed amount
            executed = Decimal(data.get("executed_amount", "0"))
            
            oid_str = str(venue_order_id)
            if oid_str not in self._order_states:
                self._order_states[oid_str] = {
                    "last_executed_qty": Decimal("0"),
                    "reported_trades": set()
                }
            
            state = self._order_states[oid_str]
            last_qty = state["last_executed_qty"]
            
            if executed > last_qty:
                delta = executed - last_qty
                
                # Fetch trades to find price/commission
                # Ideally we match trade ID, but for now using average price from order or trade history
                # This is simplified.
                avg_price = Decimal(data.get("average_price", "0") or "0")
                
                # Fetch trades for precise fill info
                history_json = await self._rust_client.get_trade_history(pair, str(venue_order_id))
                history = json.loads(history_json)
                
                commission = Money(Decimal("0"), quote_currency)
                avg_price = Decimal(data.get("average_price", "0") or "0") # Fallback
                
                # Check for new trades
                raw_trades = history.get("trades", [])
                new_trades = []
                for t in raw_trades:
                    tid = str(t.get("trade_id"))
                    if tid not in state["reported_trades"]:
                        new_trades.append(t)
                        state["reported_trades"].add(tid)
                        
                if new_trades:
                    # Calculate weighted price and comms from new trades?
                    # Or just use avg_price from order and sum comms?
                    total_fee = Decimal("0")
                    for t in new_trades:
                        fee = Decimal(t.get("fee_amount_quote", "0"))
                        total_fee += fee
                        # Could calculate px here
                    
                    commission = Money(total_fee, quote_currency)
                    if len(new_trades) == 1:
                        avg_price = Decimal(new_trades[0].get("price", "0"))
                
                self.generate_order_filled(
                    strategy_id=order.strategy_id,
                    instrument_id=order.instrument_id,
                    client_order_id=order.client_order_id,
                    venue_order_id=venue_order_id,
                    venue_position_id=None,
                    fill_id=None, # generate one?
                    last_qty=delta,
                    last_px=avg_price,
                    liquidity=None,
                    commission=commission,
                    ts_event=self._clock.timestamp_ns()
                )
                
                state["last_executed_qty"] = executed

            if status in ("FILLED", "CANCELED_UNFILLED", "CANCELED_PARTIALLY_FILLED"):
                return True
                
        except Exception as e:
            self._logger.error(f"Update processing failed: {e}")
            
        return False

    # Required abstract methods
    async def generate_order_status_reports(self, instrument_id=None, client_order_id=None):
        return []

    async def generate_fill_reports(self, instrument_id=None, client_order_id=None):
        return []

    async def generate_position_reports(self, instrument_id=None):
        return []

    async def generate_position_status_reports(self, instrument_id=None):
        return []

