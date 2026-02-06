use thiserror::Error;
use pyo3::prelude::*;

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

impl From<BitbankError> for PyResult<()> {
    fn from(err: BitbankError) -> Self {
        Err(PyErr::from(err))
    }
}

impl From<BitbankError> for PyErr {
    fn from(err: BitbankError) -> Self {
        match err {
            BitbankError::AuthError(e) => pyo3::exceptions::PyPermissionError::new_err(e),
            BitbankError::ExchangeError { code, message } => {
                match code {
                    60001 => pyo3::exceptions::PyRuntimeError::new_err(format!("Insufficient Funds ({}): {}", code, message)),
                    70001..=70014 => pyo3::exceptions::PyPermissionError::new_err(format!("Auth Error ({}): {}", code, message)),
                    _ => pyo3::exceptions::PyRuntimeError::new_err(format!("Bitbank Error ({}): {}", code, message)),
                }
            }
            _ => pyo3::exceptions::PyRuntimeError::new_err(err.to_string()),
        }
    }
}
