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

    pub fn get_assets_py(&self, py: Python) -> PyResult<PyObject> {
        self.rest_client.get_assets_py(py)
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
            
            // 2. Start Processing Loop (Background)
             let orders_arc_loop = orders_arc.clone();
             let order_cb_arc_loop = order_cb_arc.clone();
              tokio::spawn(async move {
                  // eprintln!("RB: Starting internal order message loop");
                  while let Some(msg_json) = rx.recv().await {
                      // eprintln!("RB: Received message from PubNub channel: {}", msg_json);
                       // Try parsing to update internal state
                       match serde_json::from_str::<crate::model::pubnub::PubNubMessage>(&msg_json) {
                           Ok(msg) => {
                               let method = &msg.data.method;
                               let event_type = match method.as_str() {
                                   "spot_order_new" | "spot_order" => "OrderUpdate",
                                   "spot_trade" => "TradeUpdate",
                                   "asset_update" => "AssetUpdate",
                                   _ => method.as_str(),
                               };

                               for param in msg.data.params {
                                   // For OrderUpdate, try to update internal cache if it matches Order structure
                                   if event_type == "OrderUpdate" {
                                       if let Ok(order_data) = serde_json::from_value::<crate::model::order::Order>(param.clone()) {
                                            let mut orders = orders_arc_loop.write().await;
                                            orders.insert(order_data.order_id, order_data);
                                       }
                                   }

                                   let cb_opt = {
                                      let lock = order_cb_arc.lock().unwrap();
                                      lock.clone()
                                   };
                                   
                                   if let Some(cb) = cb_opt {
                                       let param_json = param.to_string();
                                       Python::with_gil(|py| {
                                           let _ = cb.call1(py, (event_type, param_json));
                                       });
                                   }
                               }
                           },
                           Err(e) => {
                               eprintln!("RB: Failed to parse PubNub message internally: {}. JSON: {}", e, msg_json);
                               // Fallback: Notify Python with raw message if internal parse fails
                               let cb_opt = {
                                  let lock = order_cb_arc.lock().unwrap();
                                  lock.clone()
                               };
                               if let Some(cb) = cb_opt {
                                   Python::with_gil(|py| {
                                       let _ = cb.call1(py, ("Unknown", msg_json));
                                   });
                               }
                           }
                       }
                  }
                  eprintln!("RB: Internal Order Loop Terminated");
              });

             // 3. Connect PubNub (Background loop with token refresh)
         let pc = pubnub_client.clone();
         let rc = rest_client.clone();
         let sub_key_loop = sub_key.clone();
         
         tokio::spawn(async move {
             loop {
                 // 1. Fetch Fresh Auth (Dynamic Token)
                 match rc.get_pubnub_auth().await {
                     Ok(auth_params) => {
                         let channel = auth_params.pubnub_channel.clone();
                         let token = auth_params.pubnub_token.clone();
                         
                         // 2. Connect. Returns Ok(()) on clean stop, Err on Auth error
                         if let Err(e) = pc.connect(sub_key_loop.clone(), channel, token).await {
                             eprintln!("RB: PubNub connection triggered refresh: {}. Re-fetching token in 5s...", e);
                             tokio::time::sleep(tokio::time::Duration::from_secs(5)).await;
                         } else {
                             // Normal stop signaled by client
                             break;
                         }
                     }
                     Err(e) => {
                         eprintln!("RB: Failed to fetch PubNub Auth for refresh: {}. Retrying in 10s...", e);
                         tokio::time::sleep(tokio::time::Duration::from_secs(10)).await;
                     }
                 }
             }
             eprintln!("RB: PubNub background loop terminated");
         });
         
         Ok("Connected")
    };
    pyo3_asyncio::tokio::future_into_py(py, future).map(|f| f.into())
}

    // Legacy manual connect if needed, or remove
    pub fn connect_pubnub_manual(&self, py: Python, sub_key: String, channel: String, auth_key: String) -> PyResult<PyObject> {
        self.pubnub_client.connect_py(py, sub_key, channel, auth_key)
    }
}
