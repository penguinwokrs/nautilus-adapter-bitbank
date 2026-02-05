import asyncio
import json
import logging
from typing import Dict, List, Optional
from datetime import datetime

from decimal import Decimal
from nautilus_trader.live.data_client import LiveDataClient
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue, ClientId, TradeId
from nautilus_trader.model.data import QuoteTick, DataType
from nautilus_trader.model.objects import Price, Quantity, Money
from nautilus_trader.model.enums import LiquiditySide
from .config import BitbankDataClientConfig

try:
    from . import _nautilus_bitbank as bitbank
except ImportError:
    import _nautilus_bitbank as bitbank

class BitbankDataClient(LiveDataClient):
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
        
        # Validation for stability
        if not self.config.api_key or not self.config.api_secret:
            raise ValueError("BitbankDataClient requires both api_key and api_secret")
            
        self._logger = logging.getLogger(__name__)
        
        # REST Client for snapshot/initial data if needed
        self._rest_client = bitbank.BitbankRestClient(
            self.config.api_key,
            self.config.api_secret
        )
        
        # WebSocket Client
        self._ws_client = bitbank.BitbankWebSocketClient()
        self._ws_client.set_callback(self._handle_message)
        self._ws_client.set_disconnect_callback(self._on_ws_disconnect)
        
        self._connected = False
        self._reconnect_lock = asyncio.Lock()
        # Map instrument_id (str) -> Instrument
        self._subscribed_instruments: Dict[str, Instrument] = {}

    async def _connect(self):
        """Connect to Bitbank WebSocket with exponential backoff."""
        attempt = 0
        delay = 1.0
        max_delay = 60.0
        
        while True:
            self._logger.info(f"Connecting to Bitbank WebSocket (attempt {attempt + 1})...")
            try:
                await self._ws_client.connect_py()
                self._connected = True
                self._logger.info("Connected to Bitbank WebSocket")
                
                # Re-subscribe and handle existing subscriptions if any
                if self._subscribed_instruments:
                    await self.subscribe(list(self._subscribed_instruments.values()))
                break
            except Exception as e:
                attempt += 1
                self._logger.error(f"Failed to connect: {e}")
                self._connected = False
                
                self._logger.info(f"Retrying in {delay} seconds...")
                await asyncio.sleep(delay)
                delay = min(delay * 2, max_delay)

    async def _reconnect_safe(self):
        """Safely attempt to reconnect if not already connected."""
        async with self._reconnect_lock:
            if not self._connected:
                await self._connect()

    def _on_ws_disconnect(self):
        """Callback triggered when WebSocket connection is lost."""
        self._logger.warning("Bitbank WebSocket disconnected!")
        self._connected = False
        # Schedule reconnection on the main event loop
        if self.loop.is_running():
            self.loop.call_soon_threadsafe(
                lambda: asyncio.run_coroutine_threadsafe(self._reconnect_safe(), self.loop)
            )

    async def _disconnect(self):
        self._connected = False
        try:
            await self._ws_client.disconnect_py()
        except:
            pass
        self._logger.info("Disconnected")

    async def subscribe(self, instruments: List[Instrument]):
        for instrument in instruments:
            self._subscribed_instruments[instrument.id.value] = instrument
            
            symbol = instrument.id.symbol
            pair = symbol.value.replace("/", "_").lower()
            
            # Subscribe to Ticker
            await self._ws_client.subscribe_py(f"ticker_{pair}")
            
            # Subscribe to Transactions (TradeTicks)
            await self._ws_client.subscribe_py(f"transactions_{pair}")
            
            # Subscribe to Depth (OrderBook) - using depth_whole for simple full snapshot updates
            await self._ws_client.subscribe_py(f"depth_whole_{pair}")
            
            self._logger.info(f"Subscribed to ticker, transactions and depth for {pair}")

    async def unsubscribe(self, instruments: List[Instrument]):
        # Unsubscribe implementation would go here
        pass

    def _handle_message(self, msg: str):
        try:
            if not msg.startswith("42"):
                return
            
            payload_str = msg[2:]
            data_arr = json.loads(payload_str)
            
            if not isinstance(data_arr, list) or len(data_arr) < 2:
                return
                
            event_type = data_arr[0]
            if event_type != "message":
                return
                
            content = data_arr[1]
            room_name = content.get("room_name")
            message_body = content.get("message", {})
            data = message_body.get("data")
            
            if not data:
                return

            if room_name.startswith("ticker_"):
                self._handle_ticker(room_name, data)
            elif room_name.startswith("transactions_"):
                self._handle_transactions(room_name, data)
            elif room_name.startswith("depth_whole_"):
                self._handle_depth(room_name, data)
                
        except Exception as e:
            self._logger.error(f"Error handling message: {e} | Msg: {msg}")

    def _handle_depth(self, room_name: str, data: dict):
        pair = room_name.replace("depth_whole_", "")
        instrument = self._find_instrument(pair)
        
        if not instrument:
            return

        from nautilus_trader.model.data import OrderBookUpdate
        
        # Bitbank depth_whole data: {"bids": [["price", "amount"], ...], "asks": [...], "timestamp": ...}
        bids_raw = data.get("bids", [])
        asks_raw = data.get("asks", [])
        ts_event = int(data.get("timestamp", 0)) * 1_000_000
        
        # For a full snapshot in Nautilus, we can send it as an OrderBookUpdate
        # Note: In production, incremental updates (depth) are better for performance, 
        # but depth_whole is easier for a start.
        
        bids = [(Price.from_str(b[0]), Quantity.from_str(b[1])) for b in bids_raw]
        asks = [(Price.from_str(a[0]), Quantity.from_str(a[1])) for a in asks_raw]
        
        # Sort bids descending, asks ascending (Nautilus expects this)
        bids.sort(key=lambda x: x[0], reverse=True)
        asks.sort(key=lambda x: x[0])

        update = OrderBookUpdate(
            instrument_id=instrument.id,
            bids=bids,
            asks=asks,
            ts_event=ts_event,
            ts_init=self._clock.timestamp_ns(),
        )
        self._handle_data(update)

    def _handle_transactions(self, room_name: str, data: dict):
        pair = room_name.replace("transactions_", "")
        instrument = self._find_instrument(pair)
        
        if not instrument:
            return

        from nautilus_trader.model.data import TradeTick
        from nautilus_trader.model.enums import AggressorSide

        transactions = data.get("transactions", [])
        
        for tx in transactions:
            side_str = tx.get("side")
            price = tx.get("price")
            amount = tx.get("amount")
            ts_event = int(tx.get("executed_at", 0)) * 1_000_000
            
            if price and amount:
                side = AggressorSide.BUYER if side_str == "buy" else AggressorSide.SELLER
                
                tick = TradeTick(
                    instrument_id=instrument.id,
                    price=Price.from_str(price),
                    size=Quantity.from_str(amount),
                    aggressor_side=side,
                    trade_id=TradeId(str(tx.get("transaction_id"))),
                    ts_event=ts_event,
                    ts_init=self._clock.timestamp_ns(),
                )
                self._handle_data(tick)
        
    def _find_instrument(self, pair: str) -> Optional[Instrument]:
        for inst in self._subscribed_instruments.values():
            if inst.id.symbol.value.replace("/", "_").lower() == pair:
                return inst
        return None

    def _handle_ticker(self, room_name: str, data: dict):
        # Extract pair from room_name: ticker_btc_jpy
        pair = room_name.replace("ticker_", "")
        instrument = self._find_instrument(pair)
        
        if instrument:
            # Parse data
            # {"sell":"11339506","buy":"11337274","open":"...","high":"...","low":"...","last":"...","vol":"...","timestamp":1770258493976}
            ask_price = data.get("sell")
            bid_price = data.get("buy")
            # timestamp is in ms, convert to ns
            ts_event = int(data.get("timestamp", 0)) * 1_000_000
            
            if ask_price and bid_price:
                quote = QuoteTick(
                    instrument_id=instrument.id,
                    bid_price=Price.from_str(bid_price),
                    ask_price=Price.from_str(ask_price),
                    bid_size=Quantity.from_str("0"), # bitbank ticker doesn't provide size
                    ask_size=Quantity.from_str("0"),
                    ts_event=ts_event,
                    ts_init=self._clock.timestamp_ns(),
                )
                # Use _handle_data to properly route through DataEngine to Cache
                self._handle_data(quote)
                self._logger.debug(f"Handled QuoteTick for {instrument.id}: {bid_price}/{ask_price}")
            
            self._logger.info(f"TICKER {instrument.id}: Last={data.get('last')} @ {ts_event}")
            
    async def fetch_instruments(self) -> List[Instrument]:
        """Fetch all available currency pairs from Bitbank."""
        from nautilus_trader.model.instruments import CryptoInstrument
        from nautilus_trader.model.currencies import Currency
        from nautilus_trader.model.enums import AssetType
        
        try:
            resp_json = await self._rest_client.get_pairs_py()
            data = json.loads(resp_json)
            pairs = data.get("pairs", [])
            
            instruments = []
            for p in pairs:
                if p.get("is_suspended"):
                    continue
                
                name = p["name"] # e.g. btc_jpy
                base_asset = p["base_asset"].upper()
                quote_asset = p["quote_asset"].upper()
                
                # Convert btc_jpy -> BTC/JPY
                symbol = f"{base_asset}/{quote_asset}"
                
                inst = CryptoInstrument(
                    instrument_id=InstrumentId.from_str(f"{symbol}.{self.venue.value}"),
                    raw_symbol=Symbol(name),
                    base_currency=Currency.from_str(base_asset),
                    quote_currency=Currency.from_str(quote_asset),
                    price_precision=p["price_digits"],
                    size_precision=p["amount_digits"],
                    price_increment=Price.from_str(p["limit_unit_amount"]),
                    size_increment=Quantity.from_str(p["unit_amount"]),
                    lot_size=Quantity.from_str("1"),
                    max_quantity=Quantity.from_str(p["max_amount"]),
                    min_quantity=Quantity.from_str(p["min_amount"]),
                    max_notional=None,
                    min_notional=None,
                    margins=False,
                    is_inverse=False,
                    maker_fee=Decimal(p["maker_fee_rate"]),
                    taker_fee=Decimal(p["taker_fee_rate"]),
                    ts_event=self._clock.timestamp_ns(),
                    ts_init=self._clock.timestamp_ns(),
                )
                instruments.append(inst)
            
            self._logger.info(f"Fetched {len(instruments)} instruments from Bitbank")
            return instruments
            
        except Exception as e:
            self._logger.error(f"Failed to fetch instruments: {e}")
            return []

    # For testing from test_adapter.py (legacy)
    async def fetch_ticker(self, instrument_id: str):
        symbol = instrument_id.split(".")[0]
        pair = symbol.replace("/", "_").lower()
        json_str = await self._rest_client.get_ticker_py(pair)
        return json.loads(json_str)
