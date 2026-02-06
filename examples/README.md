# Bitbank Adapter Examples

This directory contains example scripts demonstrating how to use the Bitbank adapter with Nautilus Trader.

## Prerequisites

All examples require the following environment variables:

```bash
export BITBANK_API_KEY="your_api_key"
export BITBANK_API_SECRET="your_api_secret"
```

## Examples

### 1. Start Node (`start_node.py`)

Basic example of starting a Nautilus TradingNode with the Bitbank adapter.

```bash
python examples/start_node.py
```

### 2. Subscribe Data (`subscribe_data.py`)

Shows how to subscribe to real-time market data (quotes, order book).

```bash
python examples/subscribe_data.py
```

### 3. Simple Strategy (`simple_strategy.py`)

Demonstrates a simple Moving Average Crossover strategy.

**Features:**
- Short and long period MA calculation
- Buy/sell signal generation
- Integration with TradingNode

```bash
python examples/simple_strategy.py
```

### 4. Manual Orders (`manual_orders.py`)

Step-by-step demonstration of order management:
- Place limit orders
- Check order status
- Cancel orders
- View active orders

```bash
python examples/manual_orders.py
```

### 5. Multi-Symbol Monitor (`multi_symbol.py`)

Real-time price monitor for multiple trading pairs.

**Features:**
- Subscribes to multiple pairs simultaneously
- Color-coded price changes
- Auto-refreshing display

```bash
python examples/multi_symbol.py
```

### 6. Fetch History (`fetch_history.py`)

Downloads historical data and saves to CSV for backtesting.

**Features:**
- Recent trades
- Order book snapshots
- CSV export

```bash
python examples/fetch_history.py
```

### 7. Account Info (`account_info.py`)

Displays account information:
- Asset balances
- Active orders
- Trade history

```bash
python examples/account_info.py
```

## Notes

⚠️ **Warning**: Some examples (like `manual_orders.py`) execute real orders. Use caution and small amounts when testing.

All examples use environment variables for credentials. Never hardcode API keys in source files.
