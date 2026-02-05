use thiserror::Error;

#[derive(Error, Debug)]
pub enum BitbankError {
    #[error("API Request Error: {0}")]
    RequestError(#[from] reqwest::Error),

    #[error("WebSocket Error: {0}")]
    WebSocketError(#[from] tokio_tungstenite::tungstenite::Error),

    #[error("Parse Error: {0}")]
    ParseError(#[from] serde_json::Error),

    #[error("Authentication Error: {0}")]
    AuthError(String),

    #[error("Exchange Error: {code} - {message}")]
    ExchangeError {
        code: i32,
        message: String,
    },
    
    #[error("Unknown Error: {0}")]
    Unknown(String),
}
