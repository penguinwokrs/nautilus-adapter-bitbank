use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct PubNubConnectParams {
    pub subscribe_key: String,
    pub channel: String,
    // Add other fields if bitbank returns them, e.g. uuid
}
