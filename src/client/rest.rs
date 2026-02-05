use reqwest::{Client, Method, StatusCode};
use serde::{de::DeserializeOwned, Serialize};
use hmac::{Hmac, Mac};
use sha2::Sha256;
use hex;
use crate::error::BitbankError;
use crate::model::{BitbankResponse, BitbankErrorResponse, market_data::{Ticker, Depth, PairsContainer}, order::{Order, Trades}, pubnub::PubNubConnectParams};
use std::time::{SystemTime, UNIX_EPOCH};
use pyo3::prelude::*;

type HmacSha256 = Hmac<Sha256>;

#[pyclass]
#[derive(Clone)]
pub struct BitbankRestClient {
    client: Client,
    api_key: String,
    api_secret: String,
    base_url_public: String,
    base_url_private: String,
}

#[pymethods]
impl BitbankRestClient {
    #[new]
    pub fn new(api_key: String, api_secret: String) -> Self {
        Self {
            client: Client::new(),
            api_key,
            api_secret,
            base_url_public: "https://public.bitbank.cc".to_string(),
            base_url_private: "https://api.bitbank.cc".to_string(),
        }
    }

    pub fn get_ticker_py(&self, py: Python, pair: String) -> PyResult<PyObject> {
        let client = self.clone();
        let pair = pair.clone();
        let future = async move {
            let res = client.get_ticker(&pair).await.map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
            let json = serde_json::to_string(&res).map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
            Ok(json)
        };
        pyo3_asyncio::tokio::future_into_py(py, future).map(|f| f.into())
    }

    pub fn create_order_py(
        &self,
        py: Python,
        pair: String,
        amount: String,
        side: String,
        order_type: String,
        price: Option<String>,
    ) -> PyResult<PyObject> {
        let client = self.clone();
        let future = async move {
            let price_ref = price.as_deref();
            let res = client.create_order(&pair, &amount, price_ref, &side, &order_type)
                .await
                .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
                
            let json = serde_json::to_string(&res).map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
            Ok(json)
        };
        pyo3_asyncio::tokio::future_into_py(py, future).map(|f| f.into())
    }

    pub fn cancel_order_py(&self, py: Python, pair: String, order_id: String) -> PyResult<PyObject> {
        let client = self.clone();
        let future = async move {
            let order_id_u64 = order_id.parse::<u64>().map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("Invalid order_id: {}", e)))?;
            
            let res = client.cancel_order(&pair, order_id_u64)
                .await
                .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
                
            let json = serde_json::to_string(&res).map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
            Ok(json)
        };
        pyo3_asyncio::tokio::future_into_py(py, future).map(|f| f.into())
    }

    pub fn get_order_py(&self, py: Python, pair: String, order_id: String) -> PyResult<PyObject> {
        let client = self.clone();
        let future = async move {
            let order_id_u64 = order_id.parse::<u64>().map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("Invalid order_id: {}", e)))?;
            
            let res = client.get_order(&pair, order_id_u64)
                .await
                .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
                
            let json = serde_json::to_string(&res).map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
            Ok(json)
        };
        pyo3_asyncio::tokio::future_into_py(py, future).map(|f| f.into())
    }

    pub fn get_trade_history_py(&self, py: Python, pair: String, order_id: Option<String>) -> PyResult<PyObject> {
        let client = self.clone();
        let future = async move {
            let order_id_u64 = match order_id {
                Some(id) => Some(id.parse::<u64>().map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("Invalid order_id: {}", e)))?),
                None => None,
            };
            
            let res = client.get_trade_history(&pair, order_id_u64)
                .await
                .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
                
            let json = serde_json::to_string(&res).map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
            Ok(json)
        };
        pyo3_asyncio::tokio::future_into_py(py, future).map(|f| f.into())
    }

    pub fn get_pairs_py(&self, py: Python) -> PyResult<PyObject> {
        let client = self.clone();
        let future = async move {
            let res = client.get_pairs()
                .await
                .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
                
            let json = serde_json::to_string(&res).map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
            Ok(json)
        };
        pyo3_asyncio::tokio::future_into_py(py, future).map(|f| f.into())
    }

    pub fn get_pubnub_auth_py(&self, py: Python) -> PyResult<PyObject> {
        let client = self.clone();
        let future = async move {
             let endpoint = "/v1/user/subscribe";
             let res: PubNubConnectParams = client.request(Method::GET, endpoint, None, None, true)
                .await
                .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

             let json = serde_json::to_string(&res).map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
             Ok(json)
        };
        pyo3_asyncio::tokio::future_into_py(py, future).map(|f| f.into())
    }
}

// Internal methods definitions... (same as before)
impl BitbankRestClient {
    // ... (rest of the implementation omitted for brevity but logic must persist)
    // To ensure I don't delete existing internal methods, I must include them.
    // I can assume previous view_file content.
    
    fn generate_signature(&self, text: &str) -> String {
        let mut mac = HmacSha256::new_from_slice(self.api_secret.as_bytes())
            .expect("HMAC can take key of any size");
        mac.update(text.as_bytes());
        hex::encode(mac.finalize().into_bytes())
    }

    async fn request<T: DeserializeOwned>(
        &self,
        method: Method,
        endpoint: &str, 
        query: Option<&[(&str, &str)]>,
        body: Option<&str>,
        private: bool,
    ) -> Result<T, BitbankError> {
        let url = if private {
            format!("{}{}", self.base_url_private, endpoint)
        } else {
            format!("{}{}", self.base_url_public, endpoint)
        };

        let mut builder = self.client.request(method.clone(), &url);

        if private {
            let timestamp = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_millis()
                .to_string();
            
            let path_for_sign = if let Some(q) = query {
                 let qs = serde_urlencoded::to_string(q).unwrap();
                 format!("{}?{}", endpoint, qs)
            } else {
                endpoint.to_string()
            };
            
            let text_to_sign = if method == Method::GET {
                format!("{}{}", timestamp, path_for_sign)
            } else {
                 let b = body.unwrap_or("");
                 format!("{}{}", timestamp, b)
            };

            let signature = self.generate_signature(&text_to_sign);

            builder = builder
                .header("ACCESS-KEY", &self.api_key)
                .header("ACCESS-NONCE", &timestamp)
                .header("ACCESS-SIGNATURE", signature);
        }

        if let Some(q) = query {
            builder = builder.query(q);
        }
        
        if let Some(b) = body {
             builder = builder
                .header("Content-Type", "application/json")
                .body(b.to_string());
        }

        let response = builder.send().await?;
        let status = response.status();
        let text = response.text().await?;

        if !status.is_success() {
            if let Ok(err_res) = serde_json::from_str::<BitbankErrorResponse>(&text) {
                 return Err(BitbankError::ExchangeError { 
                     code: err_res.data.code, 
                     message: err_res.data.message.unwrap_or_default() 
                 });
            }
            return Err(BitbankError::Unknown(format!("Status: {}, Body: {}", status, text)));
        }

        let val: serde_json::Value = serde_json::from_str(&text)?;
        let success = val.get("success").and_then(|v| v.as_i64()).unwrap_or(0);
        
        if success == 1 {
            if let Some(data) = val.get("data") {
                let res: T = serde_json::from_value(data.clone())?;
                Ok(res)
            } else {
                Err(BitbankError::Unknown(format!("Success=1 but no data. Body: {}", text)))
            }
        } else {
             // Handle error info in data
             if let Some(data) = val.get("data") {
                 let code = data.get("code").and_then(|v| v.as_i64()).unwrap_or(0) as i32;
                 let message = data.get("message").and_then(|v| v.as_str()).unwrap_or("Unknown error").to_string();
                 Err(BitbankError::ExchangeError { code, message })
             } else {
                 Err(BitbankError::Unknown(format!("Success=0 and no data. Body: {}", text)))
             }
        }
    }

    pub async fn get_ticker(&self, pair: &str) -> Result<Ticker, BitbankError> {
        let endpoint = format!("/{}/ticker", pair);
        self.request(Method::GET, &endpoint, None, None, false).await
    }

    pub async fn get_pairs(&self) -> Result<PairsContainer, BitbankError> {
        let endpoint = "/v1/spot/pairs";
        self.request(Method::GET, endpoint, None, None, false).await
    }

    // Keep all other methods as previously defined
    pub async fn get_depth(&self, pair: &str) -> Result<Depth, BitbankError> {
        let endpoint = format!("/{}/depth", pair);
        self.request(Method::GET, &endpoint, None, None, false).await
    }
    
    pub async fn create_order(&self, pair: &str, amount: &str, price: Option<&str>, side: &str, order_type: &str) -> Result<Order, BitbankError> {
        let endpoint = "/v1/user/spot/order";
        let mut body_json = serde_json::json!({
            "pair": pair,
            "amount": amount,
            "side": side,
            "type": order_type
        });
        
        if let Some(p) = price {
             body_json["price"] = serde_json::json!(p);
        }
        
        // Bitbank requires stringified number for amount/price usually, or simple numbers?
        // documentation says string.
        
        let body_str = body_json.to_string();
        
        self.request(Method::POST, endpoint, None, Some(&body_str), true).await
    }

    pub async fn cancel_order(&self, pair: &str, order_id: u64) -> Result<Order, BitbankError> {
        let endpoint = "/v1/user/spot/cancel_order";
        let body_json = serde_json::json!({
            "pair": pair,
            "order_id": order_id
        });
        
        let body_str = body_json.to_string();
        
        self.request(Method::POST, endpoint, None, Some(&body_str), true).await
    }

    pub async fn get_order(&self, pair: &str, order_id: u64) -> Result<Order, BitbankError> {
        let endpoint = "/v1/user/spot/order";
        let query = [
            ("pair", pair),
            ("order_id", &order_id.to_string()),
        ];
        
        self.request(Method::GET, endpoint, Some(&query), None, true).await
    }

    pub async fn get_trade_history(&self, pair: &str, order_id: Option<u64>) -> Result<Trades, BitbankError> {
        let endpoint = "/v1/user/spot/trade_history";
        let mut query = vec![("pair", pair.to_string())];
        if let Some(id) = order_id {
            query.push(("order_id", id.to_string()));
        }
        
        // Convert Vec<(String, String)> to &[(&str, &str)]
        let query_refs: Vec<(&str, &str)> = query.iter().map(|(k, v)| (k.as_ref(), v.as_ref())).collect();

        self.request::<Trades>(Method::GET, endpoint, Some(&query_refs), None, true).await
    }
}
