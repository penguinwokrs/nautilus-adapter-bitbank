use pyo3::prelude::*;
use tokio_tungstenite::{connect_async, tungstenite::Message};
use futures_util::{SinkExt, StreamExt};
use std::sync::Arc;
use tokio::sync::Mutex;
use url::Url;
use serde_json::Value;
use std::collections::HashSet;
use tokio::time::{sleep, Duration};

#[pyclass]
#[derive(Clone)]
pub struct BitbankDataClient {
    sender: Arc<Mutex<Option<tokio::sync::mpsc::UnboundedSender<String>>>>,
    data_callback: Arc<std::sync::Mutex<Option<PyObject>>>, 
    subscriptions: Arc<Mutex<HashSet<String>>>,
    books: Arc<tokio::sync::RwLock<std::collections::HashMap<String, crate::model::orderbook::OrderBook>>>,
}

#[pymethods]
impl BitbankDataClient {
    #[new]
    pub fn new() -> Self {
        Self { 
            sender: Arc::new(Mutex::new(None)),
            data_callback: Arc::new(std::sync::Mutex::new(None)),
            subscriptions: Arc::new(Mutex::new(HashSet::new())),
            books: Arc::new(tokio::sync::RwLock::new(std::collections::HashMap::new())),
        }
    }

    pub fn set_data_callback(&self, callback: PyObject) {
        let mut lock = self.data_callback.lock().unwrap();
        *lock = Some(callback);
    }
    pub fn connect(&self, py: Python) -> PyResult<PyObject> {
        let sender_arc = self.sender.clone();
        let data_cb_arc = self.data_callback.clone();
        let subs_arc = self.subscriptions.clone();
        let books_arc = self.books.clone();
        
        let future = async move {
            let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel::<String>();
            {
                let mut lock = sender_arc.lock().await;
                *lock = Some(tx);
            }

            tokio::spawn(async move {
                let mut backoff_sec = 1;
                let max_backoff = 64;

                loop {
                    let url = Url::parse("wss://stream.bitbank.cc/socket.io/?EIO=4&transport=websocket").unwrap();
                    
                    match connect_async(url).await {
                        Ok((ws_stream, _)) => {
                            println!("RB: Connected to Bitbank WebSocket");
                            backoff_sec = 1; // reset backoff
                            
                            let (mut write, mut read) = ws_stream.split();

                            // 1. Send Handshake "40"
                            if let Err(e) = write.send(Message::Text("40".to_string())).await {
                                 println!("Handshake error: {}", e);
                                 continue; 
                            }

                            // 2. Re-join previous rooms
                            {
                                let subs = subs_arc.lock().await;
                                for room in subs.iter() {
                                    let msg = format!("42[\"join-room\", \"{}\"]", room);
                                    let _ = write.send(Message::Text(msg)).await;
                                }
                            }

                            loop {
                                tokio::select! {
                                    msg = read.next() => {
                                        match msg {
                                            Some(Ok(Message::Text(txt))) => {
                                                if txt == "2" {
                                                    let _ = write.send(Message::Text("3".to_string())).await;
                                                } else if txt.starts_with("42") {
                                                    if txt.len() > 2 {
                                                        let json_str = &txt[2..];
                                                        if let Ok(val) = serde_json::from_str::<Value>(json_str) {
                                                            if let Some(arr) = val.as_array() {
                                                                if arr.len() >= 2 && arr[0] == "message" {
                                                                    if let Some(content) = arr[1].as_object() {
                                                                        if let (Some(room_name_val), Some(msg_data)) = (content.get("room_name"), content.get("message")) {
                                                                            if let Some(room_name) = room_name_val.as_str() {
                                                                                if let Some(inner_data) = msg_data.get("data") {
                                                                                    let mut parsed_obj: Option<PyObject> = Python::with_gil(|py| {
                                                                                        if room_name.starts_with("ticker_") {
                                                                                             serde_json::from_value::<crate::model::market_data::Ticker>(inner_data.clone())
                                                                                                 .ok().map(|v| v.into_py(py))
                                                                                        } else if room_name.starts_with("transactions_") {
                                                                                             serde_json::from_value::<crate::model::market_data::Transactions>(inner_data.clone())
                                                                                                 .ok().map(|v| v.into_py(py))
                                                                                        } else {
                                                                                            None
                                                                                        }
                                                                                    });

                                                                                    // Handle OrderBook processing in Rust
                                                                                    if room_name.starts_with("depth_whole_") || room_name.starts_with("depth_diff_") {
                                                                                        let pair = if room_name.starts_with("depth_whole_") {
                                                                                            &room_name["depth_whole_".len()..]
                                                                                        } else {
                                                                                            &room_name["depth_diff_".len()..]
                                                                                        };

                                                                                        let mut books = books_arc.write().await;
                                                                                        let book = books.entry(pair.to_string()).or_insert_with(|| crate::model::orderbook::OrderBook::new(pair.to_string()));
                                                                                        
                                                                                        if room_name.starts_with("depth_whole_") {
                                                                                            if let Ok(depth) = serde_json::from_value::<crate::model::market_data::Depth>(inner_data.clone()) {
                                                                                                book.apply_whole(depth);
                                                                                                parsed_obj = Some(Python::with_gil(|py| book.clone().into_py(py)));
                                                                                            }
                                                                                        } else {
                                                                                             if let Ok(diff) = serde_json::from_value::<crate::model::market_data::DepthDiff>(inner_data.clone()) {
                                                                                                book.apply_diff(diff);
                                                                                                parsed_obj = Some(Python::with_gil(|py| book.clone().into_py(py)));
                                                                                            }
                                                                                        }
                                                                                    }

                                                                                    if let Some(valid_obj) = parsed_obj {
                                                                                         let cb_opt = {
                                                                                             let lock = data_cb_arc.lock().unwrap();
                                                                                             lock.clone()
                                                                                         };
                                                                                         if let Some(cb) = cb_opt {
                                                                                             let rn = room_name.to_string();
                                                                                             Python::with_gil(|py| {
                                                                                                 let _ = cb.call1(py, (rn, valid_obj));
                                                                                             });
                                                                                         }
                                                                                    }
                                                                                }
                                                                            }
                                                                        }
                                                                    }
                                                                }
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                            Some(Ok(Message::Close(_))) => {
                                                println!("RB: WebSocket closed by server");
                                                break;
                                            }
                                            Some(Err(e)) => {
                                                println!("WS Error: {}", e);
                                                break;
                                            }
                                            None => break,
                                            _ => {}
                                        }
                                    }
                                    cmd = rx.recv() => {
                                        if let Some(room_id) = cmd {
                                            // Store it for reconnection
                                            {
                                                let mut subs = subs_arc.lock().await;
                                                subs.insert(room_id.clone());
                                            }
                                            let msg = format!("42[\"join-room\", \"{}\"]", room_id);
                                            if let Err(e) = write.send(Message::Text(msg)).await {
                                                println!("Failed to send subscribe: {}", e);
                                                break;
                                            }
                                        } else {
                                            // Sender dropped
                                            return; 
                                        }
                                    }
                                }
                            }
                        }
                        Err(e) => {
                            println!("RB: Connection failed: {}. Retrying in {}s...", e, backoff_sec);
                        }
                    }

                    sleep(Duration::from_secs(backoff_sec)).await;
                    backoff_sec = (backoff_sec * 2).min(max_backoff);
                }
            });

            Ok("Connected")
        };
        
        pyo3_asyncio::tokio::future_into_py(py, future).map(|f| f.into())
    }
    
    pub fn subscribe(&self, py: Python, rooms: Vec<String>) -> PyResult<PyObject> {
        let sender_arc = self.sender.clone();
        let future = async move {
             let lock = sender_arc.lock().await;
             if let Some(tx) = &*lock {
                 for room_id in rooms {
                     tx.send(room_id).map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
                 }
                 Ok("Subscribe commands sent")
             } else {
                 Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("Client not connected"))
             }
        };
        
        pyo3_asyncio::tokio::future_into_py(py, future).map(|f| f.into())
    }

    pub fn disconnect(&self, py: Python) -> PyResult<PyObject> {
        let sender_arc = self.sender.clone();
        let future = async move {
            let mut lock = sender_arc.lock().await;
            *lock = None; 
            Ok("Disconnected")
        };
        pyo3_asyncio::tokio::future_into_py(py, future).map(|f| f.into())
    }
}
