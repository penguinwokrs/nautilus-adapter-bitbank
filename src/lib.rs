#![allow(non_local_definitions)]

use pyo3::prelude::*;

mod client;
mod error;
mod model;

/// A Python module implemented in Rust.
#[pymodule]
fn _nautilus_bitbank(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<client::rest::BitbankRestClient>()?;
    m.add_class::<client::websocket::BitbankWebSocketClient>()?;
    m.add_class::<client::pubnub::PubNubClient>()?;
    m.add_class::<client::data_client::BitbankDataClient>()?;
    m.add_class::<client::execution_client::BitbankExecutionClient>()?;
    
    // Models
    m.add_class::<model::market_data::Ticker>()?;
    m.add_class::<model::market_data::Depth>()?;
    m.add_class::<model::market_data::DepthDiff>()?;
    m.add_class::<model::market_data::Transaction>()?;
    m.add_class::<model::market_data::Transactions>()?;
    m.add_class::<model::orderbook::OrderBook>()?;
    Ok(())
}
