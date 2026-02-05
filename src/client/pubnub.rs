use pyo3::prelude::*;
use reqwest::Client;
use std::sync::Arc;
use tokio::sync::Mutex;
use serde_json::Value;

#[pyclass]
#[derive(Clone)]
pub struct PubNubClient {
    client: Client,
    callback: Arc<std::sync::Mutex<Option<PyObject>>>,
    // Flag to stop polling
    running: Arc<Mutex<bool>>,
}

#[pymethods]
impl PubNubClient {
    #[new]
    pub fn new() -> Self {
        Self {
            client: Client::new(),
            callback: Arc::new(std::sync::Mutex::new(None)),
            running: Arc::new(Mutex::new(false)),
        }
    }

    pub fn set_callback(&self, callback: PyObject) {
        let mut lock = self.callback.lock().unwrap();
        *lock = Some(callback);
    }

    pub fn connect_py(&self, py: Python, sub_key: String, channel: String) -> PyResult<PyObject> {
        let client = self.client.clone();
        let callback_arc = self.callback.clone();
        let running_arc = self.running.clone();

        let future = async move {
            {
                let mut run = running_arc.lock().await;
                *run = true;
            }

            let mut timetoken = "0".to_string();
            // https://ps.pndsn.com/v2/subscribe/{sub-key}/{channel}/0?tt={timetoken}
            
            println!("PubNub Polling Started for channel: {}", channel);

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
                            if let Ok(txt) = resp.text().await {
                                // PubNub returns: {"t":{...}, "m":[...]}
                                // Check for new timetoken in "t" -> "t" or root
                                // Usually v2 response: {"t":{"t":"16...","r":...}, "m":[...]}
                                
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
                                                // Invoke callback
                                                let cb_opt = {
                                                    let lock = callback_arc.lock().unwrap();
                                                    lock.clone()
                                                };
                                                
                                                if let Some(cb) = cb_opt {
                                                    let msg_json = msg.to_string();
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
                            println!("PubNub Request Failed: status={}", resp.status());
                            tokio::time::sleep(tokio::time::Duration::from_secs(5)).await;
                        }
                    },
                    Err(e) => {
                        println!("PubNub Connection Error: {}", e);
                        tokio::time::sleep(tokio::time::Duration::from_secs(5)).await;
                    }
                }
            }
            println!("PubNub Polling Stopped");
            Ok("Stopped")
        };
        
        pyo3_asyncio::tokio::future_into_py(py, future).map(|f| f.into())
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
