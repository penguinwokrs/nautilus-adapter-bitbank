# Future Roadmap & Refactoring Plan: Rust-First Architecture

## Overview
This document outlines the strategic pivot to a **Rust-First** architecture for `nautilus-adapter-bitbank`. Following the design pattern of official Nautilus Trader adapters (e.g., Binance), correct modularity and high performance will be achieved by implementing the core adapter components directly in Rust.

## 1. Architecture: Rust-First

In this new architecture, the Python layer is minimized to configuration and simple factory instantiation. The heavy lifting—state management, network I/O, parsing, and event loop integration—is handled entirely within Rust structs exposed via PyO3.

### Core Components (Rust)

#### `BitbankDataClient`
A Rust struct exposed to Python.
*   **Responsibilities**:
    *   Manages WebSocket connections (Tokio tasks).
    *   Handles subscription state and recovery.
    *   Parses raw WebSocket messages into Nautilus domain objects (QuoteTick, TradeTick, etc.).
    *   Directly interacts with the Nautilus event bus (or passes objects back to Python callback handlers efficiently).

#### `BitbankExecutionClient`
A Rust struct exposed to Python.
*   **Responsibilities**:
    *   Manages REST API interactions (Reqwest).
    *   Handles Order lifecycle state (Open, Filled, Canceled).
    *   Manages PubNub connection for real-time updates.
    *   Implements `submit_order`, `cancel_order`, etc., entirely in Rust.

### Proposed Directory Structure

```text
nautilus_bitbank/
├── __init__.py
├── config.py               # Python Configuration Dataclasses
├── factories.py            # Factories instantiating Rust classes
└── _nautilus_bitbank.so    # Compiled Rust Extension (artifacts)
```

**Note**: `data.py` and `execution.py` will be removed or reduced to simple shims importing the Rust classes.

## 2. Refactoring Steps

### Phase 1: Rust Client Foundation
*   Refactor `src/lib.rs` to expose `BitbankDataClient` and `BitbankExecutionClient` classes.
*   Move existing `client/rest.rs` and `client/websocket.rs` logic into these new storage structs.

### Phase 2: Internal Rust Modularity
Inside the Rust crate, ensure clear separation of concerns:
*   `src/parsing/`: specific parsing logic for Ticker, Trades, OrderBook.
*   `src/connectivity/`: WebSocket and HTTP handlers.
*   `src/orderbook/`: L2 OrderBook management (applying snapshots/diffs).

### Phase 3: Python Cleanup
*   Remove legacy Python implementation in `nautilus_bitbank/data.py` and `nautilus_bitbank/execution.py`.
*   Update `factories.py` to return the Rust-implemented instances.

## 3. Feature Improvements

### A. Level 2 Order Book (High Performance)
**Status**: Implemented.
**Detail**:
1.  Rust-managed `OrderBook` struct handles `depth_whole` and `depth_diff`.
2.  State is maintained in Rust memory with sequence number validation.
3.  Optimized Top-N extraction (configurable depth) for Python.

### B. PubNub Integration (Rust)
**Status**: Python Prototype.
**Plan**:
1.  Port the PubNub subscription and message handling logic to Rust (using `tungstenite` or a Rust PubNub crate if compatible).
2.  Integrate into the `BitbankExecutionClient` struct.

## 4. Immediate Next Steps

1.  **Repo Structure**: Clean up Python files to align with the new thin-wrapper goal.
2.  **Rust Scaffolding**: Create the `DataClient` struct in `src/lib.rs` and verify it can be instantiated from Python.
3.  **Parsing Migration**: Port Ticker parsing to Rust and wire it up to the `DataClient`.
