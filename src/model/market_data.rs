use serde::{Deserialize, Serialize};
use pyo3::prelude::*;

#[pyclass]
#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct Ticker {
    #[pyo3(get)]
    pub sell: String,
    #[pyo3(get)]
    pub buy: String,
    #[pyo3(get)]
    pub high: String,
    #[pyo3(get)]
    pub low: String,
    #[pyo3(get)]
    pub last: String,
    #[pyo3(get)]
    pub vol: String,
    #[pyo3(get)]
    pub timestamp: u64,
}

#[pymethods]
impl Ticker {
    #[new]
    pub fn new(sell: String, buy: String, high: String, low: String, last: String, vol: String, timestamp: u64) -> Self {
        Self { sell, buy, high, low, last, vol, timestamp }
    }
}

#[pyclass]
#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct Depth {
    #[pyo3(get)]
    pub asks: Vec<Vec<String>>, 
    #[pyo3(get)]
    pub bids: Vec<Vec<String>>,
    #[pyo3(get)]
    pub timestamp: u64,
    #[pyo3(get)]
    pub s: Option<u64>,
}

#[pymethods]
impl Depth {
    #[new]
    pub fn new(asks: Vec<Vec<String>>, bids: Vec<Vec<String>>, timestamp: u64, s: Option<u64>) -> Self {
        Self { asks, bids, timestamp, s }
    }
}

#[pyclass]
#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct DepthDiff {
    #[pyo3(get)]
    pub asks: Vec<Vec<String>>, 
    #[pyo3(get)]
    pub bids: Vec<Vec<String>>,
    #[pyo3(get)]
    pub timestamp: u64,
    #[pyo3(get)]
    pub s: u64, // Sequence is mandatory for diff
}

#[pymethods]
impl DepthDiff {
    #[new]
    pub fn new(asks: Vec<Vec<String>>, bids: Vec<Vec<String>>, timestamp: u64, s: u64) -> Self {
        Self { asks, bids, timestamp, s }
    }
}

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct PairInfo {
    pub name: String,
    pub base_asset: String,
    pub quote_asset: String,
    pub maker_fee_rate_base: String,
    pub taker_fee_rate_base: String,
    pub maker_fee_rate_quote: String,
    pub taker_fee_rate_quote: String,
    pub unit_amount: String,
    #[serde(default)]
    pub limit_unit_amount: Option<String>,
    pub min_amount: Option<String>,
    pub max_amount: Option<String>,
    pub price_digits: i32,
    pub amount_digits: i32,
    #[serde(rename = "is_suspended", default)]
    pub is_suspended_legacy: Option<bool>, // Some versions use is_suspended
    #[serde(rename = "is_enabled", default)]
    pub is_enabled: Option<bool>, 
}

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct PairsContainer {
    pub pairs: Vec<PairInfo>,
}

#[pyclass]
#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct Transaction {
    #[pyo3(get)]
    pub transaction_id: u64,
    #[pyo3(get)]
    pub side: String,
    #[pyo3(get)]
    pub price: String,
    #[pyo3(get)]
    pub amount: String,
    #[pyo3(get)]
    pub executed_at: u64,
}

#[pymethods]
impl Transaction {
    #[new]
    pub fn new(transaction_id: u64, side: String, price: String, amount: String, executed_at: u64) -> Self {
        Self { transaction_id, side, price, amount, executed_at }
    }
}

#[pyclass]
#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct Transactions {
    #[pyo3(get)]
    pub transactions: Vec<Transaction>,
}

#[pymethods]
impl Transactions {
    #[new]
    pub fn new(transactions: Vec<Transaction>) -> Self {
        Self { transactions }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_ticker() {
        let json = r#"{
            "sell": "1000000",
            "buy": "999000",
            "high": "1005000",
            "low": "990000",
            "last": "999500",
            "vol": "12.5",
            "timestamp": 1600000000000
        }"#;
        let ticker: Ticker = serde_json::from_str(json).unwrap();
        assert_eq!(ticker.sell, "1000000");
        assert_eq!(ticker.buy, "999000");
    }

    #[test]
    fn test_parse_depth() {
        let json = r#"{
            "asks": [["1001", "0.1"], ["1002", "0.2"]],
            "bids": [["999", "0.5"], ["998", "1.0"]],
            "timestamp": 1600000000000
        }"#;
        let depth: Depth = serde_json::from_str(json).unwrap();
        assert_eq!(depth.asks.len(), 2);
        assert_eq!(depth.asks[0][0], "1001");
    }

    #[test]
    fn test_parse_transactions() {
        let json = r#"{
            "transactions": [
                {
                    "transaction_id": 123,
                    "side": "buy",
                    "price": "1000",
                    "amount": "0.1",
                    "executed_at": 1600000000000
                }
            ]
        }"#;
        let txs: Transactions = serde_json::from_str(json).unwrap();
        assert_eq!(txs.transactions.len(), 1);
        assert_eq!(txs.transactions[0].transaction_id, 123);
    }
}
