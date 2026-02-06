use serde::{Deserialize, Serialize};

#[derive(Deserialize, Serialize, Debug, Clone)]
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

#[derive(Deserialize, Serialize, Debug, Clone)]
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

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct Trades {
    pub trades: Vec<Trade>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_order() {
        let json = r#"{
            "order_id": 999,
            "pair": "btc_jpy",
            "side": "buy",
            "type": "limit",
            "start_amount": "0.1",
            "remaining_amount": "0.1",
            "executed_amount": "0",
            "price": "1000000",
            "average_price": "0",
            "ordered_at": 1600000000000,
            "status": "UNFILLED"
        }"#;
        let order: Order = serde_json::from_str(json).unwrap();
        assert_eq!(order.order_id, 999);
        assert_eq!(order.order_type, "limit");
    }

    #[test]
    fn test_parse_trades() {
        let json = r#"{
            "trades": [
                {
                    "trade_id": 1,
                    "pair": "btc_jpy",
                    "order_id": 999,
                    "side": "buy",
                    "type": "limit",
                    "amount": "0.05",
                    "price": "1000000",
                    "maker_taker": "maker",
                    "fee_amount_base": "0",
                    "fee_amount_quote": "0",
                    "executed_at": 1600000000000
                }
            ]
        }"#;
        let trades: Trades = serde_json::from_str(json).unwrap();
        assert_eq!(trades.trades.len(), 1);
        assert_eq!(trades.trades[0].trade_id, 1);
    }
}
