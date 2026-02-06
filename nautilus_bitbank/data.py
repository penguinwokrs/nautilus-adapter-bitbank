import asyncio
import json
import logging
from typing import List

from nautilus_trader.live.data_client import LiveDataClient
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.identifiers import ClientId, Venue
from .config import BitbankDataClientConfig

try:
    from . import _nautilus_bitbank as bitbank
except ImportError:
    import _nautilus_bitbank as bitbank


class BitbankDataClient(LiveDataClient):
    """
    Rust-First implementation wrapper.
    Actual logic resides in bitbank.BitbankDataClient (Rust).
    """
    def __init__(self, loop, config: BitbankDataClientConfig, msgbus, cache, clock):
        super().__init__(
            loop=loop, 
            client_id=ClientId("BITBANK-DATA"),
            venue=Venue("BITBANK"),
            msgbus=msgbus, 
            cache=cache, 
            clock=clock, 
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
        # Delegate connection to Rust
        # Rust connects async and runs its own loop
        await self._rust_client.connect()
        self._logger.info("Connected to Bitbank via Rust client")

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
            await self._rust_client.subscribe(rooms)

    async def unsubscribe(self, instruments: List[Instrument]):
        pass

    def _handle_rust_data(self, room_name: str, data):
        """
        Callback from Rust.
        room_name: e.g. "ticker_btc_jpy"
        data: PyObject (Ticker, Depth, or Transactions) from Rust
        """
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


