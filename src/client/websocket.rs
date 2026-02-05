use pyo3::prelude::*;
use tokio_tungstenite::{connect_async, tungstenite::Message};
use futures_util::{SinkExt, StreamExt};
use std::sync::Arc;
use tokio::sync::Mutex;
use url::Url;

#[pyclass]
#[derive(Clone)]
pub struct BitbankWebSocketClient {
    sender: Arc<Mutex<Option<tokio::sync::mpsc::UnboundedSender<String>>>>,
    callback: Arc<std::sync::Mutex<Option<PyObject>>>,
    disconnect_callback: Arc<std::sync::Mutex<Option<PyObject>>>,
}

#[pymethods]
impl BitbankWebSocketClient {
    #[new]
    pub fn new() -> Self {
        Self { 
            sender: Arc::new(Mutex::new(None)),
            callback: Arc::new(std::sync::Mutex::new(None)),
            disconnect_callback: Arc::new(std::sync::Mutex::new(None)),
        }
    }

    pub fn set_callback(&self, callback: PyObject) {
        let mut lock = self.callback.lock().unwrap();
        *lock = Some(callback);
    }

    pub fn set_disconnect_callback(&self, callback: PyObject) {
        let mut lock = self.disconnect_callback.lock().unwrap();
        *lock = Some(callback);
    }

    pub fn connect_py(&self, py: Python) -> PyResult<PyObject> {
        let sender_arc = self.sender.clone();
        let callback_arc = self.callback.clone();
        let disconnect_callback_arc = self.disconnect_callback.clone();
        
        let future = async move {
            let url = Url::parse("wss://stream.bitbank.cc/socket.io/?EIO=4&transport=websocket")
                .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;

            let (ws_stream, _) = connect_async(url).await
                .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Connect error: {}", e)))?;

            println!("Connected to Bitbank WebSocket");

            let (mut write, mut read) = ws_stream.split();

            // 1. Send Handshake "40"
            write.send(Message::Text("40".to_string())).await
                 .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

            let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel::<String>();
            
            {
                let mut lock = sender_arc.lock().await;
                *lock = Some(tx);
            }

            tokio::spawn(async move {
                loop {
                    tokio::select! {
                        msg = read.next() => {
                            match msg {
                                Some(Ok(Message::Text(txt))) => {
                                    if txt == "2" {
                                        let _ = write.send(Message::Text("3".to_string())).await;
                                    } else if txt.starts_with("42") {
                                        // Invoke callback
                                        let cb_opt = {
                                            let lock = callback_arc.lock().unwrap();
                                            lock.clone()
                                        };

                                        if let Some(cb) = cb_opt {
                                            let txt_clone = txt.clone();
                                            Python::with_gil(|py| {
                                                if let Err(e) = cb.call1(py, (txt_clone,)) {
                                                    e.print(py);
                                                }
                                            });
                                        }
                                    }
                                }
                                Some(Ok(Message::Close(_))) => break,
                                Some(Err(e)) => {
                                    println!("WS Error: {}", e);
                                    break;
                                }
                                None => break,
                                _ => {}
                            }
                        }
                        cmd = rx.recv() => {
                            if let Some(c) = cmd {
                                let msg = format!("42[\"join-room\", \"{}\"]", c);
                                if let Err(e) = write.send(Message::Text(msg)).await {
                                    println!("Failed to send subscribe: {}", e);
                                    break;
                                }
                            } else {
                                break; 
                            }
                        }
                    }
                }
                println!("WebSocket loop terminated");
                
                // Call disconnect callback if set
                let disconnect_cb_opt = {
                    let lock = disconnect_callback_arc.lock().unwrap();
                    lock.clone()
                };

                if let Some(cb) = disconnect_cb_opt {
                    Python::with_gil(|py| {
                        if let Err(e) = cb.call0(py) {
                            e.print(py);
                        }
                    });
                }
            });

            Ok("Connected")
        };
        
        pyo3_asyncio::tokio::future_into_py(py, future).map(|f| f.into())
    }
    
    pub fn subscribe_py(&self, py: Python, room_id: String) -> PyResult<PyObject> {
        let sender_arc = self.sender.clone();
        let future = async move {
             let lock = sender_arc.lock().await;
             if let Some(tx) = &*lock {
                 tx.send(room_id).map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
                 Ok("Subscribe command sent")
             } else {
                 Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("Client not connected"))
             }
        };
        
        pyo3_asyncio::tokio::future_into_py(py, future).map(|f| f.into())
    }

    pub fn disconnect_py(&self, py: Python) -> PyResult<PyObject> {
        let sender_arc = self.sender.clone();
        let callback_arc = self.callback.clone();
        
        let future = async move {
            {
                let mut lock = sender_arc.lock().await;
                *lock = None; // This will drop tx and close rx, terminating the loop
            }
            {
                let mut lock = callback_arc.lock().unwrap();
                *lock = None; // Clear callback to avoid GIL issues
            }
            Ok("Disconnected")
        };
        pyo3_asyncio::tokio::future_into_py(py, future).map(|f| f.into())
    }
}
