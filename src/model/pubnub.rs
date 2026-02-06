use serde::{Deserialize, Serialize};
use crate::model::order::Order;

#[allow(dead_code)]
#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct PubNubMessage {
    pub data: Order,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct PubNubConnectParams {
    pub pubnub_channel: String,
    pub pubnub_token: String,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_pubnub_message() {
        let json_data = r#"
        {
            "data": {
                "order_id": 1001,
                "pair": "btc_jpy",
                "side": "buy",
                "type": "limit",
                "start_amount": "0.1",
                "remaining_amount": "0.05",
                "executed_amount": "0.05",
                "price": "1200000",
                "average_price": "1200000",
                "ordered_at": 1600000000,
                "status": "PARTIALLY_FILLED",
                "expire_at": 1600003600,
                "triggered_at": null,
                "trigger_price": null
            }
        }
        "#;

        let msg: PubNubMessage = serde_json::from_str(json_data).expect("Failed to parse");
        
        assert_eq!(msg.data.order_id, 1001);
        assert_eq!(msg.data.pair, "btc_jpy");
        assert_eq!(msg.data.status, "PARTIALLY_FILLED");
        assert_eq!(msg.data.remaining_amount, "0.05");
        assert_eq!(msg.data.expire_at, Some(1600003600));
    }
}
