# 結（Yui）

> 助詞が役割を決め、主題が文脈を持続する、日本語ネイティブのプログラミング言語。

```
関数：[A]を[B]に足す
    戻り値：A + B
おわり

3を5に足す      ※ 8
5に3を足す      ※ 8 ── 語順は自由
```

既存の日本語プログラミング言語の多くが「キーワードの日本語化」に留まっていたのに対し、結（Yui）は **日本語の文法構造そのもの** を言語仕様に取り込んだ汎用プログラミング言語である。

完全な言語仕様は [SPEC.md](./SPEC.md) を参照。

---

## 設計の中核

| | 概要 |
|---|---|
| **助詞駆動の自由語順呼び出し** | `を / に / で / から / まで / より / と` などの格助詞が引数の役割を決める。引数の順序は自由 |
| **メソッド記法（「の」postfix）** | `配列の長さ`、`(-7)の絶対値`、`人の名前` のように所有格「の」で関数・属性アクセスを書ける。連鎖可能 |
| **主題持続（は文脈）** | 「〜は」で導入した主題が `〜について／おわり` ブロックの内側で暗黙のレシーバとして持続する |
| **文末ムード** | `〜とする / 〜である / 〜せよ / 〜だろうか` で代入・宣言・命令・述語を文法的に区別 |
| **自然語比較** | 「が」マーカーと「より大きい／と等しい／以上／以下／未満」で読み下しのまま比較式が書ける |
| **文字列補間** | `『{式}』` で式を文字列に埋め込める |

---

## クイックスタート

必要なもの: **Python 3.10 以降**（標準ライブラリのみ。外部依存なし）

```bash
git clone https://github.com/RTCK-reina/yui-lang.git
cd yui-lang

# ファイルを実行
python3 yui.py samples/hello.yui

# REPL
python3 yui.py
```

ブラウザだけで試すこともできる。`repl.html` を開けば、単一HTMLに収まったJavaScript実装のREPLが動く（インストール不要）。

---

## 書き味

```
※ 変数と文末ムード
名前 は 「田中」 である        ※ 〜である：再代入不可
年齢 を 22 とする              ※ 〜とする：再代入可
『{名前}さんは{年齢}歳です』を表示せよ

※ 自然語比較
もし 年齢 が 20 以上 ならば
    「成人」を表示せよ
おわり

※ 主題持続
数列 を ［3, 1, 4, 1, 5］ とする
数列について
    長さ を 表示せよ           ※ 5
    合計 を 表示せよ           ※ 14
    昇順 を 表示せよ           ※ ［1, 1, 3, 4, 5］
おわり

※ 種族（クラス相当）と「の」によるメソッド記法
種族 ユーザー：
    属性：名前, 年齢, 所属
おわり

関数：[本人]を 自己紹介する
    戻り値：『{本人の名前}（{本人の年齢}歳）』
おわり

※ 高階関数とラムダ
二倍 を 関数([X]を) X * 2 とする
(［1,2,3］に 二倍を 適用) を 表示せよ    ※ ［2, 4, 6］
```

---

## リポジトリ構成

| パス | 内容 |
|---|---|
| `yui.py` | Pythonリファレンス実装。Lexer / Parser / Tree-walking Evaluator。起動時に `stdlib.yui` を自動ロード |
| `yui.js` | ブラウザ実装の本体。5つの HTML はこれを埋め込んで生成される |
| `stdlib.yui` | 標準ライブラリ。Yui自身で書かれている |
| `builtin_types.json` | 組み込み関数の引数型。2つの実装が共有する |
| `SPEC.md` | 言語仕様書 v1.0。字句要素・BNF・設計判断記録まで |
| `repl.html` | ブラウザ版REPL。単一HTMLファイルに `yui.js` と stdlib を埋め込み |
| `drama.yui` | 劇作支援ライブラリ。ノベルゲーム・短編シナリオ・TRPG台本用の薄いDSL層 |
| `drama_player.html` | `drama.yui` で書かれたシナリオのブラウザプレイヤー |
| `ai_player.html` | WebLLM でブラウザ内にLLMを載せ、キャラクターと対話する実験 |
| `ai_dialog.html` | 複数のAIキャラクター同士を会話させるマルチエージェント実験 |
| `ai_branch.html` | AI生成による分岐ツリーの可視化実験 |
| `samples/` | サンプル21本 |
| `tools/build_html.py` | `yui.js` と `stdlib.yui` を5つの HTML へ埋め込むビルドスクリプト |
| `tools/diff_impls.py` | 2つの実装の挙動差を測る調査用ツール |
| `tools/browser_check.mjs` | 5つの HTML を実ブラウザで開いて操作する検証ツール |
| `tests/` | テスト。`cases.json` を2つの実装が共有する |

`ai_*.html` は [WebLLM](https://github.com/mlc-ai/web-llm) を使うため **WebGPU対応ブラウザ** が必要。モデルは画面上部のセレクタで選べる（既定は `ai_player.html` / `ai_dialog.html` が Llama 3.2 3B Instruct、`ai_branch.html` が Hermes 3 Llama 3.2 3B）。初回はモデルのダウンロードが走り、大きさは選択によって 0.8GB〜2.4GB。

3本とも「スキップ（オフラインデモ）」を選べば、モデルを落とさずに UI と Yui の実行部分だけ試せる。

---

## サンプル

`samples/` 以下は全て `python3 yui.py samples/<名前>.yui` で実行できる。

**言語機能**: `hello` `mood`（文末ムード）`free_word_order`（自由語順）`natural_compare`（自然語比較）`dict_demo` `class_demo`（種族）`lambda` `higher_order` `try_catch` `break_continue` `module_main` / `module_example/`（モジュール）

**アルゴリズム**: `fizzbuzz` `fibonacci` `factorial`

**実用**: `text_processing` `data_analysis` `todo_list` `stdlib_demo` `time_demo`

**シナリオ**: `yuri_demo`（`drama.yui` を使った短編『窓辺、四月』）

---

## 既知の制約

- インタプリタはツリー歩き型。コンパイルや末尾呼び出し最適化はない
- 再帰の深さは Python のスタック制限に依存（既定で約1000段）
- 文字列補間は内部で再パース・再評価するため、ホットループ内の補間は重い
- 仮引数は必ず `[名前]助詞` 形式が必要（助詞なし引数は不可）
- 関数名に助詞「を に で …」を含めると呼び出し時に分割される（含めない命名を推奨）
- 漢数字単独は数値リテラルとして扱われる（変数名に使う場合は他の文字を含める）
- ブラウザ版は `読み込む` が無効（同期ファイル取得不可のため）
- ブラウザ版は整数と小数を型として区別しない（JavaScript の `Number` を使うため）。結果が整数値になる小数演算の表示が Python 実装と食い違う
- 2つの実装の差は整数と小数の区別に起因するものだけが残っている（総当たり 1239 通り中 6 件。`python3 tools/diff_impls.py --all` で測れる）

---

## 開発

テストは外部依存なしで走る。追加のインストールは要らない。

```bash
python3 tests/run_tests.py    # Python 実装 + ビルド同期チェック + サンプル実行
node tests/js_test.mjs        # ブラウザ実装（Node だけで動く。ブラウザ不要）
```

`tests/js_test.mjs` は `repl.html` の `<script>` を取り出し、最小限の DOM スタブとともに Node の `vm` 上で実行する。ブラウザも Playwright も要らない。

テストケースは `tests/cases.json` に置いてあり、2つの実装が同じファイルを読む。未解決の不具合は `known_failure` を付けたまま残してあり、終了コードには影響しないが実行のたびに一覧表示される。

### HTML のビルド

ブラウザ向けの5つの HTML（`repl.html` / `drama_player.html` / `ai_player.html` / `ai_dialog.html` / `ai_branch.html`）は、いずれも単体で開けば動くことを狙っている。そのため外部ファイルを読み込めず、JavaScript 実装と標準ライブラリを本文へ直接埋め込む必要がある。

原本は2つだけで、5つの HTML の埋め込みブロックはそこから生成する。

| 原本 | 内容 |
|---|---|
| `yui.js` | JavaScript 実装のインタプリタ本体 |
| `stdlib.yui` | 標準ライブラリ（Python 実装と共有） |
| `builtin_types.json` | 組み込み関数の引数型（Python 実装と共有） |

```bash
python3 tools/build_html.py           # 5つの HTML を再生成
python3 tools/build_html.py --check   # ずれていれば一覧を出して終了コード1
```

各 HTML は生成ブロックの後ろに自分の UI と固有の組み込み関数を足す。たとえば `drama_player.html` は `表示` と `入力` を差し替え、劇用の関数を追加している。生成ブロックを直接編集しても次のビルドで上書きされるので、編集は `yui.js` / `stdlib.yui` / `builtin_types.json` に対して行う。走らせ忘れは両方のテストが検出する。

### 2つの実装の差を測る

`yui.py` と `yui.js` は同じ言語仕様を別々に実装しているため、放っておくとずれる。

```bash
python3 tools/diff_impls.py --all     # 組み込み × 引数型、主題ブロック経由、演算子 × 型 を総当たりで比較
```

助詞を明示する呼び出しと、主題ブロックで暗黙に渡す呼び出しは別経路なので両方測る。実際、型署名を入れた直後は主題経由だけに 18 件の食い違いが残っていた。

### ブラウザでの検証

`tests/js_test.mjs` は Node 上でインタプリタを動かすため、HTML の UI 側——とくに WebLLM を使う `ai_*.html`——には手が届かない。そこは実ブラウザで確かめる。

```bash
npm install playwright && npx playwright install chromium
node tools/browser_check.mjs          # 5つの HTML を開いて操作する
node tools/browser_check.mjs --show   # 画面を出して実行
```

WebLLM の CDN はスタブに差し替わり、各ページが期待する応答書式で返す。「LLM 出力 → 解析 → Yui コード生成 → インタプリタ実行 → 描画」の経路が、モデルのダウンロードもネットワークもなしで通る。Playwright を別途入れる必要があるため、依存なしで走る `tests/` には含めていない。

### 自動テストで届かない範囲

スタブは常に書式の整った応答を返すため、実際の LLM が応答を崩したときの復旧経路は通っていない。そこを含め、目視や実機でしか確認できない事項は [docs/manual_check.md](./docs/manual_check.md) にまとめてある。

---

## ライセンス

[MIT License](./LICENSE) — 著作権表記：RTCK
