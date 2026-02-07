import asyncio
import json
import logging
from typing import List

from nautilus_trader.live.data_client import LiveMarketDataClient
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.identifiers import ClientId, Venue
from .config import BitbankDataClientConfig

try:
    from . import _nautilus_bitbank as bitbank
except ImportError:
    import _nautilus_bitbank as bitbank


class BitbankDataClient(LiveMarketDataClient):
    """
    Rust-First implementation wrapper.
    Actual logic resides in bitbank.BitbankDataClient (Rust).
    """
    def __init__(self, loop, config: BitbankDataClientConfig, msgbus, cache, clock, instrument_provider=None):
        # Create a minimal instrument provider if not provided
        if instrument_provider is None:
            from nautilus_trader.common.providers import InstrumentProvider
            instrument_provider = InstrumentProvider()
        
        super().__init__(
            loop=loop, 
            client_id=ClientId("BITBANK-DATA"),
            venue=Venue("BITBANK"),
            msgbus=msgbus, 
            cache=cache, 
            clock=clock, 
            instrument_provider=instrument_provider,
            config=config
        )
        self.config = config
        self._logger = logging.getLogger(__name__)
        self._subscribed_instruments = {}  # format: "btc_jpy" -> Instrument

        # Instantiate Rust Client
        self._rust_client = bitbank.BitbankDataClient()
        self._rust_client.set_data_callback(self._handle_rust_data)
        
        self._rest_client = bitbank.BitbankRestClient(
            self.config.api_key or "",
            self.config.api_secret or "",
            self.config.timeout_ms,
            self.config.proxy_url
        )

    async def _connect(self):
        self._logger.info("BitbankDataClient connected")
        
        # Load instruments first
        await self._load_instruments()

        if self.config.use_pubnub:
            # Delegate connection to Rust (PubNub)
            await self._rust_client.connect()
            self._logger.info("Connected to Bitbank via Rust client (PubNub)")
        else:
            self._logger.info("PubNub disabled. Using REST polling (not implemented yet)")
            # TODO: Implement REST polling loop here if needed

    async def _disconnect(self):
        await self._rust_client.disconnect()

    async def subscribe(self, instruments: List[Instrument]):
        rooms = []
        for instrument in instruments:
            symbol = instrument.id.symbol
            pair = symbol.value.replace("/", "_").lower()
            self._subscribed_instruments[pair] = instrument
            
            rooms.extend([
                f"ticker_{pair}",
                f"transactions_{pair}",
                f"depth_whole_{pair}",
                f"depth_diff_{pair}"
            ])
        
        if rooms:
            self._logger.info(f"Subscribing to rooms: {rooms}")
            await self._rust_client.subscribe(rooms)

    async def unsubscribe(self, instruments: List[Instrument]):
        pass

    def _handle_rust_data(self, room_name: str, data):
        """
        Callback from Rust.
        room_name: e.g. "ticker_btc_jpy"
        data: PyObject (Ticker, Depth, or Transactions) from Rust
        """
        # self._logger.debug(f"Received data for {room_name}")
        try:
            # Extract pair and type
            if room_name.startswith("ticker_"):
                pair = room_name[len("ticker_"):]
                self._handle_ticker(pair, data)
            elif room_name.startswith("transactions_"):
                pair = room_name[len("transactions_"):]
                self._handle_transactions(pair, data)
            elif room_name.startswith("depth_whole_") or room_name.startswith("depth_diff_"):
                if room_name.startswith("depth_whole_"):
                    pair = room_name[len("depth_whole_"):]
                else:
                    pair = room_name[len("depth_diff_"):]
                self._handle_depth(pair, data)
                
        except Exception as e:
            self._logger.error(f"Error handling data from Rust: {e}")

    def _handle_ticker(self, pair: str, data: dict):
        instrument = self._subscribed_instruments.get(pair)
        if not instrument:
            return

        from nautilus_trader.model.data import QuoteTick
        from nautilus_trader.model.objects import Price, Quantity

        # Ticker object has attributes: sell, buy, timestamp
        bid = data.buy
        ask = data.sell
        ts = int(data.timestamp) * 1_000_000

        if bid and ask:
            quote = QuoteTick(
                instrument_id=instrument.id,
                bid_price=Price.from_str(str(bid)),
                ask_price=Price.from_str(str(ask)),
                bid_size=Quantity.from_str("0"), # bitbank ticker has no size
                ask_size=Quantity.from_str("0"),
                ts_event=ts,
                ts_init=self._clock.timestamp_ns(),
            )
            self._handle_data(quote)

    def _handle_transactions(self, pair: str, data: dict):
        instrument = self._subscribed_instruments.get(pair)
        if not instrument:
            return

        from nautilus_trader.model.data import TradeTick
        from nautilus_trader.model.objects import Price, Quantity
        from nautilus_trader.model.enums import AggressorSide
        from nautilus_trader.model.identifiers import TradeId

        # Transactions object has transactions list
        txs = data.transactions
        for tx in txs:
            # tx: Transaction object attributes: transaction_id, price, amount, executed_at, side
            price = tx.price
            amount = tx.amount
            side_str = tx.side
            ts = int(tx.executed_at) * 1_000_000
            
            aggressor_side = AggressorSide.BUYER if side_str == "buy" else AggressorSide.SELLER

            tick = TradeTick(
                instrument_id=instrument.id,
                price=Price.from_str(str(price)),
                size=Quantity.from_str(str(amount)),
                aggressor_side=aggressor_side,
                trade_id=TradeId(str(tx.transaction_id)),
                ts_event=ts,
                ts_init=self._clock.timestamp_ns(),
            )
            self._handle_data(tick)

    def _handle_depth(self, pair: str, data):
        instrument = self._subscribed_instruments.get(pair)
        if not instrument:
            return

        from nautilus_trader.model.data import OrderBookDelta, OrderBookDeltas, BookOrder
        from nautilus_trader.model.enums import BookAction, OrderSide
        from nautilus_trader.model.objects import Price, Quantity
        
        # OrderBook object from Rust
        # Using configurable depth for optimal performance
        top_asks, top_bids = data.get_top_n(self.config.order_book_depth)
        ts = int(data.timestamp) * 1_000_000
        ts_init = self._clock.timestamp_ns()

        deltas = []
        # Clear previous state to simulate a snapshot
        deltas.append(OrderBookDelta.clear(instrument.id, 0, ts, ts_init))
        
        for p, q in top_asks:
            order = BookOrder(OrderSide.SELL, Price.from_str(str(p)), Quantity.from_str(str(q)), 0)
            deltas.append(OrderBookDelta(instrument.id, BookAction.ADD, order, 0, 0, ts, ts_init))
            
        for p, q in top_bids:
            order = BookOrder(OrderSide.BUY, Price.from_str(str(p)), Quantity.from_str(str(q)), 0)
            deltas.append(OrderBookDelta(instrument.id, BookAction.ADD, order, 0, 0, ts, ts_init))

        snapshot = OrderBookDeltas(instrument.id, deltas)
        self._handle_data(snapshot)

    async def fetch_instruments(self) -> List[Instrument]:
        try:
            # Import dependencies locally to avoid circular imports
            from nautilus_trader.model.instruments import CurrencyPair
            from nautilus_trader.model.identifiers import InstrumentId, Symbol
            from nautilus_trader.model.objects import Price, Quantity
            from nautilus_trader.model.currencies import Currency
            from nautilus_trader.model.enums import CurrencyType
            from decimal import Decimal
            import nautilus_trader.model.currencies as currency_constants

            res_json = await self._rest_client.get_pairs_py()
            data = json.loads(res_json)
            pairs = data.get("pairs", [])
            
            instruments = []
            
            # 1. Collect all unique currency codes
            currency_codes = set()
            for p in pairs:
                currency_codes.add(p.get("base_asset").upper())
                currency_codes.add(p.get("quote_asset").upper())
            
            # 2. Resolve or create Currency objects and register to Cache
            resolved_currencies = {} # code -> Currency
            
            for code in currency_codes:
                # Try to get from Cache first
                currency = None
                if hasattr(self._cache, "currency"):
                    currency = self._cache.currency(code)
                
                # Try global constants
                if currency is None:
                    currency = getattr(currency_constants, code, None)
                
                # Create new if not found
                if currency is None:
                    # For unknown crypto assets
                    currency = Currency(code, 8, 0, code, CurrencyType.CRYPTO)
                    self._logger.info(f"Created new Currency object for {code}")

                resolved_currencies[code] = currency
                
                # Register to Cache if possible
                if hasattr(self._cache, "add_currency"):
                    try:
                        self._cache.add_currency(currency)
                    except Exception as e:
                        # Might already exist
                        pass

            # 3. Create Instruments
            for p in pairs:
                if not p.get("is_enabled", True) or p.get("is_suspended", False):
                    continue
                    
                base_code = p.get("base_asset").upper()
                quote_code = p.get("quote_asset").upper()
                pair_name = p.get("name") # e.g. "btc_jpy"
                
                # Construct InstrumentId (e.g. BTC/JPY.BITBANK)
                symbol_str = f"{base_code}/{quote_code}"
                instrument_id = InstrumentId.from_str(f"{symbol_str}.BITBANK")
                
                base_currency = resolved_currencies[base_code]
                quote_currency = resolved_currencies[quote_code]
                
                price_prec = int(p.get("price_digits"))
                qty_prec = int(p.get("amount_digits"))
                
                # Calculate increments
                price_inc = Decimal("1").scaleb(-price_prec)
                qty_inc = Decimal("1").scaleb(-qty_prec)
                min_qty_val = Decimal(p.get("min_amount") or "0")
                
                # Handle weird API values if any
                price_inc_str = f"{price_inc:.10f}".rstrip('0').rstrip('.')
                qty_inc_str = f"{qty_inc:.10f}".rstrip('0').rstrip('.')
                min_qty_str = f"{min_qty_val:.10f}".rstrip('0').rstrip('.')

                instrument = CurrencyPair(
                    instrument_id=instrument_id,
                    raw_symbol=Symbol(pair_name),
                    base_currency=base_currency,
                    quote_currency=quote_currency,
                    price_precision=price_prec,
                    size_precision=qty_prec,
                    price_increment=Price.from_str(price_inc_str),
                    size_increment=Quantity.from_str(qty_inc_str),
                    min_quantity=Quantity.from_str(min_qty_str),
                    lot_size=None,
                    max_quantity=None,
                    min_notional=None,
                    max_notional=None,
                    commission_maker=None, # Loaded from account/trade feedback usually
                    commission_taker=None,
                    is_retradable=True,
                )
                instruments.append(instrument)
                
                # Register to Cache/Provider immediately
                try:
                    if self._instrument_provider:
                        self._instrument_provider.add(instrument)
                    if self._cache:
                        self._cache.add_instrument(instrument)
                except Exception:
                    pass
            
            self._logger.info(f"Fetched and registered {len(instruments)} instruments (and {len(resolved_currencies)} currencies) from Bitbank")
            return instruments
            
        except Exception as e:
            self._logger.error(f"Error fetching instruments: {e}", exc_info=True)
            return []


    async def _subscribe_quote_ticks(self, command):
        instrument_id = command.instrument_id if hasattr(command, 'instrument_id') else command
        instrument = self._instrument_provider.find(instrument_id)
        if instrument is None and hasattr(self, '_cache'):
            instrument = self._cache.instrument(instrument_id)
            
        if instrument:
            await self.subscribe([instrument])
        else:
            self._logger.error(f"Could not find instrument {instrument_id} in provider or cache")

    async def _unsubscribe_quote_ticks(self, instrument_id):
        pass

    async def _subscribe_trade_ticks(self, command):
        instrument_id = command.instrument_id if hasattr(command, 'instrument_id') else command
        instrument = self._instrument_provider.find(instrument_id)
        if instrument is None and hasattr(self, '_cache'):
            instrument = self._cache.instrument(instrument_id)

        if instrument:
            await self.subscribe([instrument])
        else:
            self._logger.error(f"Could not find instrument {instrument_id} in provider or cache")

    async def _unsubscribe_trade_ticks(self, instrument_id):
        pass

    async def _subscribe_order_book_deltas(self, command):
        instrument_id = command.instrument_id if hasattr(command, 'instrument_id') else command
        instrument = self._instrument_provider.find(instrument_id)
        if instrument is None and hasattr(self, '_cache'):
            instrument = self._cache.instrument(instrument_id)

        if instrument:
            await self.subscribe([instrument])
        else:
            self._logger.error(f"Could not find instrument {instrument_id} in provider or cache")

    async def _unsubscribe_order_book_deltas(self, instrument_id):
        pass
    
    async def _subscribe_order_book_snapshots(self, instrument_id):
        pass

    async def _subscribe_bars(self, command):
        self._logger.warning("Bitbank does not support real-time Bars subscription. Ignoring.")

    async def _unsubscribe_bars(self, instrument_id):
        pass

    async def _unsubscribe_order_book_snapshots(self, instrument_id):
        pass

    async def _load_instruments(self):
        if not self.config.instrument_provider or not self.config.instrument_provider.load_ids:
            return
            
        # Try to fetch and register all instruments from API
        fetched = await self.fetch_instruments()
        
        if fetched:
            self._logger.info(f"Successfully loaded {len(fetched)} instruments via fetch_instruments")
            return

        # Fallback if API failed
        self._logger.warning("fetch_instruments failed or returned empty. Using manual fallback for BTC/JPY.")
        
        try:
            from nautilus_trader.model.instruments import CurrencyPair
            from nautilus_trader.model.identifiers import InstrumentId, Symbol
            from nautilus_trader.model.objects import Price, Quantity
            from nautilus_trader.model.currencies import Currency, JPY, BTC
            from decimal import Decimal

            # Minimal fallback
            def add_fallback(symbol_str, base, quote):
                 try:
                    instrument_id = InstrumentId.from_str(f"{symbol_str}.BITBANK")
                    if self._instrument_provider.find(instrument_id):
                        return

                    instrument = CurrencyPair(
                        instrument_id=instrument_id,
                        raw_symbol=Symbol(symbol_str),
                        base_currency=base,
                        quote_currency=quote,
                        price_precision=0,
                        size_precision=4,
                        price_increment=Price.from_str("1"),
                        size_increment=Quantity.from_str("0.0001"),
                        min_quantity=Quantity.from_str("0.0001"),
                        lot_size=None,
                        is_retradable=True,
                    )
                    
                    if self._instrument_provider:
                        self._instrument_provider.add(instrument)
                    if self._cache:
                        self._cache.add_instrument(instrument)
                        
                    self._logger.info(f"Added fallback instrument {instrument_id}")
                 except Exception as e:
                    self._logger.error(f"Failed to add fallback {symbol_str}: {e}")

            for instrument_id_str in self.config.instrument_provider.load_ids:
                 if "BTC/JPY" in instrument_id_str:
                      add_fallback("BTC/JPY", BTC, JPY)

        except Exception as e:
            self._logger.error(f"Fallback loading failed: {e}")


