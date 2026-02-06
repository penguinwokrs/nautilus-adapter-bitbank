use std::collections::BTreeMap;
use pyo3::prelude::*;
use crate::model::market_data::{Depth, DepthDiff};

#[pyclass]
#[derive(Clone)]
pub struct OrderBook {
    #[pyo3(get)]
    pub pair: String,
    pub asks: BTreeMap<String, String>, // Price -> Amount
    pub bids: BTreeMap<String, String>, // Price -> Amount
    #[pyo3(get)]
    pub sequence: u64,
    #[pyo3(get)]
    pub timestamp: u64,
}

#[pymethods]
impl OrderBook {
    #[new]
    pub fn new(pair: String) -> Self {
        Self {
            pair,
            asks: BTreeMap::new(),
            bids: BTreeMap::new(),
            sequence: 0,
            timestamp: 0,
        }
    }

    pub fn apply_whole(&mut self, depth: Depth) {
        self.asks.clear();
        for level in depth.asks {
            if level.len() >= 2 {
                self.asks.insert(level[0].clone(), level[1].clone());
            }
        }
        self.bids.clear();
        for level in depth.bids {
            if level.len() >= 2 {
                self.bids.insert(level[0].clone(), level[1].clone());
            }
        }
        self.sequence = depth.s.unwrap_or(0);
        self.timestamp = depth.timestamp;
    }

    pub fn apply_diff(&mut self, diff: DepthDiff) {
        if diff.s <= self.sequence {
            return; // Ignore old diffs
        }
        
        for level in diff.asks {
            if level.len() >= 2 {
                let price = &level[0];
                let amount = &level[1];
                if amount == "0" || amount == "0.0000" {
                    self.asks.remove(price);
                } else {
                    self.asks.insert(price.clone(), amount.clone());
                }
            }
        }
        for level in diff.bids {
            if level.len() >= 2 {
                let price = &level[0];
                let amount = &level[1];
                if amount == "0" || amount == "0.0000" {
                    self.bids.remove(price);
                } else {
                    self.bids.insert(price.clone(), amount.clone());
                }
            }
        }
        self.sequence = diff.s;
        self.timestamp = diff.timestamp;
    }

    pub fn get_asks(&self) -> Vec<Vec<String>> {
        self.asks.iter().map(|(p, a)| vec![p.clone(), a.clone()]).collect()
    }

    pub fn get_bids(&self) -> Vec<Vec<String>> {
        // BTreeMap is ascending, so we need to reverse it for bids (highest first)
        self.bids.iter().rev().map(|(p, a)| vec![p.clone(), a.clone()]).collect()
    }

    /// Optimized: Get only Top N levels for faster Python processing
    pub fn get_top_n(&self, n: usize) -> (Vec<Vec<String>>, Vec<Vec<String>>) {
        let top_asks: Vec<Vec<String>> = self.asks.iter()
            .take(n)
            .map(|(p, a)| vec![p.clone(), a.clone()])
            .collect();
        
        let top_bids: Vec<Vec<String>> = self.bids.iter()
            .rev()
            .take(n)
            .map(|(p, a)| vec![p.clone(), a.clone()])
            .collect();
            
        (top_asks, top_bids)
    }
}
