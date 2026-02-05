use serde::{Deserialize, Serialize};

#[derive(Deserialize, Serialize, Debug)]
pub struct Order {
    pub order_id: u64,
    pub pair: String,
    pub side: String,
    #[serde(rename = "type")]
    pub order_type: String,
    pub start_amount: String,
    pub remaining_amount: String,
    pub executed_amount: String,
    pub price: Option<String>, 
    pub average_price: String,
    pub ordered_at: u64,
    pub status: String,
    #[serde(default)]
    pub expire_at: Option<u64>,
    #[serde(default)]
    pub triggered_at: Option<u64>,
    #[serde(default)]
    pub trigger_price: Option<String>,
}

#[derive(Deserialize, Serialize, Debug)]
pub struct Trade {
    pub trade_id: u64,
    pub pair: String,
    pub order_id: u64,
    pub side: String,
    #[serde(rename = "type")]
    pub order_type: String,
    pub amount: String,
    pub price: String,
    pub maker_taker: String,
    pub fee_amount_base: String,
    pub fee_amount_quote: String,
    pub executed_at: u64,
}

#[derive(Deserialize, Serialize, Debug)]
pub struct Trades {
    pub trades: Vec<Trade>,
}
