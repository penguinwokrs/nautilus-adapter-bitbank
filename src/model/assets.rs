use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct Asset {
    pub asset: String,
    pub amount_precision: i32,
    pub onhand_amount: String,
    pub locked_amount: String,
    pub free_amount: String,
    pub stop_deposit: bool,
    pub stop_withdrawal: bool,
    pub withdrawal_fee: serde_json::Value,
}

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct Assets {
    pub assets: Vec<Asset>,
}

#[derive(Debug, Deserialize, Serialize, Clone)]
#[serde(untagged)]
pub enum VariantWrapper {
    String(String),
    Float(f64),
}
