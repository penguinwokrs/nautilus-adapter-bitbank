use pyo3::prelude::*;

mod client;
mod error;
mod model;

/// A Python module implemented in Rust.
#[pymodule]
fn _nautilus_bitbank(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<client::rest::BitbankRestClient>()?;
    m.add_class::<client::websocket::BitbankWebSocketClient>()?;
    Ok(())
}
