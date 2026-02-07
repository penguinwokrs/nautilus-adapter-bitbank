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
        from nautilus_trader.model.instruments import CurrencyPair
        from nautilus_trader.model.identifiers import InstrumentId, Symbol
        from nautilus_trader.model.objects import Price, Quantity, Currency
        from nautilus_trader.model.enums import CurrencyType
        import nautilus_trader.model.currencies as currencies
        
        def get_currency(code: str) -> Currency:
            code = code.upper()
            if hasattr(currencies, code):
                return getattr(currencies, code)
            return Currency(code, 8, 0, code, CurrencyType.CRYPTO)

        try:
            res_json = await self._rest_client.get_pairs_py()
            data = json.loads(res_json)
            pairs = data.get("pairs", [])
            
            instruments = []
            for p in pairs:
                if not p.get("is_enabled", True) or p.get("is_suspended", False):
                    continue
                    
                base = p.get("base_asset").upper()
                quote = p.get("quote_asset").upper()
                pair_name = p.get("name") # e.g. "btc_jpy"
                symbol = f"{base}/{quote}"
                
                instrument = CurrencyPair(
                    InstrumentId.from_str(f"{symbol}.BITBANK"),
                    Symbol(pair_name),
                    get_currency(base),
                    get_currency(quote),
                    int(p.get("price_digits")),
                    int(p.get("amount_digits")),
                    Price.from_str(f"{10.0**-p.get('price_digits'):.10f}".rstrip('0').rstrip('.')),
                    Quantity.from_str(f"{10.0**-p.get('amount_digits'):.10f}".rstrip('0').rstrip('.')),
                    Quantity.from_str(p.get("min_amount") or "0"),
                    True, # is_retradable
                )
                instruments.append(instrument)
            
            self._logger.info(f"Fetched {len(instruments)} instruments from Bitbank")
            return instruments
            
        except Exception as e:
            self._logger.error(f"Error fetching instruments: {e}")
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
        
        load_ids = list(self.config.instrument_provider.load_ids)

        try:
            import aiohttp
            from nautilus_trader.model.instruments import CurrencyPair
            from nautilus_trader.model.identifiers import Symbol, Venue, InstrumentId
            from nautilus_trader.model.objects import Price, Quantity
            from nautilus_trader.model.currencies import Currency
            from decimal import Decimal
        except ImportError as e:
            self._logger.error(f"Imports failed: {e}")
            return
            
        # Helper to add instrument manually
        def add_manual_instrument(symbol_str: str, base: str, quote: str, p_prec: int, q_prec: int, min_q: str):
             try:
                instrument_id = InstrumentId.from_str(f"{symbol_str}.BITBANK")
                
                # Check if already exists in provider but allow updating cache if needed
                exists_in_provider = False
                try: 
                    if self._instrument_provider.find(instrument_id):
                        exists_in_provider = True
                except:
                    pass

                price_inc = Decimal("1").scaleb(-p_prec)
                qty_inc = Decimal("1").scaleb(-q_prec)
                
                # Use CurrencyPair for spot instruments
                instrument = CurrencyPair(
                    instrument_id=instrument_id,
                    raw_symbol=Symbol(symbol_str),
                    base_currency=Currency.from_str(base),
                    quote_currency=Currency.from_str(quote),
                    price_precision=p_prec,
                    size_precision=q_prec,
                    price_increment=Price(price_inc, p_prec),
                    size_increment=Quantity(qty_inc, q_prec),
                    ts_event=0,
                    ts_init=0,
                    min_quantity=Quantity(Decimal(min_q), q_prec),
                    lot_size=None,
                )
                
                if not exists_in_provider:
                    self._instrument_provider.add(instrument)
                    self._logger.info(f"Loaded fallback instrument {instrument_id} to provider")
                
                # Also add to Cache to ensure RiskEngine and Strategy see it
                if self._cache:
                    self._cache.add_instrument(instrument)
             except Exception as e:
                self._logger.error(f"Failed to add manual instrument {symbol_str}: {e}")

        # Try fetching from API
        url = "https://public.bitbank.cc/bitbankcc/pairs"
        data = None
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                    else:
                        self._logger.warning(f"Failed to fetch pairs API: {response.status}. Using manual fallback.")
        except Exception as e:
            self._logger.warning(f"Error fetching pairs API: {e}. Using manual fallback.")

        # Process API data if available
        if data:
            pairs_data = data.get("data", {}).get("pairs", [])
            pairs_map = {p["name"]: p for p in pairs_data}

            for instrument_id_str in self.config.instrument_provider.load_ids:
                try:
                    # Handle both 'BTC/JPY.BITBANK' and 'BTC/JPY' formats
                    if "." in instrument_id_str:
                         native_symbol = instrument_id_str.split(".")[0]
                    else:
                         native_symbol = instrument_id_str
                    
                    pair_name = native_symbol.replace("/", "_").lower()
                    info = pairs_map.get(pair_name)
                    
                    if info:
                        base = info["base_asset"].upper()
                        quote = info["quote_asset"].upper()
                        p_prec = int(info["price_digits"])
                        q_prec = int(info["amount_digits"])
                        min_q = info["unit_amount"]
                        add_manual_instrument(native_symbol, base, quote, p_prec, q_prec, min_q)
                    else:
                        # Fallback if specific pair not in API result
                        self._logger.info(f"Pair {pair_name} not in API data, trying fallback")
                        if "BTC/JPY" in instrument_id_str:
                             add_manual_instrument("BTC/JPY", "BTC", "JPY", 0, 4, "0.0001")
                except Exception as e:
                    self._logger.error(f"Error processing instrument {instrument_id_str}: {e}")
        else:
            # Full Fallback (API failed)
            for instrument_id_str in self.config.instrument_provider.load_ids:
                if "BTC/JPY" in instrument_id_str:
                     add_manual_instrument("BTC/JPY", "BTC", "JPY", 0, 4, "0.0001")


