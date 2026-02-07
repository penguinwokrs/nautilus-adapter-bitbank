use pyo3::prelude::*;
use reqwest::Client;
use std::sync::Arc;
use tokio::sync::{Mutex, mpsc};
use serde_json::Value;

use std::time::Duration;

#[pyclass]
#[derive(Clone)]
pub struct PubNubClient {
    client: Client,
    // Callback to Python: fn(message_json: str)
    pub callback: Arc<std::sync::Mutex<Option<PyObject>>>,
    // Flag to stop polling
    running: Arc<Mutex<bool>>,
    internal_sender: Arc<std::sync::Mutex<Option<mpsc::UnboundedSender<String>>>>,
    pub uuid: String,
}

#[pymethods]
impl PubNubClient {
    #[new]
    pub fn new() -> Self {
        let uuid = chrono::Utc::now().timestamp_nanos_opt().unwrap_or(0).to_string();
        eprintln!("PubNubClient: Creating new instance with UUID={}", uuid);
        Self {
            client: Client::builder()
                .timeout(Duration::from_secs(310))
                .build()
                .unwrap_or_else(|_| Client::new()),
            callback: Arc::new(std::sync::Mutex::new(None)),
            running: Arc::new(Mutex::new(false)),
            internal_sender: Arc::new(std::sync::Mutex::new(None)),
            uuid,
        }
    }

    pub fn set_callback(&self, callback: PyObject) {
        let mut lock = self.callback.lock().unwrap();
        *lock = Some(callback);
    }

    pub fn connect_py(&self, py: Python, sub_key: String, channel: String, auth_key: String) -> PyResult<PyObject> {
        let client = self.clone();
        let future = async move {
            client.connect(sub_key, channel, auth_key).await.map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e))?;
            Ok("Stopped")
        };
        pyo3_asyncio::tokio::future_into_py(py, future).map(|f| f.into())
    }

}

impl PubNubClient {
    pub fn set_internal_sender(&self, sender: mpsc::UnboundedSender<String>) {
        let mut lock = self.internal_sender.lock().unwrap();
        *lock = Some(sender);
    }

    pub async fn connect(&self, sub_key: String, channel: String, auth_key: String) -> Result<(), String> {
        let mut timetoken = "0".to_string();
        let running_arc = self.running.clone();
        let callback_arc = self.callback.clone();
        let sender_arc = self.internal_sender.clone();
        let client = &self.client;
        
        // Bitbank PAM expects the channel name as the UUID in some cases
        let uuid = channel.clone(); 
        
        {
            let mut run = running_arc.lock().await;
            *run = true;
        }

        // eprintln!("PubNub Polling Started for channel: {}, auth={}", channel, auth_key);

        let mut backoff_sec = 1;
        let max_backoff = 64;

        loop {
            // Check if we should stop
            {
                let run = running_arc.lock().await;
                if !*run {
                    break;
                }
            }
            let url = format!(
                "https://ps.pndsn.com/v2/subscribe/{}/{}/0",
                sub_key, channel
            );

            let query = [
                ("tt", timetoken.as_str()),
                ("auth", auth_key.as_str()),
                ("uuid", uuid.as_str())
            ];

            // eprintln!("PubNub: Polling URL={} with tt={}, uuid={}", url, timetoken, uuid);

            match client.get(&url).query(&query).send().await {
                Ok(resp) => {
                    let status = resp.status();
                    if status.is_success() {
                        // eprintln!("PubNub: Poll OK. Time: {}", chrono::Utc::now()); 
                        backoff_sec = 1; // reset backoff
                        if let Ok(txt) = resp.text().await {
                            match serde_json::from_str::<Value>(&txt) {
                                Ok(val) => {
                                    // Extract new timetoken
                                    if let Some(t_obj) = val.get("t") {
                                            if let Some(tt) = t_obj.get("t") {
                                                if let Some(tt_str) = tt.as_str() {
                                                    timetoken = tt_str.to_string();
                                                }
                                            }
                                    }

                                    // Extract messages
                                    if let Some(msgs) = val.get("m") {
                                        if let Some(arr) = msgs.as_array() {
                                            for msg in arr {
                                                let msg_json = msg.to_string();
                                                // println!("DEBUG: PubNub Message Received: {}", msg_json);
                                                
                                                // 1. Send to Internal Channel (Rust)
                                                {
                                                    let lock = sender_arc.lock().unwrap();
                                                    if let Some(tx) = &*lock {
                                                        let _ = tx.send(msg_json.clone());
                                                    }
                                                }

                                                // 2. Invoke Python callback
                                                let cb_opt = {
                                                    let lock = callback_arc.lock().unwrap();
                                                    lock.clone()
                                                };
                                                
                                                if let Some(cb) = cb_opt {
                                                    Python::with_gil(|py| {
                                                        if let Err(e) = cb.call1(py, (msg_json,)) {
                                                            e.print(py);
                                                        }
                                                    });
                                                }
                                            }
                                        }
                                    }
                                }
                                Err(e) => {
                                    eprintln!("PubNub JSON Parse Error: {}. Text: {}", e, txt);
                                }
                            }
                        }
                    } else {
                        let status = resp.status();
                        let text = resp.text().await.unwrap_or_default();
                        eprintln!("PubNub Request Failed: status={}, body={}. Retrying in {}s...", status, text, backoff_sec);
                        
                        // If token expired or auth failed, return to refresh
                        if status == reqwest::StatusCode::FORBIDDEN || status == reqwest::StatusCode::UNAUTHORIZED {
                            return Err(format!("Auth failed or expired: status={}", status));
                        }
                        
                        tokio::time::sleep(tokio::time::Duration::from_secs(backoff_sec)).await;
                        backoff_sec = (backoff_sec * 2).min(max_backoff);
                    }
                },
                Err(e) => {
                    eprintln!("PubNub Connection Error: {}. Retrying in {}s...", e, backoff_sec);
                    tokio::time::sleep(tokio::time::Duration::from_secs(backoff_sec)).await;
                    backoff_sec = (backoff_sec * 2).min(max_backoff);
                }
            }
        }
        println!("PubNub Polling Stopped");
        Ok(())
    }


    pub fn stop_py(&self, py: Python) -> PyResult<PyObject> {
        let running_arc = self.running.clone();
        let future = async move {
            let mut run = running_arc.lock().await;
            *run = false;
            Ok("Stopping")
        };
        pyo3_asyncio::tokio::future_into_py(py, future).map(|f| f.into())
    }
}
