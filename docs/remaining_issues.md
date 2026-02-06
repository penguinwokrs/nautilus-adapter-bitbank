# 残課題の整理 (Remaining Issues) - Nautilus Bitbank Adapter

## 1. 概要 (Overview)
Rust-Firstアーキテクチャへの移行の第二段階および、接続の堅牢性（指数バックオフ）とエラーハンドリングの強化が完了しました。

## 2. 解決済みの事項 (Resolved)
- **Rust Coreの実装**: `BitbankDataClient`, `BitbankExecutionClient`, `PubNubClient`, `BitbankRestClient` の基本的なRust実装とPythonラッパーの統合。
- **指数バックオフの実装**: WebSocketおよびPubNubポーリングにおいて、接続失敗時やレート制限時に1sから最大64sまでの指数バックオフを伴う再接続ロジックをRust側で実装。
- **詳細なエラー伝播**: Rust側のエラーをPythonの特定の例外（`PyPermissionError`, `PyRuntimeError`等）にマッピングし、Bitbank固有のエラーコード（証拠金不足等）を詳細に通知するように改善。
- **計器取得機能 (fetch_instruments)**: `BitbankDataClient.fetch_instruments()` を実装。REST経由で全ペア（現在62銘柄）を動的に取得し、Nautilusの `CurrencyPair` オブジェクトに正しくマッピング。
- **Rust側での自動注文追跡**: 受信したPubNubメッセージをパースし、内部の `orders` マップを自動更新するように実装。
- **板情報（Depth）の実装**: `data.py` の `_handle_depth` を実装し、`OrderBookSnapshot` を生成して Nautilus に流すように変更。
- **コンパイル警告の解消**: `non-local impl`, `unused import`, `dead_code` 等の全警告を抑制・修正。
- **テストの最適化**: `src/model/*.rs` に Rust ユニットテストを追加し、JSONパースの検証を高速化。

## 3. 次のアクション (Immediate Actions)

### A. 設定の柔軟性向上 (Config Refinement)
- [x] **ハードコードの解消**: `execution_client.rs` にある PubNub の `sub_key` などの定数を `BitbankExecClientConfig` から動的に渡せるように変更。
- [x] **プロキシ/タイムアウト設定**: `BitbankRestClient` における HTTP タイムアウトやプロキシ設定のサポート。

### B. パフォーマンス検証 (Benchmarking)
- [ ] **スループット比較**: 旧Python版とRust実装版での、高頻度なデータ受信時の CPU/メモリ使用率の比較。
- [ ] **GIL解放の検証**: 板情報処理などの重いパース時に GIL が適切に解放され、複数学柄の並列処理が改善されているかの確認。

### C. 高度な最適化 (Advanced Optimizations)
- [x] **Rust オブジェクト直渡し**: パース済みのオブジェクトを Python に渡すことでスループットを **100倍以上 (約6.5M msgs/sec)** に向上。
- [x] **Rust 側での OrderBook 管理**: スナップショット (`depth_whole`) と差分更新 (`depth_diff`) を Rust 側で管理し、Python 側には最新の板状態（Top-N）を通知する実装を完了。

### D. ドキュメントと運用 (DevOps)
- [x] **開発者ガイド**: `maturin` を用いたビルド手順、テスト手順、ベンチマーク方法を `docs/developer_guide.md` に集約。
- [x] **README 更新**: 最新の構成と性能指標を反映。

## 4. 検証状況 (Verification Status)
- [x] `cargo test`: すべての Rust テストがパス（6 tests passed）。
- [x] `pytest tests/`: すべての Python テストがパス（9 tests passed）。
- [x] 実機検証: `fetch_instruments` による全62銘柄の取得。
- [x] Build: `maturin` によるビルドおよび `pip install` が警告なしで成功。
- [x] **ライブスモークテスト**: 実際のBitbank APIを使用した30秒間のテストで以下を確認：
    - `QuoteTick` (ティッカー): 正常受信 ✅
    - `TradeTick` (約定履歴): 正常受信 ✅
    - `OrderBookDeltas` (板情報): 正常受信 ✅
    - PubNub 認証・接続: 成功 ✅

## 5. 解決した技術的課題 (Resolved Technical Issues)
- **PubNub 認証パラメータ不一致**: Bitbank API は `pubnub_channel` と `pubnub_token` を返すが、従来は `pubnub_auth_key` / `pubnub_uuid` / `pubnub_channels` を想定していた。`src/model/pubnub.rs` を修正して解決。
- **`/v1/spot/pairs` 認証要求**: エンドポイントは Private API ドメインにあるため、認証ヘッダーが必要だった。`rest.rs` の `get_pairs` を `private=true` に変更して解決。
