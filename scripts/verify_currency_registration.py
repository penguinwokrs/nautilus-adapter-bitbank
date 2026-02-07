
import asyncio
import os
import sys
from unittest.mock import MagicMock

# Add nautilus-adapter-bitbank/src to path if needed, 
# but assuming we are running from project root where package is installed or reachable.
sys.path.append(os.getcwd())

from nautilus_bitbank.execution import BitbankExecutionClient
from nautilus_bitbank.config import BitbankExecClientConfig
from nautilus_bitbank.factories import BitbankExecutionClientFactory
from nautilus_trader.model.currencies import Currency

from nautilus_trader.common.providers import InstrumentProvider

class MockInstrumentProvider(InstrumentProvider):
    def __init__(self):
        super().__init__()
        self.currencies = {}

    def instrument(self, instrument_id):
        return None

    def currency(self, code):

        return self.currencies.get(code)
    
    def add_currency(self, currency):
        self.currencies[currency.code] = currency
        print(f"MOCK: Added currency {currency.code}")

async def main():
    print("=== Verifying Bitbank Dynamic Currency Registration ===")
    
    from dotenv import load_dotenv
    load_dotenv("../../LUCA-IM/LUCA/.env")

    # 1. Config (Load from env if available, else dummy)
    api_key = os.getenv("BITBANK_API_KEY", "dummy_key")
    api_secret = os.getenv("BITBANK_API_SECRET", "dummy_secret")
    
    config = BitbankExecClientConfig(
        api_key=api_key,
        api_secret=api_secret,
    )
    
    # 2. Mock Components
    loop = asyncio.get_running_loop()
    msgbus = MagicMock()
    cache = MagicMock()
    # Mock cache to act as InstrumentProvider OR use our MockInstrumentProvider
    # In factory, we wrap cache if it's not a provider. 
    # Here we pass our mock provider directly.
    instrument_provider = MockInstrumentProvider()
    clock = MagicMock()
    
    # 3. Create Client (Wrapper to bypass strict __init__ checks)
    class TestClient(BitbankExecutionClient):
        def __init__(self, provider):
            self._instrument_provider = provider
            self.log = MagicMock()
            self.log.info.side_effect = print
            self.log.warning.side_effect = print
            self.log.error.side_effect = print
            self.loop = asyncio.get_running_loop()
            
            # mock rust client if needed? Not for this test.

    try:
        client = TestClient(instrument_provider)
        
        # 4. Run Registration
        print("Fetching currencies from Bitbank...")
        await client._register_all_currencies()
        
        # 5. Verify
        currencies = instrument_provider.currencies
        print(f"Registered {len(currencies)} currencies.")
        
        expected_currencies = ["BTC", "XRP", "ETH", "MONA", "BCC", "LTC"] # Some major ones
        for code in expected_currencies:
            if code in currencies:
                print(f"✅ {code} found (Dynamic)")
            else:
                # Check global model
                from nautilus_trader.model import currencies as model_currencies
                if getattr(model_currencies, code, None):
                     print(f"✅ {code} found (Global)")
                else:
                     print(f"❌ {code} NOT found")

        # Check a minor altcoin likely not in Nautilus globals
        minor_alt = "OAS" 
        if minor_alt in currencies:
             print(f"✅ {minor_alt} found (Dynamic - Likely new)")
        
    except Exception as e:
        print(f"❌ Validation failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    asyncio.run(main())
