use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::{RwLock, mpsc};
use crate::model::order::Order;
use pyo3::prelude::*;
use crate::client::rest::BitbankRestClient;
use crate::client::pubnub::PubNubClient;

#[pyclass]
pub struct BitbankExecutionClient {
    rest_client: BitbankRestClient,
    pubnub_client: PubNubClient,
    pubnub_subscribe_key: String,
    // Order State
    orders: Arc<RwLock<HashMap<u64, Order>>>,
    client_oid_map: Arc<RwLock<HashMap<String, u64>>>,
    // Callback for order updates: (event_type, data_json)
    order_callback: Arc<std::sync::Mutex<Option<PyObject>>>,
}

#[pymethods]
impl BitbankExecutionClient {
    #[new]
    pub fn new(api_key: String, api_secret: String, pubnub_subscribe_key: String, timeout_ms: u64, proxy_url: Option<String>) -> Self {
        Self {
            rest_client: BitbankRestClient::new(api_key, api_secret, timeout_ms, proxy_url),
            pubnub_client: PubNubClient::new(),
            pubnub_subscribe_key,
            orders: Arc::new(RwLock::new(HashMap::new())),
            client_oid_map: Arc::new(RwLock::new(HashMap::new())),
            order_callback: Arc::new(std::sync::Mutex::new(None)),
        }
    }

    pub fn set_order_callback(&self, callback: PyObject) {
        let mut lock = self.order_callback.lock().unwrap();
        *lock = Some(callback);
    }

    // Proxy methods to internal clients or implement logic here
    
    pub fn get_order(&self, py: Python, pair: String, order_id: String) -> PyResult<PyObject> {
        self.rest_client.get_order_py(py, pair, order_id)
    }
    
    pub fn get_trade_history(&self, py: Python, pair: String, order_id: Option<String>) -> PyResult<PyObject> {
        self.rest_client.get_trade_history_py(py, pair, order_id)
    }

    pub fn submit_order(&self, py: Python, pair: String, amount: String, side: String, order_type: String, client_order_id: String, price: Option<String>) -> PyResult<PyObject> {
        let rest_client = self.rest_client.clone();
        let orders_arc = self.orders.clone();
        let client_oid_map_arc = self.client_oid_map.clone();
        
        let future = async move {
             let price_ref = price.as_deref();
             // 1. Submit Order
             let order_res = rest_client.create_order(&pair, &amount, price_ref, &side, &order_type)
                .await
                .map_err(PyErr::from)?;
             
             // 2. Track it
             let oid = order_res.order_id;
             {
                 let mut orders = orders_arc.write().await;
                 orders.insert(oid, order_res); // Assuming Order is Clone or we just move it? create_order returns struct.
             }
             {
                 let mut map = client_oid_map_arc.write().await;
                 map.insert(client_order_id, oid);
             }

             // Return the Order object (serialized)
             let orders_read = orders_arc.read().await;
             let stored_order = orders_read.get(&oid).unwrap(); // Safe as we just inserted
             let json = serde_json::to_string(stored_order).map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
             Ok(json)
        };
        pyo3_asyncio::tokio::future_into_py(py, future).map(|f| f.into())
    }
    
    pub fn cancel_order(&self, py: Python, pair: String, order_id: String) -> PyResult<PyObject> {
        self.rest_client.cancel_order_py(py, pair, order_id)
    }

    pub fn set_pubnub_callback(&self, callback: PyObject) {
         self.pubnub_client.set_callback(callback);
    }

    pub fn connect(&self, py: Python) -> PyResult<PyObject> {
        let rest_client = self.rest_client.clone();
        let pubnub_client = self.pubnub_client.clone();
        let order_cb_arc = self.order_callback.clone();
        let orders_arc = self.orders.clone();
        
        let sub_key = self.pubnub_subscribe_key.clone();

        // Channel for internal messages
        let (tx, mut rx) = mpsc::unbounded_channel::<String>();
        pubnub_client.set_internal_sender(tx);

        let future = async move {
             // 1. Get Auth
             let auth_params = rest_client.get_pubnub_auth().await
                 .map_err(PyErr::from)?;
             
             // 2. Start Processing Loop (Background)
             let orders_arc_loop = orders_arc.clone();
             tokio::spawn(async move {
                 while let Some(msg_json) = rx.recv().await {
                     let mut event_type = "OrderUpdate";
                     
                     // Try parsing to update internal state
                     if let Ok(msg) = serde_json::from_str::<crate::model::pubnub::PubNubMessage>(&msg_json) {
                         let mut orders = orders_arc_loop.write().await;
                         orders.insert(msg.data.order_id, msg.data.clone());
                         event_type = "OrderUpdate"; // can be more specific if needed
                     }
                     
                     let cb_opt = {
                        let lock = order_cb_arc.lock().unwrap();
                        lock.clone()
                     };
                     
                     if let Some(cb) = cb_opt {
                         Python::with_gil(|py| {
                             let _ = cb.call1(py, (event_type, msg_json));
                         });
                     }
                 }
                 println!("RB: Order Loop Terminated");
             });

             // 3. Connect PubNub (This blocks until stopped, need to spawn it too? No, pubnub.connect already loops)
             // Wait, PubNubClient::connect LOOPS.
             // If I await it here, this future will never complete "Connected".
             // The previous logic awaited it?
             // No, previously I just ran it.
             // Wait, if `pubnub_client.connect` loops, I must SPAWN it.
             let pc = pubnub_client.clone();
             let channel = auth_params.pubnub_channel.clone();
             
             tokio::spawn(async move {
                 let _ = pc.connect(sub_key, channel).await;
             });
             
             Ok("Connected")
        };
        pyo3_asyncio::tokio::future_into_py(py, future).map(|f| f.into())
    }

    // Legacy manual connect if needed, or remove
    pub fn connect_pubnub_manual(&self, py: Python, sub_key: String, channel: String) -> PyResult<PyObject> {
        self.pubnub_client.connect_py(py, sub_key, channel)
    }
}
