# -------------------------------------------------------------------------------------------------
#  Copyright (C) 2024 Penguinworks. All rights reserved.
#
#  Licensed under the GNU Lesser General Public License Version 3.0 (the "License");
#  You may not use this file except in compliance with the License.
#  You may obtain a copy of the License at https://www.gnu.org/licenses/lgpl-3.0.en.html
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
# -------------------------------------------------------------------------------------------------
"""
Bitbank instrument provider implementation.

Provides Nautilus instrument definitions from the Bitbank exchange.
"""

from decimal import Decimal
import json
import logging

from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.config import InstrumentProviderConfig
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import CurrencyPair
from nautilus_trader.model.objects import Currency, Price, Quantity


BITBANK_VENUE = Venue("BITBANK")

logger = logging.getLogger(__name__)


class BitbankInstrumentProvider(InstrumentProvider):
    """
    Provides Nautilus instrument definitions from Bitbank.

    Parameters
    ----------
    client : BitbankRestClient
        The Bitbank REST client (Rust backend).
    config : InstrumentProviderConfig, optional
        The instrument provider configuration, by default None.

    Examples
    --------
    >>> from nautilus_bitbank.providers import BitbankInstrumentProvider
    >>> provider = BitbankInstrumentProvider(client=rust_client)
    >>> await provider.load_all_async()
    >>> btc_jpy = provider.find(InstrumentId.from_str("BTC/JPY.BITBANK"))

    """

    def __init__(
        self,
        client,  # BitbankRestClient from Rust
        config: InstrumentProviderConfig | None = None,
    ) -> None:
        super().__init__(config=config)
        self._client = client
        self._log_warnings = config.log_warnings if config else True

    async def load_all_async(self, filters: dict | None = None) -> None:
        """
        Load all instruments from Bitbank.

        Parameters
        ----------
        filters : dict, optional
            Filters to apply (not currently used).

        """
        filters_str = "..." if not filters else f" with filters {filters}..."
        self._log.info(f"Loading all instruments{filters_str}")

        try:
            pairs_json = await self._client.get_pairs_py()
            pairs_data = json.loads(pairs_json)
            
            pairs = pairs_data.get("pairs", []) if isinstance(pairs_data, dict) else pairs_data
            
            for pair_info in pairs:
                try:
                    instrument = self._parse_instrument(pair_info)
                    if instrument:
                        self.add(instrument=instrument)
                except Exception as e:
                    if self._log_warnings:
                        self._log.warning(f"Failed to parse instrument: {e}")
            
            self._log.info(f"Loaded {len(self._instruments)} instruments from Bitbank")
            
        except Exception as e:
            self._log.error(f"Failed to load instruments: {e}")
            raise

    async def load_ids_async(
        self,
        instrument_ids: list[InstrumentId],
        filters: dict | None = None,
    ) -> None:
        """
        Load specific instruments by their IDs.

        Parameters
        ----------
        instrument_ids : list[InstrumentId]
            The instrument IDs to load.
        filters : dict, optional
            Filters to apply (not currently used).

        """
        if not instrument_ids:
            self._log.warning("No instrument IDs given for loading")
            return

        # Validate all instrument IDs
        for instrument_id in instrument_ids:
            if instrument_id.venue != BITBANK_VENUE:
                raise ValueError(
                    f"Instrument {instrument_id} is not for BITBANK venue"
                )

        # Load all and filter
        await self.load_all_async(filters)
        
        # Keep only requested instruments
        requested_ids = set(instrument_ids)
        for instrument_id in list(self._instruments.keys()):
            if instrument_id not in requested_ids:
                self._instruments.pop(instrument_id, None)

    async def load_async(
        self, 
        instrument_id: InstrumentId, 
        filters: dict | None = None
    ) -> None:
        """
        Load a single instrument by its ID.

        Parameters
        ----------
        instrument_id : InstrumentId
            The instrument ID to load.
        filters : dict, optional
            Filters to apply (not currently used).

        """
        await self.load_ids_async([instrument_id], filters)

    def _parse_instrument(self, pair_info: dict) -> CurrencyPair | None:
        """
        Parse a Bitbank pair info dict into a Nautilus CurrencyPair.

        Parameters
        ----------
        pair_info : dict
            The pair information from Bitbank API.

        Returns
        -------
        CurrencyPair or None
            The parsed instrument, or None if invalid.

        """
        # Check if pair is enabled/not suspended
        is_enabled = pair_info.get("is_enabled", True)
        is_suspended = pair_info.get("is_suspended", False)
        
        if is_suspended or (is_enabled is not None and not is_enabled):
            return None

        name = pair_info.get("name", "")
        base_asset = pair_info.get("base_asset", "").upper()
        quote_asset = pair_info.get("quote_asset", "").upper()
        
        if not base_asset or not quote_asset:
            return None

        # Parse precision
        price_precision = int(pair_info.get("price_digits", 0))
        size_precision = int(pair_info.get("amount_digits", 4))
        
        # Parse fees
        maker_fee = Decimal(pair_info.get("maker_fee_rate_quote", "0") or "0")
        taker_fee = Decimal(pair_info.get("taker_fee_rate_quote", "0") or "0")
        
        # Parse min/max amounts
        min_amount = pair_info.get("min_amount") or pair_info.get("unit_amount", "0.0001")
        max_amount = pair_info.get("max_amount")
        
        # Create symbol
        symbol_str = f"{base_asset}/{quote_asset}"
        
        # Build instrument
        instrument_id = InstrumentId(
            symbol=Symbol(symbol_str),
            venue=BITBANK_VENUE,
        )
        
        # Create currencies
        base_currency = Currency(
            code=base_asset,
            precision=size_precision,
            iso4217=0,
            name=base_asset,
            currency_type=1,  # CRYPTO
        )
        quote_currency = Currency(
            code=quote_asset,
            precision=price_precision if quote_asset == "JPY" else 8,
            iso4217=392 if quote_asset == "JPY" else 0,
            name=quote_asset,
            currency_type=2 if quote_asset == "JPY" else 1,  # FIAT or CRYPTO
        )
        
        # Price and size increments
        price_increment = Price(10 ** -price_precision, precision=price_precision)
        size_increment = Quantity(10 ** -size_precision, precision=size_precision)
        
        return CurrencyPair(
            instrument_id=instrument_id,
            raw_symbol=Symbol(name),
            base_currency=base_currency,
            quote_currency=quote_currency,
            price_precision=price_precision,
            size_precision=size_precision,
            price_increment=price_increment,
            size_increment=size_increment,
            lot_size=Quantity(1, precision=0),
            max_quantity=Quantity.from_str(max_amount) if max_amount else None,
            min_quantity=Quantity.from_str(str(min_amount)),
            max_price=None,
            min_price=None,
            margin_init=Decimal("0"),
            margin_maint=Decimal("0"),
            maker_fee=maker_fee,
            taker_fee=taker_fee,
            ts_event=0,
            ts_init=0,
        )
