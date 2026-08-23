#!/usr/bin/env python3
"""
結（Yui）ビルドスクリプト — インタプリタと標準ライブラリを各HTMLへ埋め込む

ブラウザ向けの5つの HTML は、いずれも単体で開けば動くことを狙って作られている。
そのため外部ファイルを読み込めず、JavaScript 実装と標準ライブラリを本文へ
直接埋め込む必要がある。これを手で維持すると、5つのコピーが必ずずれる。
実際、この仕組みを入れるまでインタプリタは5箇所に複製されており、
修正が repl.html にしか入っていない状態になっていた。

原本は次の3つだけ:
    yui.js             … JavaScript 実装のインタプリタ本体
    stdlib.yui         … 標準ライブラリ（Python 実装と共有）
    builtin_types.json … 組み込み関数の引数型（Python 実装と共有）

各 HTML の <script> は次の構造になる:

    YUI:BEGIN マーカー
      yui.js の内容
      const BUILTIN_ARG_TYPES = { builtin_types.json の内容 };
      const STDLIB_SRC = `stdlib.yui の内容`;
    YUI:END マーカー
      （ここから下は各 HTML 固有の UI と組み込み関数の追加）

使い方:
    python3 tools/build_html.py            # 5つの HTML を再生成
    python3 tools/build_html.py --check    # ずれていれば一覧を出して終了コード1

著作権表記：RTCK
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "yui.js"
STDLIB = ROOT / "stdlib.yui"
ARG_TYPES = ROOT / "builtin_types.json"
TARGETS = [
    "repl.html",
    "drama_player.html",
    "ai_player.html",
    "ai_dialog.html",
    "ai_branch.html",
]

BEGIN = "/* ── YUI:BEGIN ── tools/build_html.py が yui.js / stdlib.yui / builtin_types.json から生成する。直接編集しないこと ── */"
END = "/* ── YUI:END ── */"


def escape_for_template_literal(src: str) -> str:
    """JS のテンプレートリテラルに安全に埋め込める形へ変換する。

    バックスラッシュを最初に処理しないと、後続の置換で入れたエスケープを
    二重にエスケープしてしまうので順序が重要。
    """
    return src.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")


def render_block() -> str:
    core = io.open(CORE, encoding="utf-8").read().rstrip("\n")
    stdlib = escape_for_template_literal(io.open(STDLIB, encoding="utf-8").read().rstrip("\n"))
    # 説明用のキー（_ で始まる）は実行時に不要なので落とす
    raw = json.load(io.open(ARG_TYPES, encoding="utf-8"))
    sigs = {k: v for k, v in raw.items() if not k.startswith("_")}
    types = json.dumps(sigs, ensure_ascii=False, indent=2)
    return (f"{BEGIN}\n{core}\n\n"
            f"const BUILTIN_ARG_TYPES = {types};\n\n"
            f"const STDLIB_SRC = `{stdlib}\n`;\n{END}")


def locate_block(script: str, path: Path) -> tuple[int, int]:
    """<script> の中身から、生成対象ブロックの [開始, 終了) を返す。

    マーカーが既にあればそれを使う。無い初回は、先頭から
    「const STDLIB_SRC = `…`;」の終わりまでを対象とする。
    """
    i = script.find(BEGIN)
    if i != -1:
        j = script.find(END, i)
        if j == -1:
            raise SystemExit(f"エラー：{path.name} に YUI:BEGIN はあるが YUI:END がありません")
        return i, j + len(END)

    marker = "const STDLIB_SRC = `"
    k = script.find(marker)
    if k == -1:
        raise SystemExit(f"エラー：{path.name} に stdlib 埋め込みブロックが見つかりません")
    end = script.find("`;", k + len(marker))
    if end == -1:
        raise SystemExit(f"エラー：{path.name} の stdlib 埋め込みブロックの終端が見つかりません")
    # 旧 STDLIB マーカー付き（repl.html）は、その END までを含める
    old_end_marker = "/* ── STDLIB:END ── */"
    tail = script.find(old_end_marker, end)
    if tail != -1 and tail - end < 8:
        end = tail + len(old_end_marker) - len("`;")
    return 0, end + len("`;")


def process(path: Path, block: str, check_only: bool) -> bool:
    """同期していれば True。check_only=False なら必要に応じて書き換える。"""
    html = io.open(path, encoding="utf-8").read()
    m = re.search(r"(<script[^>]*>)(.*?)(</script>)", html, re.S)
    if not m:
        raise SystemExit(f"エラー：{path.name} に <script> が見つかりません")
    script = m.group(2)
    start, end = locate_block(script, path)

    if script[start:end] == block:
        return True
    if check_only:
        return False

    new_script = script[:start] + block + script[end:]
    io.open(path, "w", encoding="utf-8").write(
        html[:m.start(2)] + new_script + html[m.end(2):]
    )
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="yui.js / stdlib.yui / builtin_types.json を各 HTML へ埋め込む")
    ap.add_argument("--check", action="store_true",
                    help="書き換えず、ずれていれば一覧を出して終了コード1")
    args = ap.parse_args()

    block = render_block()
    stale = []
    for src in (CORE, STDLIB, ARG_TYPES):
        if not src.exists():
            raise SystemExit(f"エラー：原本 {src.name} が見つかりません")
    for name in TARGETS:
        path = ROOT / name
        if not path.exists():
            raise SystemExit(f"エラー：{name} が見つかりません")
        if not process(path, block, args.check):
            stale.append(name)

    if not stale:
        print(f"同期済み：{len(TARGETS)} 個の HTML は yui.js / stdlib.yui / builtin_types.json と一致しています")
        return 0
    if args.check:
        print("同期ずれ：次の HTML が原本と一致しません", file=sys.stderr)
        for n in stale:
            print(f"  {n}", file=sys.stderr)
        print("\n`python3 tools/build_html.py` を実行して再生成してください", file=sys.stderr)
        return 1
    print(f"生成しました：{', '.join(stale)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
