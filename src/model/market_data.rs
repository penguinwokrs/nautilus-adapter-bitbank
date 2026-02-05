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
