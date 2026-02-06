# Nautilus Trader Adapter for Bitbank

A high-performance [Nautilus Trader](https://nautilustrader.io/) adapter for the [Bitbank](https://bitbank.cc/) cryptocurrency exchange, featuring a hybrid Python/Rust implementation for optimal speed and reliability.

## Features

### 🚀 High Performance
- **Rust-First Architecture**: Market data parsing and object creation happen in Rust, achieving throughput peaks of **>6M msgs/sec**.
- **Zero-JSON Bridging**: Uses `PyO3` to pass structured objects directly to Python, eliminating standard JSON processing overhead.
- **AsyncIO Integration**: Native integration with the Tokio runtime and Python's `asyncio`.

### 📊 Data Client
- **Real-time Market Data**: Streams Ticker, Trades, and Order Book (Depth) updates.
- **Efficient Order Book Management**: Rust-managed `OrderBook` handles incremental updates (`depth_diff`) and full snapshots (`depth_whole`) with zero overhead to Python.
- **Configurable Depth**: Optimized Top-N snapshots (default Top 20) are passed to Python, configurable via `BitbankDataClientConfig`.
- **Dynamic Instruments**: Automatically fetches trading pair metadata via `fetch_instruments`.
- **Configurable Network**: Supports HTTP timeouts and proxy settings for REST API interactions.

### ⚡ Execution Client
- **Order Management**: Full lifecycle support for Limit/Market orders.
- **Private Updates**: Low-latency order/trade updates via PubNub (fully configurable subscribe key).
- **Robust Error Mapping**: Maps Bitbank-specific API errors (e.g. 10009: Insufficient funds) directly to human-readable Python exceptions.

## Documentation
- [Developer Guide](docs/developer_guide.md): Information for developers/contributors.
- [Future Roadmap](docs/future_roadmap.md): Planned features and architecture changes.

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
