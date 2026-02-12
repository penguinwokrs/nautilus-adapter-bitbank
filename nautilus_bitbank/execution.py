import asyncio
import json
import logging
from typing import Dict, List, Optional
from decimal import Decimal

from nautilus_trader.live.execution_client import LiveExecutionClient
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.model.orders import Order
from nautilus_trader.model.objects import Money, Currency, AccountBalance
from nautilus_trader.model.events import AccountState
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.currencies import JPY
from nautilus_trader.model.identifiers import Venue, ClientId, AccountId, VenueOrderId, TradeId
from nautilus_trader.model.enums import OrderSide, OrderType, OmsType, AccountType, OrderStatus, LiquiditySide
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
        self.log = logging.getLogger("nautilus.bitbank.execution")

    @property
    def account_id(self) -> AccountId:
        return self._account_id

    async def _connect(self):
        # Register all currencies first to ensure AccountState can resolve them
        await self._register_all_currencies()

        if self.config.use_pubnub:
            try:
                # Delegate Auth and Connect to Rust
                await self._rust_client.connect()
                self.log.info("PubNub stream started via Rust client")
                
                # Initial Account State Fetch
                try:
                    reports = await self.generate_account_status_reports()
                    if reports:
                        for report in reports:
                            self._send_account_state(report)
                        self.log.info(f"Published {len(reports)} account reports")
                except Exception as e:
                    self.log.error(f"Failed to fetch initial account state: {e}")

            except Exception as e:
                self.log.error(f"Failed to connect PubNub via Rust: {e}")

    async def _disconnect(self):
        self.log.info("BitbankExecutionClient disconnected")
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
            
            client_id = str(order.client_order_id)
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
        Handle incoming PubNub message from Rust client.
        """
        self.log.debug(f"PubNub Event Received: {event_type}")
        try:
            data = json.loads(message)
            if event_type == "OrderUpdate":
                venue_order_id = VenueOrderId(str(data.get("order_id")))
                pair = data.get("pair")
                # Trigger processing
                self.create_task(self._process_order_update_from_data(venue_order_id, pair, data))
            elif event_type == "TradeUpdate":
                # data is trade object: {"pair": "btc_jpy", "order_id": ..., "side": ..., "price": ..., "amount": ..., "fee_amount_base": ..., "fee_amount_quote": ..., "executed_at": ...}
                self.log.info(f"Received TradeUpdate via PubNub: {data}")
                venue_order_id = VenueOrderId(str(data.get("order_id")))
                pair = data.get("pair")
                self.create_task(self._process_order_update_from_data(venue_order_id, pair, data))
            elif event_type == "AssetUpdate":
                # data is a single asset update object
                self._process_asset_update(data)
            else:
                self.log.debug(f"Unknown PubNub Event: {event_type} - {message}")
        except Exception as e:
            self.log.error(f"Error handling PubNub message: {e}")

    def _process_asset_update(self, data: dict):
        """
        Process single asset update and generate AccountState.
        """
        try:
            asset_code = data.get("asset", "").upper()
            if not asset_code:
                return

            from nautilus_trader.model.objects import AccountBalance, Money

            # Dynamic currency resolution via instrument_provider
            currency = None
            if hasattr(self._instrument_provider, 'currency'):
                currency = self._instrument_provider.currency(asset_code)
            
            # Fallback to model constants if provider doesn't have it
            if currency is None:
                from nautilus_trader.model import currencies
                currency = getattr(currencies, asset_code, None)
            
            if currency is None:
                self.log.debug(f"Skipping unknown currency: {asset_code}")
                return

            total_val = int(Decimal(data.get("onhand_amount", "0")))
            locked_val = int(Decimal(data.get("locked_amount", "0")))
            free_val = total_val - locked_val 
            
            balance = AccountBalance(
                Money(total_val, currency),
                Money(locked_val, currency),
                Money(free_val, currency),
            )

            import time
            ts_now = int(time.time() * 1_000_000_000)  # Current time in nanoseconds
            
            account_state = AccountState(
                self._account_id,
                AccountType.CASH,  # bitbank is spot exchange
                None,              # No single base currency
                True,              # Is reported
                [balance],         # balances list
                [],                # margins (empty for spot)
                {},                # info dict
                UUID4(),           # event_id
                ts_now,            # ts_event
                ts_now,            # ts_init
            )
            self._send_account_state(account_state)
            self.log.info(f"Updated account state for {asset_code} via PubNub")
        except Exception as e:
            self.log.error(f"Failed to process asset update: {e}")

    async def _process_order_update_from_data(self, venue_order_id: VenueOrderId, pair: str, data: dict):
        # Retry logic for ClientOrderId lookup (handling race condition where PubNub arrives before REST return)
        client_oid = None
        for _ in range(10):
            client_oid = self._cache.client_order_id(venue_order_id)
            if client_oid:
                break
            await asyncio.sleep(0.1)

        if not client_oid:
            self._logger.warning(f"ClientOrderId not found for venue_order_id: {venue_order_id} after retries. Ignoring update.")
            return

        order = self._cache.order(client_oid)
        if not order:
            self._logger.warning(f"Order not found in cache for client_order_id: {client_oid}")
            return

        # Instrument to get quote currency for commission Money object
        instrument = self._instrument_provider.find(order.instrument_id)
        if instrument is None and hasattr(self, '_cache'):
            instrument = self._cache.instrument(order.instrument_id)

        quote_currency = JPY if not instrument else instrument.quote_currency
        
        await self._process_order_update(order, venue_order_id, pair, quote_currency, data)

    async def _process_order_update(self, order: Order, venue_order_id: VenueOrderId, pair: str, quote_currency, data: dict = None) -> bool:
        """
        Check order status and generate events.
        """
        try:
            if data is None:
                # Fallback to REST polling if no data provided
                resp_json = await self._rust_client.get_order(pair, str(venue_order_id))
                data = json.loads(resp_json)
            
            status = data.get("status")
            executed_qty = Decimal(data.get("executed_amount", "0"))
            
            # 1. Handle OrderAccepted (UNFILLED)
            # If we received an update (even UNFILLED), it means the venue knows about it.
            # Note: valid only if order is not yet accepted? 
            # Nautilus deduplicates events usually, but good to be explicit.
            if status == "UNFILLED":
                pass 

            # 2. Handle Fills
            oid_str = str(venue_order_id)
            if oid_str not in self._order_states:
                self._order_states[oid_str] = {
                    "last_executed_qty": Decimal("0"),
                    "reported_trades": set()
                }
            
            state = self._order_states[oid_str]
            last_qty = state["last_executed_qty"]
            
            if executed_qty > last_qty:
                delta = executed_qty - last_qty
                
                # Default values from payload
                avg_price = Decimal(data.get("average_price", "0") or "0")
                commission = Money(Decimal("0"), quote_currency)
                
                # Fetch detailed trade history for accurate Fee and Price
                new_trades = []
                try:
                    history_json = await self._rust_client.get_trade_history(pair, str(venue_order_id))
                    history = json.loads(history_json)
                    raw_trades = history.get("trades", [])
                    
                    new_trades = []
                    for t in raw_trades:
                        tid = str(t.get("trade_id"))
                        if tid not in state["reported_trades"]:
                            new_trades.append(t)
                            state["reported_trades"].add(tid)
                    
                    if new_trades:
                        total_fee = Decimal("0")
                        weighted_price_sum = Decimal("0")
                        total_trade_qty = Decimal("0")
                        
                        for t in new_trades:
                            qty = Decimal(t.get("amount", "0"))
                            px = Decimal(t.get("price", "0"))
                            fee = Decimal(t.get("fee_amount_quote", "0"))
                            
                            weighted_price_sum += qty * px
                            total_trade_qty += qty
                            total_fee += fee
                        
                        commission = Money(total_fee, quote_currency)
                        if total_trade_qty > 0:
                            avg_price = weighted_price_sum / total_trade_qty
                            
                except Exception as e:
                     self._logger.warning(f"Failed to fetch trade history for fill details: {e}. Using fallback values.")

                # Determine trade_id from trade history or generate fallback
                if new_trades:
                    trade_id = TradeId(str(new_trades[0].get("trade_id")))
                else:
                    trade_id = TradeId(str(venue_order_id) + "-" + str(int(delta * 10**8)))

                self.generate_order_filled(
                    strategy_id=order.strategy_id,
                    instrument_id=order.instrument_id,
                    client_order_id=order.client_order_id,
                    venue_order_id=venue_order_id,
                    venue_position_id=None,
                    trade_id=trade_id,
                    order_side=order.side,
                    order_type=order.order_type,
                    last_qty=delta,
                    last_px=avg_price,
                    quote_currency=quote_currency,
                    commission=commission,
                    liquidity_side=LiquiditySide.MAKER,
                    ts_event=self._clock.timestamp_ns(),
                )
                
                state["last_executed_qty"] = executed_qty

            # 3. Handle Cancel/Close
            if status in ("CANCELED_UNFILLED", "CANCELED_PARTIALLY_FILLED"):
                # Avoid duplicate cancel events if already processed via REST or previous update
                if order.status not in (OrderStatus.CANCELED, OrderStatus.FILLED, OrderStatus.EXPIRED):
                    self.generate_order_canceled(
                        strategy_id=order.strategy_id,
                        instrument_id=order.instrument_id,
                        client_order_id=order.client_order_id,
                        venue_order_id=venue_order_id,
                        ts_event=self._clock.timestamp_ns(),
                    )
                return True
                
            if status == "FILLED":
                return True

        except Exception as e:
            self._logger.error(f"Update processing failed: {e}")
            
        return False

    # Required abstract methods
    async def generate_order_status_reports(self, instrument_id=None, client_order_id=None):
        return []

    async def generate_account_status_reports(self, instrument_id=None, client_order_id=None):
        """
        Fetch assets from Bitbank and report AccountState.
        """
        try:
            reports = []
            
            # 1. Fetch assets via Rust
            assets_json = await self._rust_client.get_assets_py()
            self.log.debug(f"Fetched assets: {assets_json[:200]}...")  # Log first 200 chars only
            
            assets_data = json.loads(assets_json).get("assets", [])
            
            nautilus_balances = []
            for asset in assets_data:
                currency_str = asset["asset"].upper()
                try:
                    # Dynamic currency resolution
                    currency = None
                    if hasattr(self._instrument_provider, 'currency'):
                        currency = self._instrument_provider.currency(currency_str)
                    if currency is None:
                        from nautilus_trader.model import currencies
                        currency = getattr(currencies, currency_str, None)
                    
                    if currency is None:
                        continue  # Skip unknown currencies
                    
                    total = int(Decimal(asset["onhand_amount"]))
                    locked = int(Decimal(asset["locked_amount"]))
                    free = total - locked
                    
                    nautilus_balances.append(
                        AccountBalance(
                            Money(total, currency),
                            Money(locked, currency),
                            Money(free, currency),
                        )
                    )

                except Exception as e:
                    self._logger.error(f"Failed to parse balance for {currency_str}: {e}")
                    continue
            
            # Create AccountState
            # If nautilus_balances is empty, we must provide at least one balance (AccountState requires it)
            if not nautilus_balances:
                self.log.warning("No balances found, adding zero JPY balance")
                nautilus_balances.append(
                    AccountBalance(
                        Money(0, JPY),
                        Money(0, JPY),
                        Money(0, JPY),
                    )
                )


            account_state = AccountState(
                self._account_id,
                self.account_type,
                None,  # Multi-currency
                True,
                nautilus_balances,
                [],
                {},
                UUID4(),
                self._clock.timestamp_ns(),
                self._clock.timestamp_ns(),
            )

            reports.append(account_state)
            
            return reports
            
        except Exception as e:
            self._logger.error(f"Failed to generate account status reports: {e}", exc_info=True)
            return []

    async def generate_fill_reports(self, instrument_id=None, client_order_id=None):
        return []


    async def generate_position_status_reports(self, instrument_id=None):
        return []

    async def _register_all_currencies(self):
        """
        Dynamically register all Bitbank currencies to the InstrumentProvider (Cache).
        This allows handling assets that are not yet in nautilus_trader.model.currencies.
        """
        import json
        import urllib.request
        from nautilus_trader.model.currencies import Currency
        try:
            from nautilus_trader.model.enums import CurrencyType
        except ImportError:
            CurrencyType = None

        url = "https://api.bitbank.cc/v1/spot/pairs"
        
        def fetch_pairs():
            try:
                with urllib.request.urlopen(url, timeout=10) as response:
                    if response.status != 200:
                        return None
                    return json.loads(response.read().decode())
            except Exception as e:
                self.log.error(f"Failed to fetch pairs from Bitbank: {e}")
                return None

        # Run in executor to not block loop
        try:
            data = await self.loop.run_in_executor(None, fetch_pairs)
        except Exception:
            return

        if not data or data.get("success") != 1:
            return

        pairs_list = data["data"]["pairs"]
        codes = set()
        for p in pairs_list:
            codes.add(p["base_asset"].upper())
            codes.add(p["quote_asset"].upper())

        added_count = 0
        from nautilus_trader.model import currencies as model_currencies

        for code in codes:
            # Check provider first
            if hasattr(self._instrument_provider, "currency"):
                if self._instrument_provider.currency(code):
                    continue
            
            # Check globals
            if getattr(model_currencies, code, None):
                continue

            # Create new
            try:
                ctype = CurrencyType.CRYPTO
                if code in ("JPY", "USD", "EUR"):
                    ctype = CurrencyType.FIAT
                
                # Use positional args for v1.222.0 compatibility
                # Currency(code, precision, iso4217, name, currency_type)
                currency = Currency(code, 8, 0, code, ctype)
                
                if hasattr(self._instrument_provider, "add_currency"):
                    self._instrument_provider.add_currency(currency)
                    added_count += 1
            except Exception as e:
                self.log.warning(f"Could not add currency {code}: {e}")

        if added_count > 0:
            self.log.info(f"Dynamically registered {added_count} currencies from Bitbank public API")


