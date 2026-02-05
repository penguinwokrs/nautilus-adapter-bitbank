use serde::{Deserialize, Serialize};

#[derive(Deserialize, Serialize, Debug)]
pub struct Ticker {
    pub sell: String,
    pub buy: String,
    pub high: String,
    pub low: String,
    pub last: String,
    pub vol: String,
    pub timestamp: u64,
}

#[derive(Deserialize, Serialize, Debug)]
pub struct Depth {
    pub asks: Vec<Vec<String>>, 
    pub bids: Vec<Vec<String>>,
    pub timestamp: u64,
}

#[derive(Deserialize, Serialize, Debug)]
pub struct PairInfo {
    pub name: String,
    pub base_asset: String,
    pub quote_asset: String,
    pub maker_fee_rate: String,
    pub taker_fee_rate: String,
    pub unit_amount: String,
    pub limit_unit_amount: String,
    pub min_amount: String,
    pub max_amount: String,
    pub price_digits: i32,
    pub amount_digits: i32,
    pub is_suspended: bool,
}

#[derive(Deserialize, Serialize, Debug)]
pub struct PairsContainer {
    pub pairs: Vec<PairInfo>,
}
