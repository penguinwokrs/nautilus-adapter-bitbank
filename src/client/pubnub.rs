use pyo3::prelude::*;
use reqwest::Client;
use std::sync::Arc;
use tokio::sync::{Mutex, mpsc};
use serde_json::Value;

#[pyclass]
#[derive(Clone)]
pub struct PubNubClient {
    client: Client,
    pub callback: Arc<std::sync::Mutex<Option<PyObject>>>,
    // Flag to stop polling
    running: Arc<Mutex<bool>>,
    internal_sender: Arc<std::sync::Mutex<Option<mpsc::UnboundedSender<String>>>>,
}

#[pymethods]
impl PubNubClient {
    #[new]
    pub fn new() -> Self {
        Self {
            client: Client::new(),
            callback: Arc::new(std::sync::Mutex::new(None)),
            running: Arc::new(Mutex::new(false)),
            internal_sender: Arc::new(std::sync::Mutex::new(None)),
        }
    }

    pub fn set_callback(&self, callback: PyObject) {
        let mut lock = self.callback.lock().unwrap();
        *lock = Some(callback);
    }

    pub fn connect_py(&self, py: Python, sub_key: String, channel: String) -> PyResult<PyObject> {
        let client = self.clone();
        let future = async move {
            client.connect(sub_key, channel).await.map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e))?;
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

    pub async fn connect(&self, sub_key: String, channel: String) -> Result<(), String> {
        let client = self.client.clone();
        let callback_arc = self.callback.clone();
        let running_arc = self.running.clone();
        let sender_arc = self.internal_sender.clone();

        {
            let mut run = running_arc.lock().await;
            *run = true;
        }

        let mut timetoken = "0".to_string();
        println!("PubNub Polling Started for channel: {}", channel);

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
                "https://ps.pndsn.com/v2/subscribe/{}/{}/0?tt={}", 
                sub_key, channel, timetoken
            );

            match client.get(&url).send().await {
                Ok(resp) => {
                    if resp.status().is_success() {
                        backoff_sec = 1; // reset backoff
                        if let Ok(txt) = resp.text().await {
                            if let Ok(val) = serde_json::from_str::<Value>(&txt) {
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
                        }
                    } else {
                        println!("PubNub Request Failed: status={}. Retrying in {}s...", resp.status(), backoff_sec);
                        tokio::time::sleep(tokio::time::Duration::from_secs(backoff_sec)).await;
                        backoff_sec = (backoff_sec * 2).min(max_backoff);
                    }
                },
                Err(e) => {
                    println!("PubNub Connection Error: {}. Retrying in {}s...", e, backoff_sec);
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
