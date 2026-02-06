import asyncio
import logging
import json
import os
from decimal import Decimal

from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.cache.cache import Cache
from nautilus_trader.model.identifiers import TraderId
from nautilus_trader.common.providers import InstrumentProvider

from nautilus_bitbank.data import BitbankDataClient
from nautilus_bitbank.execution import BitbankExecutionClient
from nautilus_bitbank.config import BitbankDataClientConfig, BitbankExecClientConfig

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ExecutionTest")

# Load credentials from environment variables
API_KEY = os.environ.get("BITBANK_API_KEY", "")
API_SECRET = os.environ.get("BITBANK_API_SECRET", "")

if not API_KEY or not API_SECRET:
    raise EnvironmentError("BITBANK_API_KEY and BITBANK_API_SECRET environment variables must be set")

async def main():
    logger.info("========================================")
    logger.info("  FULL EXECUTION TEST (BUY + SELL)     ")
    logger.info("  ⚠️ This will execute REAL trades!    ")
    logger.info("========================================")
    
    loop = asyncio.get_event_loop()
    clock = LiveClock()
    trader_id = TraderId("EXEC-TEST")
    msgbus = MessageBus(trader_id=trader_id, clock=clock)
    cache = Cache(database=None)
    
    data_config = BitbankDataClientConfig(api_key=API_KEY, api_secret=API_SECRET)
    data_client = BitbankDataClient(
        loop=loop, config=data_config, msgbus=msgbus, cache=cache, clock=clock
    )
    
    exec_config = BitbankExecClientConfig(api_key=API_KEY, api_secret=API_SECRET, use_pubnub=False)
    instrument_provider = InstrumentProvider()
    
    exec_client = BitbankExecutionClient(
        loop=loop, config=exec_config, msgbus=msgbus, cache=cache,
        clock=clock, instrument_provider=instrument_provider
    )

    try:
        await data_client._connect()
        
        instruments = await data_client.fetch_instruments()
        for inst in instruments:
            instrument_provider.add(inst)
        
        # Use XYM/JPY (cheapest)
        selected_pair = "xym_jpy"
        symbol = "XYM/JPY"
        
        # Get current ticker
        ticker_json = await data_client._rest_client.get_ticker_py(selected_pair)
        ticker = json.loads(ticker_json)
        
        # Get ask/bid prices
        ask_price = ticker.get("sell")  # Best ask (we buy at this price)
        bid_price = ticker.get("buy")   # Best bid (we sell at this price)
        last_price = Decimal(ticker.get("last", "0"))
        
        logger.info(f"===== {symbol} Market Data =====")
        logger.info(f"Last: ¥{last_price}")
        logger.info(f"Ask (sell orders): ¥{ask_price}")
        logger.info(f"Bid (buy orders): ¥{bid_price}")
        
        # Use last price if ask/bid is None
        if ask_price:
            buy_price = ask_price  # Buy at the ask price to ensure fill
        else:
            buy_price = str(last_price * Decimal("1.05"))  # 5% above last
            
        if bid_price:
            sell_price = bid_price  # Sell at the bid price to ensure fill
        else:
            sell_price = str(last_price * Decimal("0.95"))  # 5% below last
        
        # Order amount - buy 100 XYM (should cost ~37 JPY at 0.37/XYM)
        order_amount = "100"
        estimated_cost = Decimal(buy_price) * Decimal(order_amount)
        
        logger.info(f"Order amount: {order_amount} XYM")
        logger.info(f"BUY price: ¥{buy_price} (at ask)")
        logger.info(f"SELL price: ¥{sell_price} (at bid)")
        logger.info(f"Estimated cost: ¥{estimated_cost:.2f}")
        
        # ===== STEP 1: BUY Order (expect to fill immediately) =====
        logger.info("")
        logger.info("=" * 50)
        logger.info("STEP 1: Placing BUY order at ASK price...")
        logger.info("=" * 50)
        
        buy_order_id = None
        try:
            buy_resp_json = await exec_client._rust_client.submit_order(
                selected_pair,
                order_amount,
                "buy",
                "limit",
                "EXEC-BUY-001",
                buy_price
            )
            buy_resp = json.loads(buy_resp_json)
            buy_order_id = buy_resp.get("order_id")
            buy_status = buy_resp.get("status")
            executed = buy_resp.get("executed_amount", "0")
            remaining = buy_resp.get("remaining_amount", order_amount)
            
            logger.info(f"✅ BUY Response:")
            logger.info(f"   order_id: {buy_order_id}")
            logger.info(f"   status: {buy_status}")
            logger.info(f"   executed: {executed}")
            logger.info(f"   remaining: {remaining}")
            
        except Exception as e:
            logger.error(f"❌ BUY order failed: {e}")
            return

        # Wait and check status
        await asyncio.sleep(2)
        
        if buy_order_id:
            logger.info("Checking BUY order status...")
            try:
                status_json = await exec_client._rust_client.get_order(selected_pair, str(buy_order_id))
                status = json.loads(status_json)
                buy_final_status = status.get("status")
                executed = status.get("executed_amount", "0")
                logger.info(f"   Final status: {buy_final_status}")
                logger.info(f"   Executed: {executed} XYM")
                
                # Check trade history
                try:
                    trades_json = await exec_client._rust_client.get_trade_history(selected_pair, str(buy_order_id))
                    trades = json.loads(trades_json)
                    if trades.get("trades"):
                        logger.info("   Trades:")
                        for t in trades["trades"]:
                            logger.info(f"     - {t.get('amount')} @ ¥{t.get('price')}")
                except Exception as te:
                    logger.warning(f"   Could not fetch trades: {te}")
                    
            except Exception as e:
                logger.error(f"Failed to check BUY status: {e}")

        # ===== STEP 2: SELL Order (if we have XYM now) =====
        await asyncio.sleep(1)
        
        logger.info("")
        logger.info("=" * 50)
        logger.info("STEP 2: Placing SELL order at BID price...")
        logger.info("=" * 50)
        
        sell_order_id = None
        try:
            sell_resp_json = await exec_client._rust_client.submit_order(
                selected_pair,
                order_amount,
                "sell",
                "limit",
                "EXEC-SELL-001",
                sell_price
            )
            sell_resp = json.loads(sell_resp_json)
            sell_order_id = sell_resp.get("order_id")
            sell_status = sell_resp.get("status")
            executed = sell_resp.get("executed_amount", "0")
            remaining = sell_resp.get("remaining_amount", order_amount)
            
            logger.info(f"✅ SELL Response:")
            logger.info(f"   order_id: {sell_order_id}")
            logger.info(f"   status: {sell_status}")
            logger.info(f"   executed: {executed}")
            logger.info(f"   remaining: {remaining}")
            
        except Exception as e:
            logger.error(f"❌ SELL order failed: {e}")

        # Wait and check status
        await asyncio.sleep(2)
        
        if sell_order_id:
            logger.info("Checking SELL order status...")
            try:
                status_json = await exec_client._rust_client.get_order(selected_pair, str(sell_order_id))
                status = json.loads(status_json)
                sell_final_status = status.get("status")
                executed = status.get("executed_amount", "0")
                logger.info(f"   Final status: {sell_final_status}")
                logger.info(f"   Executed: {executed} XYM")
                
                # Check trade history
                try:
                    trades_json = await exec_client._rust_client.get_trade_history(selected_pair, str(sell_order_id))
                    trades = json.loads(trades_json)
                    if trades.get("trades"):
                        logger.info("   Trades:")
                        for t in trades["trades"]:
                            logger.info(f"     - {t.get('amount')} @ ¥{t.get('price')}")
                except Exception as te:
                    logger.warning(f"   Could not fetch trades: {te}")
                    
            except Exception as e:
                logger.error(f"Failed to check SELL status: {e}")

        logger.info("")
        logger.info("=" * 50)
        logger.info("  TEST COMPLETE  ")
        logger.info("=" * 50)

    except Exception as e:
        logger.error(f"Error during test: {e}", exc_info=True)
    finally:
        await data_client._disconnect()
        logger.info("Test finished.")

if __name__ == "__main__":
    asyncio.run(main())
