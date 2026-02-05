use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct PubNubConnectParams {
    pub pubnub_channel: String,
    pub pubnub_token: String,
}
