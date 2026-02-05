import asyncio
import json
import logging
from typing import Dict, List, Optional
from datetime import datetime

from nautilus_trader.live.data_client import LiveDataClient
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.identifiers import InstrumentId
from .config import BitbankDataClientConfig


try:
    from . import _nautilus_bitbank as bitbank
except ImportError:
    # Fallback or dev handling
    import _nautilus_bitbank as bitbank

from nautilus_trader.model.identifiers import Venue, ClientId

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
        self._logger = logging.getLogger(__name__)
        
        # REST Client for snapshot/initial data if needed
        self._rest_client = bitbank.BitbankRestClient(
            self.config.api_key or "", 
            self.config.api_secret or ""
        )
        
        # WebSocket Client
        self._ws_client = bitbank.BitbankWebSocketClient()
        self._ws_client.set_callback(self._handle_message)
        
        self._connected = False
        # Map instrument_id (str) -> Instrument
        self._subscribed_instruments: Dict[str, Instrument] = {}

    async def _connect(self):
        self._logger.info("Connecting to Bitbank WebSocket...")
        try:
            await self._ws_client.connect_py()
            self._connected = True
            # LiveDataClient parent usually handles CONNECTED state via signals/events
            # For now just log
            self._logger.info("Connected to Bitbank WebSocket")
        except Exception as e:
            self._logger.error(f"Failed to connect: {e}")
            raise

    async def _disconnect(self):
        self._connected = False
        # WS client doesn't have disconnect method exposed yet in Rust, 
        # but dropping it or closing loop usually works. 
        self._logger.info("Disconnected")

    async def subscribe(self, instruments: List[Instrument]):
        for instrument in instruments:
            self._subscribed_instruments[instrument.id.value] = instrument
            
            # Subscribe to Ticker (as a baseline)
            # Format: BTC/JPY -> btc_jpy
            symbol = instrument.id.symbol
            pair = symbol.value.replace("/", "_").lower()
            
            room_id = f"ticker_{pair}"
            await self._ws_client.subscribe_py(room_id)
            self._logger.info(f"Subscribed to {room_id}")

    async def unsubscribe(self, instruments: List[Instrument]):
        # Unsubscribe implementation would go here
        pass

    def _handle_message(self, msg: str):
        # Format: 42["message",{"room_name":"...","message":{...}}]
        try:
            if not msg.startswith("42"):
                return
            
            payload_str = msg[2:]
            data_arr = json.loads(payload_str)
            # data_arr: ["message", { ... }]
            
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
                
        except Exception as e:
            self._logger.error(f"Error handling message: {e} | Msg: {msg}")

    def _handle_ticker(self, room_name: str, data: dict):
        # Extract pair from room_name: ticker_btc_jpy
        pair = room_name.replace("ticker_", "")
        # Find matching instrument
        # This is inefficient 0(N), optimization needed later
        instrument = None
        for inst_id_str, inst in self._subscribed_instruments.items():
            # inst.id.symbol is BTC/JPY
            if inst.id.symbol.value.replace("/", "_").lower() == pair:
                instrument = inst
                break
        
        if instrument:
            # Parse data
            # {"sell":"11339506","buy":"11337274","open":"...","high":"...","low":"...","last":"...","vol":"...","timestamp":1770258493976}
            # For LiveDataClient, we would normally use self._msgbus to publish QuoteTick or TradeTick.
            # Since this is initial impl, logging is fine.
            last_price = data.get("last")
            timestamp = data.get("timestamp")
            
            self._logger.info(f"TICKER {instrument.id}: Last={last_price} @ {timestamp}")
            
    # For testing from test_adapter.py (legacy)
    async def fetch_ticker(self, instrument_id: str):
        symbol = instrument_id.split(".")[0]
        pair = symbol.replace("/", "_").lower()
        json_str = await self._rest_client.get_ticker_py(pair)
        return json.loads(json_str)
