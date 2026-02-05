# Nautilus Trader Adapter for Bitbank

A high-performance [Nautilus Trader](https://nautilustrader.io/) adapter for the [Bitbank](https://bitbank.cc/) cryptocurrency exchange, featuring a hybrid Python/Rust implementation for optimal speed and reliability.

## Features

### 🚀 High Performance
- **Core Logic in Rust**: WebSocket handling, HMAC-SHA256 signature generation, and JSON parsing are implemented in Rust using `pyo3` and `tokio`.
- **AsyncIO Integration**: Seamlessly integrates with Nautilus Trader's asyncio event loop.

### 📊 Data Client
- **Real-time Market Data**: streams Ticker, Trades (Transactions), and Order Book (Depth) updates.
- **Dynamic Instruments**: Automatically fetches and parses available currency pairs and their precision settings via `fetch_instruments`.
- **Reliability**: Implements automatic reconnection with exponential backoff and connection state management.

### ⚡ Execution Client
- **Order Management**: Supports Limit/Market orders (`SubmitOrder`) and cancellations (`CancelOrder`).
- **Smart Fills**: Polls order status and fetches detailed trade history to report:
  - Accurate executions (partial/full fills).
  - Exact fees (commissions) in quote currency.
  - Maker/Taker liquidity classification.
  - **PubNub Support (Experimental)**: Connects to Bitbank's private PubNub stream for low-latency updates.
- **Robustness**: Handles Bitbank-specific error codes (e.g., insufficient funds, minimum quantity errors) and maps them to human-readable messages.

## Installation

Requires **Rust** (stable) and **Python 3.10+**.

```bash
git clone https://github.com/penguinwokrs/nautilus-adapter-bitbank.git
cd nautilus-adapter-bitbank
pip install .
```

## Configuration

Set your Bitbank API credentials using environment variables or pass them directly to the configuration objects.

```bash
export BITBANK_API_KEY="your_api_key"
export BITBANK_API_SECRET="your_api_secret"
```

## Usage

Register the adapter factories with your `TradingNode`.

```python
import os
from nautilus_trader.trading.node import TradingNode, TradingNodeConfig
from nautilus_bitbank.config import BitbankDataClientConfig, BitbankExecClientConfig
from nautilus_bitbank.factories import BitbankDataClientFactory, BitbankExecutionClientFactory

# Load Config
api_key = os.getenv("BITBANK_API_KEY")
api_secret = os.getenv("BITBANK_API_SECRET")

# Configure Client
data_config = BitbankDataClientConfig(api_key=api_key, api_secret=api_secret)
exec_config = BitbankExecClientConfig(api_key=api_key, api_secret=api_secret)

# Setup Node
node = TradingNode(config=TradingNodeConfig(trader_id="MY-TRADER"))

# Register Factories
node.add_data_client_factory("BITBANK", BitbankDataClientFactory)
node.add_exec_client_factory("BITBANK", BitbankExecutionClientFactory)

# Configure Clients for the Node
node.config.data_clients["BITBANK"] = data_config
node.config.exec_clients["BITBANK"] = exec_config

# Build & Run
node.build()
# ... add instruments and start
```

## Architecture

- **`src/`**: Rust source code (WebSocket / REST client bindings).
- **`nautilus_bitbank/`**: Python adapter package.
  - **`data.py`**: `BitbankDataClient` implementation.
  - **`execution.py`**: `BitbankExecutionClient` implementation.
  - **`factories.py`**: Factory classes for node registration.

## License

MIT
