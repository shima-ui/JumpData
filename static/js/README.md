# JavaScriptモジュール化ドキュメント

## 📁 モジュール構成

元の1568行の`main.js`を以下のモジュールに分離しました:

### 1. `state.js` - 状態管理モジュール
**責務**: アプリケーション全体の状態を管理

- **グローバル変数の管理**
  - 進捗インターバル
  - クエリ情報（現在のクエリ、元のクエリ、選択状態）
  - 号数と日付のマッピング
  - トレンドワード情報
  - 解析結果とレポートタブ
  - ソート状態

- **主要な関数**
  - `getProgressInterval()` / `setProgressInterval()`
  - `getCurrentQueries()` / `setCurrentQueries()`
  - `getOriginalQueries()` / `setOriginalQueries()`
  - `getTrendWords()` / `setTrendWords()`
  - `getCurrentResults()` / `setCurrentResults()`
  - その他、各状態のgetter/setter

### 2. `api.js` - API通信モジュール
**責務**: バックエンドAPIとの通信を担当

- **主要な関数**
  - `fetchQueries()` - クエリ情報と号数マッピングを取得
  - `startAnalysis()` - 解析を開始
  - `fetchProgress()` - 解析の進捗を取得
  - `fetchResults()` - 解析結果を取得
  - `saveToCSV()` - 結果をCSVに保存

### 3. `utils-module.js` - ユーティリティモジュール
**責務**: 汎用的な処理とデータ変換

- **主要な関数**
  - `getImageUrl()` - 画像URLを取得
  - `buildQueryFromList()` - クエリリストから文字列を作成
  - `parseQueryToList()` - クエリ文字列をリストに分解
  - `getTrendWordsMap()` - トレンドワードを作品別にマッピング
  - `getSortIcon()` - ソートアイコンを取得
  - `sortData()` - データをソート
  - `groupResultsByWork()` - 作品結果をグループ化
  - `createSummaryData()` - サマリーデータを作成
  - `createRankingData()` - ランキングデータを作成

### 4. `chart.js` (今後作成予定)
**責務**: Chart.jsを使用したグラフ描画

- グラフ作成関数
- グラフ設定とオプション管理

### 5. `ui.js` (今後作成予定)
**責務**: DOM操作とUI描画

- クエリエディタの描画
- サマリーテーブルの描画
- 結果カードの描画
- トレンドテーブルの描画
- ランキング表示

### 6. `main.js` (リファクタリング後)
**責務**: モジュール統合とイベントハンドリング

- 各モジュールのインポート
- イベントリスナーの登録
- ページ初期化処理

## 🎯 モジュール化のメリット

### 1. **保守性の向上**
- 各モジュールの責任が明確
- コードの所在が分かりやすい
- バグの特定と修正が容易

### 2. **再利用性**
- 独立したモジュールとして他のプロジェクトでも利用可能
- 共通処理の重複を削減

### 3. **テスト容易性**
- 各モジュールを個別にテスト可能
- モックを使用した単体テストが容易

### 4. **可読性**
- 機能ごとにファイルが分かれているため理解しやすい
- 関数名から機能を推測しやすい

### 5. **拡張性**
- 新機能の追加が容易
- 既存コードへの影響を最小限に抑えられる

### 6. **パフォーマンス**
- 必要なモジュールのみをロード可能（遅延ロード）
- コードの最適化が容易

## 📝 使用方法

### HTMLでのモジュール読み込み

```html
<!-- ES6モジュールとして読み込み -->
<script type="module" src="/static/js/state.js"></script>
<script type="module" src="/static/js/api.js"></script>
<script type="module" src="/static/js/utils-module.js"></script>
<script type="module" src="/static/js/main.js"></script>
```

### モジュールのインポート例

```javascript
// main.jsでの使用例
import * as State from './state.js';
import * as API from './api.js';
import * as Utils from './utils-module.js';

// 状態の取得
const queries = State.getCurrentQueries();

// API呼び出し
const data = await API.fetchQueries();

// ユーティリティ使用
const imageUrl = Utils.getImageUrl('作品名');
```

## 🔄 今後の改善予定

1. **chart.js** - グラフ描画ロジックの分離
2. **ui.js** - UI描画処理の分離
3. **main.js** - リファクタリングして薄いレイヤーに
4. TypeScript化の検討
5. ビルドツールの導入（Webpack/Viteなど）
6. ユニットテストの追加

## 📚 参照

- [ES6 Modules Documentation](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Modules)
- [JavaScript Best Practices](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide)
