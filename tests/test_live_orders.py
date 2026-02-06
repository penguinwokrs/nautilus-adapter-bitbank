#!/usr/bin/env python3
"""
Live Order Tests - Tests actual order execution with Bitbank API.

This test requires environment variables:
  - BITBANK_API_KEY
  - BITBANK_API_SECRET

WARNING: These tests execute REAL trades (small amounts).

Run with: pytest tests/test_live_orders.py -v -s
Skip in CI: pytest -m "not live"
"""
import asyncio
import os
import logging
import json
import pytest
from decimal import Decimal

from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.cache.cache import Cache
from nautilus_trader.model.identifiers import TraderId
from nautilus_trader.common.providers import InstrumentProvider

from nautilus_bitbank.data import BitbankDataClient
from nautilus_bitbank.execution import BitbankExecutionClient
from nautilus_bitbank.config import BitbankDataClientConfig, BitbankExecClientConfig

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("LiveOrderTest")


def get_credentials():
    """Get API credentials from environment variables."""
    api_key = os.environ.get("BITBANK_API_KEY", "")
    api_secret = os.environ.get("BITBANK_API_SECRET", "")
    return api_key, api_secret


def credentials_available():
    """Check if credentials are available."""
    api_key, api_secret = get_credentials()
    return bool(api_key and api_secret)


# Mark all tests in this file as live (requires real API)
pytestmark = [pytest.mark.live, pytest.mark.order]


class TestLiveOrders:
    """Live order tests - executes real trades."""
    
    @pytest.fixture
    async def clients(self):
        """Setup data and execution clients."""
        api_key, api_secret = get_credentials()
        
        loop = asyncio.get_event_loop()
        clock = LiveClock()
        trader_id = TraderId("ORDER-TEST")
        msgbus = MessageBus(trader_id=trader_id, clock=clock)
        cache = Cache(database=None)
        
        data_config = BitbankDataClientConfig(api_key=api_key, api_secret=api_secret)
        data_client = BitbankDataClient(
            loop=loop, config=data_config, msgbus=msgbus, cache=cache, clock=clock
        )
        
        exec_config = BitbankExecClientConfig(
            api_key=api_key, 
            api_secret=api_secret, 
            use_pubnub=False
        )
        instrument_provider = InstrumentProvider()
        
        exec_client = BitbankExecutionClient(
            loop=loop, config=exec_config, msgbus=msgbus, cache=cache,
            clock=clock, instrument_provider=instrument_provider
        )
        
        await data_client._connect()
        
        yield {
            "data_client": data_client,
            "exec_client": exec_client,
            "instrument_provider": instrument_provider
        }
        
        await data_client._disconnect()
    
    @pytest.mark.skipif(not credentials_available(), reason="BITBANK_API_KEY/SECRET not set")
    @pytest.mark.asyncio
    async def test_limit_buy_order_unfilled(self, clients):
        """Test placing a limit BUY order that won't fill (price too low)."""
        data_client = clients["data_client"]
        exec_client = clients["exec_client"]
        
        # Use XYM/JPY (cheap)
        pair = "xym_jpy"
        
        # Get current price
        ticker_json = await data_client._rest_client.get_ticker_py(pair)
        ticker = json.loads(ticker_json)
        current_price = Decimal(ticker.get("last", "0"))
        
        # Place order 50% below market (won't fill)
        buy_price = str(current_price * Decimal("0.50"))
        order_amount = "1"
        
        logger.info(f"Placing BUY order: {order_amount} XYM @ ¥{buy_price} (current: ¥{current_price})")
        
        order_id = None
        try:
            resp_json = await exec_client._rust_client.submit_order(
                pair, order_amount, "buy", "limit", "TEST-BUY-UNFILLED", buy_price
            )
            resp = json.loads(resp_json)
            order_id = resp.get("order_id")
            status = resp.get("status")
            
            logger.info(f"Order placed: id={order_id}, status={status}")
            
            assert order_id is not None, "Order should have an ID"
            assert status == "UNFILLED", f"Order should be UNFILLED, got {status}"
            
            # Check order status
            await asyncio.sleep(1)
            status_json = await exec_client._rust_client.get_order(pair, str(order_id))
            status_resp = json.loads(status_json)
            
            assert status_resp.get("status") == "UNFILLED", "Order should remain UNFILLED"
            
        finally:
            # Clean up - cancel the order
            if order_id:
                try:
                    cancel_json = await exec_client._rust_client.cancel_order(pair, str(order_id))
                    cancel_resp = json.loads(cancel_json)
                    logger.info(f"Order cancelled: status={cancel_resp.get('status')}")
                    assert "CANCELED" in cancel_resp.get("status", ""), "Order should be cancelled"
                except Exception as e:
                    logger.warning(f"Cancel failed (may already be cancelled): {e}")
    
    @pytest.mark.skipif(not credentials_available(), reason="BITBANK_API_KEY/SECRET not set")
    @pytest.mark.asyncio
    async def test_limit_sell_order_insufficient_funds(self, clients):
        """Test that SELL order fails with insufficient funds when no crypto held."""
        data_client = clients["data_client"]
        exec_client = clients["exec_client"]
        
        # Use a pair we definitely don't have balance for
        pair = "btc_jpy"
        
        # Get current price
        ticker_json = await data_client._rest_client.get_ticker_py(pair)
        ticker = json.loads(ticker_json)
        current_price = Decimal(ticker.get("last", "0"))
        
        # Try to sell at high price
        sell_price = str(current_price * Decimal("1.50"))
        order_amount = "0.0001"  # Minimum BTC amount
        
        logger.info(f"Attempting SELL order (expecting failure): {order_amount} BTC @ ¥{sell_price}")
        
        with pytest.raises(Exception) as exc_info:
            await exec_client._rust_client.submit_order(
                pair, order_amount, "sell", "limit", "TEST-SELL-FAIL", sell_price
            )
        
        # Should fail with insufficient funds (60001)
        error_msg = str(exc_info.value)
        logger.info(f"Expected error received: {error_msg}")
        assert "60001" in error_msg or "Insufficient" in error_msg, \
            f"Expected insufficient funds error, got: {error_msg}"
    
    @pytest.mark.skipif(not credentials_available(), reason="BITBANK_API_KEY/SECRET not set")
    @pytest.mark.asyncio
    async def test_order_lifecycle_cancel(self, clients):
        """Test full order lifecycle: place -> check -> cancel."""
        data_client = clients["data_client"]
        exec_client = clients["exec_client"]
        
        pair = "xym_jpy"
        
        # Get current price
        ticker_json = await data_client._rest_client.get_ticker_py(pair)
        ticker = json.loads(ticker_json)
        current_price = Decimal(ticker.get("last", "0"))
        
        # Place order far below market
        buy_price = str(current_price * Decimal("0.30"))
        order_amount = "1"
        
        order_id = None
        try:
            # 1. Place order
            resp_json = await exec_client._rust_client.submit_order(
                pair, order_amount, "buy", "limit", "TEST-LIFECYCLE", buy_price
            )
            resp = json.loads(resp_json)
            order_id = resp.get("order_id")
            
            assert order_id is not None
            logger.info(f"Step 1: Order placed, id={order_id}")
            
            # 2. Check order
            await asyncio.sleep(1)
            status_json = await exec_client._rust_client.get_order(pair, str(order_id))
            status_resp = json.loads(status_json)
            
            assert status_resp.get("order_id") == order_id
            assert status_resp.get("status") == "UNFILLED"
            logger.info(f"Step 2: Order status verified: {status_resp.get('status')}")
            
            # 3. Cancel order
            cancel_json = await exec_client._rust_client.cancel_order(pair, str(order_id))
            cancel_resp = json.loads(cancel_json)
            
            assert "CANCELED" in cancel_resp.get("status", "")
            logger.info(f"Step 3: Order cancelled: {cancel_resp.get('status')}")
            
            order_id = None  # Mark as cleaned up
            
        finally:
            if order_id:
                try:
                    await exec_client._rust_client.cancel_order(pair, str(order_id))
                except:
                    pass


# Allow running directly
if __name__ == "__main__":
    import sys
    
    if not credentials_available():
        print("ERROR: BITBANK_API_KEY and BITBANK_API_SECRET must be set")
        sys.exit(1)
    
    pytest.main([__file__, "-v", "-s"])
