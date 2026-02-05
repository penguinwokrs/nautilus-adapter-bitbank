pub mod market_data;
pub mod order;
pub mod pubnub;

use serde::Deserialize;

#[derive(Deserialize, Debug)]
pub struct BitbankResponse<T> {
    pub success: i32,
    pub data: T,
}

#[derive(Deserialize, Debug)]
pub struct BitbankErrorResponse {
    pub success: i32,
    pub data: BitbankErrorData,
}

#[derive(Deserialize, Debug)]
pub struct BitbankErrorData {
    pub code: i32,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
}
