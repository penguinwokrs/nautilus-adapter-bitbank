# Developer Guide

This document provides technical details for developing, building, and testing the `nautilus-adapter-bitbank`.

## 1. Architecture: Rust-First

The adapter follows a **Rust-First** design philosophy to achieve high performance and reliability.

- **Rust Layer**: Handles network I/O (WebSockets via `tokio-tungstenite`, HTTP via `reqwest`), fast JSON parsing (`serde`), and state management. The market depth is managed entirely in Rust (see `OrderBook`), applying incremental updates and maintaining the L2 state to minimize Python overhead. Market data objects are exposed to Python as `pyclass` objects using `PyO3`.
- **Optimization**: By passing parsed Rust objects directly to Python, we eliminate the overhead of redundant JSON serialization/deserialization. Performance benchmarks show over **100x improvement** in market data throughput.
- **Python Layer**: Acts as a thin wrapper that integrates with the Nautilus Trader framework. It handles configuration, lifecycle management, and maps exchange-specific objects to Nautilus Trader's domain models (`QuoteTick`, `TradeTick`, `OrderBookDeltas`).

## 2. Development Setup

### Metrics
- **Performance**: Capable of processing >6,000,000 messages/sec (L2 depth snapshots) on standard hardware.
- **Concurrency**: Fully asynchronous using the Tokio runtime, integrated with Python's `asyncio` loop.

### Prerequisites
- **Rust**: Install via [rustup](https://rustup.rs/).
- **Python**: Version 3.10+ recommended.
- **Maturin**: Used for building the Rust extension.
  ```bash
  pip install maturin
  ```

### Build and Installation
To install the adapter in editable mode for development:
```bash
pip install -e .
```
This will compile the Rust components and link them to your Python environment. Any changes to the Rust code will require re-running this command to recompile (incremental builds are fast).

## 3. Performance Benchmarking

A benchmarking script is included to measure the throughput of the data client.

```bash
python3 benchmark_data.py
```

This script measures the time taken to process large Level 2 depth snapshots from the Rust layer to Python.

## 4. Testing

### Python Tests
We use `pytest` for unit and integration tests.
```bash
pytest tests/
```

### Rust Tests
Unit tests for parsing and core logic are located within the Rust files and can be run via:
```bash
cargo test
```

## 5. Coding Standards

- **Error Handling**: Custom `BitbankError` in Rust is mapped to Python exceptions in `src/error.rs`.
- **Model Exposure**: All market data models in `src/model/market_data.rs` should implement `#[pyclass]` with `#[pyo3(get)]` for efficient attribute access from Python.
- **PubNub Key**: The PubNub subscribe key is configurable via `BitbankExecClientConfig` and should not be hardcoded in the Rust implementation.

## 6. Directory Structure
- `src/`: Rust implementation of clients and models.
- `nautilus_bitbank/`: Python shim layer and configuration.
- `tests/`: Project test suite.
- `docs/`: Project documentation and roadmap.
