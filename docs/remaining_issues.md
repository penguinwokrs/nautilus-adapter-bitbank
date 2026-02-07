# 残課題の整理 (Remaining Issues) - Nautilus Bitbank Adapter

## 1. 概要 (Overview)
Nautilus Trader 1.222.0 仕様への完全適合、PubNub を活用した約定・資産情報のリアルタイム同期、およびコードのクリーンアップが完了しました。

## 2. 解決済みの事項 (Resolved) - Updated 2026-02-07
- **Nautilus 1.222.0 への完全適合**: 
    - `AccountState`, `AccountBalance`, `Money`, `Currency` の最新コンストラクタへの対応（10引数、位置引数のみ）。
    - `Clock.now` 属性の非存在対応（フォールバック処理の実装）。
- **通貨解決の一般化**: 
    - `InstrumentProvider.currency()` を活用した動的通貨取得に移行。
    - フォールバックとして `nautilus_trader.model.currencies` のモジュール属性を参照。
- **TradeUpdate リアルタイム統合**: PubNub の `spot_trade` メッセージを処理し、REST を待たずに約定・受理を反映。
- **資産更新の整合性確保**: `total - locked == free` バリデーションをパスするため、整数演算へのキャストと逆算ロジックを導入。
- **レースコンディションの克服**: PubNub 通知が REST 応答より早く到着した際の `ClientOrderId` 検索リクエストを 10 回（1秒間）に強化。
- **コードクリーンアップ**: 
    - デバッグ用 `print()` 文の削除
    - `traceback.format_exc()` の削除
    - ログレベルの適正化 (`DEBUG`, `INFO`, `WARNING`, `ERROR`)

## 3. 残っている課題 (Pending Issues)

### A. 安定性の最終確認 (Stability - Low Priority)
- [ ] **長時間連続稼働エージング**: 24時間以上の連続接続を維持し、Rust 層での自動トークン更新が数日間問題なく動作することを確認する。

### B. 追加機能 (Optional - Future)
- [ ] **Backtest 互換性**: ヒストリカルデータの REST 取得プラグインの実装（現在は LIVE/PAPER のみ想定）。
- [ ] **全銘柄の通貨登録**: ビットバンクの全 60+ 銘柄に対応するため、初期化時に通貨を InstrumentProvider に動的登録するロジックの追加。

---
## 4. 検証済みフロー (Validated)
- [x] 初期接続 (REST 銘柄・資産取得)
- [x] リアルタイムティッカー受信 (Rust WebSocket)
- [x] 注文発行 → Accepted (PubNub経由)
- [x] 資産更新 (PubNub → AccountState → Portfolio)
- [x] 注文キャンセル → Canceled (PubNub経由)
- [x] 拘束解除の反映 (locked=0)

---
最終更新日: 2026-02-07
作成: Antigravity AI
