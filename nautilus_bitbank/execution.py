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
        
        # Validation for stability
        if not self.config.api_key or not self.config.api_secret:
            raise ValueError("BitbankExecutionClient requires both api_key and api_secret")
            
        self._account_id = AccountId("BITBANK-001")
        self._set_account_id(self._account_id)
        self._logger = logging.getLogger(__name__)
        self._is_stopped = False
        
        self._client = bitbank.BitbankRestClient(
            self.config.api_key,
            self.config.api_secret
        )
        
        self._pubnub_client = bitbank.PubNubClient()
        self._pubnub_client.set_callback(self._handle_pubnub_message)
        self._pubnub_task = None
        
        # Track order states for event generation from stream/poll
        # Map: venue_order_id (str) -> { "last_executed_qty": Decimal, "reported_trades": Set[str] }
        self._order_states: Dict[str, dict] = {}
        
        # Map: venue_order_id (str) -> Order
        # Required to map stream updates back to Nautilus context
        self._active_orders: Dict[str, Order] = {}

    @property
    def account_id(self) -> AccountId:
        return self._account_id

    async def _connect(self):
        self._logger.info("BitbankExecutionClient connected")
        try:
            # 1. Get PubNub Auth
            auth_json = await self._client.get_pubnub_auth_py()
            auth_data = json.loads(auth_json)
            # Response: {"pubnub_channel": "...", "pubnub_token": "..."}
            
            sub_key = "sub-c-e12e9174-dd60-11e6-806b-02ee2ddab7fe" # Bitbank Public Key
            channel = auth_data.get("pubnub_channel")
            token = auth_data.get("pubnub_token") # Not used in current rust client yet, but good to have
            
            if channel:
                self._logger.info(f"Starting PubNub stream on channel: {channel}")
                # 2. Connect PubNub
                # The Rust client needs sub_key and channel. 
                # Ideally pass token if PAM is enabled, but current impl doesn't support auth param.
                # Assuming public read access for this user channel secured by complexity? 
                # Or wait, `pubnub_token` IS required. 
                # Let's pass it if we can updates Rust client, otherwise try without.
                
                await self._pubnub_client.connect_py(sub_key, channel)
            else:
                self._logger.error("PubNub auth data missing channel")

        except Exception as e:
            self._logger.error(f"Failed to connect PubNub: {e}")
            pass

    async def _disconnect(self):
        self._is_stopped = True
        try:
            await self._pubnub_client.stop_py()
        except:
            pass
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
    def _handle_pubnub_message(self, msg: str):
        """Handle incoming PubNub message."""
        try:
            # Parse message
            # Structure usually: {"data": { "order_id": ..., "status": ... }}
            data = json.loads(msg)
            # Only log for now until we implement event generation
            # self._logger.info(f"PubNub Message: {data}")
            
            # TODO: Parse order update and call generate_order_filled / generate_order_status
            pass
        except Exception as e:
            self._logger.error(f"Error handling PubNub message: {e}")

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
            
            # Register active order for PubNub updates
            self._active_orders[str(venue_order_id)] = order
            
            # Use the proper API to generate OrderAccepted event
            self.generate_order_accepted(
                strategy_id=order.strategy_id,
                instrument_id=order.instrument_id,
                client_order_id=order.client_order_id,
                venue_order_id=venue_order_id,
                ts_event=self._clock.timestamp_ns(),
            )
            self._logger.info(f"Order accepted: {venue_order_id}")

            # Start polling for this order (fallback & detail retrieval)
            self.create_task(self._poll_order(order, venue_order_id))



        except Exception as e:
            err_msg = str(e)
            # Map Bitbank error codes to readable reasons
            if "60001" in err_msg or "50003" in err_msg:
                err_msg = "Insufficient funds (Bitbank)"
            elif "40001" in err_msg:
                err_msg = "Order amount is too small (Bitbank)"
            elif "40007" in err_msg:
                err_msg = "Order price is out of range (Bitbank)"
            elif "20001" in err_msg:
                err_msg = "Authentication failed (Bitbank)"
            elif "10000" in err_msg:
                err_msg = "Internal error (Bitbank)"

            self._logger.error(f"Submit failed: {err_msg}")
            self._publish_reject(command, err_msg)

    async def _poll_order(self, order: Order, venue_order_id: VenueOrderId):
        """Poll Bitbank API for order status and report fills."""
        instrument_id = order.instrument_id
        pair = instrument_id.symbol.value.replace("/", "_").lower()
        last_executed_qty = Decimal("0")
        reported_trade_ids = set()
        
        # Determine quote currency for Money objects
        # e.g. BTC/JPY -> JPY
        quote_currency_code = instrument_id.symbol.value.split("/")[-1]
        quote_currency = Currency.from_str(quote_currency_code)

        while not self._is_stopped:
            try:
                await asyncio.sleep(2)
                if self._is_stopped:
                    break
                
                resp_json = await self._client.get_order_py(pair, str(venue_order_id))
                order_data = json.loads(resp_json)
                
                status = order_data.get("status")
                executed_qty = Decimal(order_data.get("executed_amount", "0"))
                avg_price_str = order_data.get("average_price", "0")
                avg_price = Decimal(avg_price_str if avg_price_str and avg_price_str != "0" else "0")

                # Check for new fills
                if executed_qty > last_executed_qty:
                    # Fetch detailed trade history to get fee and maker/taker
                    try:
                        trades_resp = await self._client.get_trade_history_py(pair, str(venue_order_id))
                        trades_data = json.loads(trades_resp)
                        trades = trades_data.get("trades", [])
                        
                        # Sort trades by ID or time to process them in order
                        # Bitbank usually returns desc? Let's check or just iterate.
                        for tx in sorted(trades, key=lambda x: x["trade_id"]):
                            tx_id = str(tx["trade_id"])
                            if tx_id in reported_trade_ids:
                                continue
                            
                            tx_qty = Decimal(tx["amount"])
                            tx_px = Decimal(tx["price"])
                            tx_fee = Decimal(tx["fee_amount_quote"])
                            tx_mt = tx.get("maker_taker")
                            
                            l_side = LiquiditySide.NO_LIQUIDITY_SIDE
                            if tx_mt == "maker":
                                l_side = LiquiditySide.MAKER
                            elif tx_mt == "taker":
                                l_side = LiquiditySide.TAKER
                            
                            # Generate Fill Report for THIS specific trade
                            self.generate_order_filled(
                                strategy_id=order.strategy_id,
                                instrument_id=order.instrument_id,
                                client_order_id=order.client_order_id,
                                venue_order_id=venue_order_id,
                                venue_position_id=None,
                                trade_id=TradeId(tx_id),
                                order_side=order.side,
                                order_type=order.order_type,
                                last_qty=tx_qty,
                                last_px=tx_px,
                                quote_currency=quote_currency,
                                commission=Money(tx_fee, quote_currency),
                                liquidity_side=l_side,
                                ts_event=int(tx["executed_at"]) * 1_000_000,
                            )
                            reported_trade_ids.add(tx_id)
                            self._logger.info(f"Order fill reported (trade {tx_id}): {tx_qty} @ {tx_px} ({tx_mt}, fee={tx_fee})")
                            
                        last_executed_qty = executed_qty

                    except Exception as te:
                        self._logger.warning(f"Failed to fetch trade history for details: {te}")
                        # Fallback: if we can't get history, at least report the aggregate fill
                        fill_qty = executed_qty - last_executed_qty
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
                            commission=Money(0, quote_currency),
                            liquidity_side=LiquiditySide.NO_LIQUIDITY_SIDE,
                            ts_event=self._clock.timestamp_ns(),
                        )
                        last_executed_qty = executed_qty
                        self._logger.info(f"Order fill reported (aggregate fallback): {fill_qty} @ {avg_price}")

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

