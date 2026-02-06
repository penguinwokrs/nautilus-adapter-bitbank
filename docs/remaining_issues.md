# Bitbank Adapter テスト修正 - 残り課題

## 概要
Bitbank アダプターのテストスイートで、非同期処理周りのモックとタスク実行待機に起因する失敗が発生しています。

## 失敗しているテスト

### 1. `test_data_client.py` (3件失敗)

#### `test_connect_subscribe`
**症状**: `assert data_client._ws_client.connect_py_called` が `False` のまま  
**原因**: `data_client.connect()` が非同期タスクを起動するが、テスト内でそのタスクが実行完了する前にアサーションが実行されている  
**関連コード**: 
- `nautilus_bitbank/data.py:56` の `_connect()` メソッド
- `LiveDataClient.connect()` の内部実装

**修正方針**:
- `asyncio.sleep()` の待機時間を延ばす
- または `Event` を使ってタスク完了を待機する
- または `_connect()` を直接 `await` する方法を検討

#### `test_handle_ticker` と `test_handle_transactions`
**症状**: `assert data_client._handle_data.called` が `False` のまま  
**原因**: `_find_instrument()` がインストルメントを見つけられず、ハンドラーが早期リターンしている可能性  
**修正方針**:
- インストルメントの登録方法を確認（現在は `_subscribed_instruments[instrument.value]` に追加しているが、正しいキーか確認）
- `_find_instrument()` のロジックを再確認

### 2. `test_execution_client.py` (2件失敗)

#### `test_submit_order`
**症状**: `mock_rest.create_order_py_mock.assert_called_with(...)` で「not called」エラー  
**原因**: `await exec_client._submit_order(command)` 内で例外が発生しているか、モックの型チェックで失敗している可能性  
**関連コード**:
- `nautilus_bitbank/execution.py:170-244` の `_submit_order()` メソッド
- `command.order` のプロパティが正しく設定されているか

**修正方針**:
- `_submit_order()` 内でのログ出力を追加してデバッグ
- `command.order` の各プロパティの型を確認（`MagicMock` ではなく実際の型が必要か）
- 例外が発生していないか確認

#### `test_handle_pubnub_message_trigger`
**症状**: `exec_client._process_order_update.assert_called()` で「not called」エラー  
**原因**: `_handle_pubnub_message()` 内で `create_task()` されたタスクが、`asyncio.sleep(0.1)` の間に実行されていない  
**修正方針**:
- `asyncio.sleep()` の待機時間を延ばす
- または PubNub メッセージのパース処理に問題がないか確認

## 根本原因の仮説

### 仮説1: イベントループの実行タイミング
pytest-asyncio のイベントループで `create_task()` されたタスクが、テストコード内の `await` が無いと実行されない可能性があります。

**検証方法**:
```python
# テスト内で明示的にタスクを待機
await asyncio.sleep(0.5)  # より長い待機
# または
while not some_condition:
    await asyncio.sleep(0.01)
```

### 仮説2: モックの型チェック
Nautilus Trader の Cython 実装が、`MagicMock` オブジェクトを受け付けず、型検証で失敗している可能性があります。

**検証方法**:
- `command.order` の各プロパティに実際の型のインスタンスを設定
- `StrategyId`, `InstrumentId` などを `MagicMock` ではなく実オブジェクトで作成

### 仮説3: Fixture の初期化順序
`conftest.py` でのモック注入のタイミングが遅すぎる、または上書きされている可能性があります。

**検証方法**:
- テスト開始時に `print()` でモックの状態をダンプ
- `data_client._ws_client` が正しく `ManualMockWebSocketClient` のインスタンスか確認

## 次のアクション

1. **デバッグ出力の追加**: `conftest.py` と各テストファイルに `print()` を追加し、モックの状態とタスク実行を追跡
2. **イベントループの確認**: `pytest -s` で標準出力を確認しながら、タスクが実行されているか確認
3. **段階的な修正**: まず `test_data_client.py` の `connect` 問題を解決し、次に `execution_client` に進む

## 参考情報

- `LiveDataClient.connect()` は同期メソッドだが、内部で `create_task(self._connect())` を呼び出す
- `RuntimeWarning: coroutine 'BitbankDataClient._connect' was never awaited` が出ているが、実際には `create_task()` されているため、この警告自体は問題ない
- pytest-asyncio のイベントループは各テスト関数ごとに作成され、テスト終了時にクリーンアップされる
