#!/usr/bin/env python3
"""
結（Yui）ビルドスクリプト — stdlib.yui を repl.html へ埋め込む

repl.html はブラウザ単体で動く単一HTMLなので、標準ライブラリを外部ファイルとして
読み込めない（同期ファイル取得が使えない）。そのため stdlib.yui の内容を
JS のテンプレートリテラルとして埋め込んでいる。

この二重化を手作業で維持すると必ずずれるので、真実は stdlib.yui 側だけに置き、
repl.html の該当ブロックはこのスクリプトで生成する。

使い方:
    python3 tools/build_repl.py            # repl.html を stdlib.yui から再生成
    python3 tools/build_repl.py --check    # 同期していなければ差分を表示して終了コード1

著作権表記：RTCK
"""
from __future__ import annotations

import argparse
import difflib
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STDLIB = ROOT / "stdlib.yui"
REPL = ROOT / "repl.html"

BEGIN = "/* ── STDLIB:BEGIN ── tools/build_repl.py が stdlib.yui から生成する。直接編集しないこと ── */"
END = "/* ── STDLIB:END ── */"


def escape_for_template_literal(src: str) -> str:
    """JS のテンプレートリテラルに安全に埋め込める形へ変換する。

    バックスラッシュを最初に処理しないと、後続の置換で入れたエスケープを
    二重にエスケープしてしまうので順序が重要。
    """
    src = src.replace("\\", "\\\\")
    src = src.replace("`", "\\`")
    src = src.replace("${", "\\${")
    return src


def render_block(stdlib_src: str) -> str:
    body = escape_for_template_literal(stdlib_src.rstrip("\n"))
    return f"{BEGIN}\nconst STDLIB_SRC = `{body}\n`;\n{END}"


def locate_block(html: str) -> tuple[int, int]:
    """埋め込みブロックの [開始, 終了) バイト位置を返す。

    マーカーがまだ無い初回は、旧来の `const STDLIB_SRC = \\`` … `\\`;` を拾う。
    """
    i = html.find(BEGIN)
    if i != -1:
        j = html.find(END, i)
        if j == -1:
            raise SystemExit("エラー：STDLIB:BEGIN はあるが STDLIB:END が見つかりません")
        return i, j + len(END)

    marker = "const STDLIB_SRC = `"
    i = html.find(marker)
    if i == -1:
        raise SystemExit("エラー：repl.html に stdlib 埋め込みブロックが見つかりません")
    j = html.find("`;", i + len(marker))
    if j == -1:
        raise SystemExit("エラー：stdlib 埋め込みブロックの終端が見つかりません")
    return i, j + len("`;")


def build(check_only: bool) -> int:
    stdlib_src = io.open(STDLIB, encoding="utf-8").read()
    html = io.open(REPL, encoding="utf-8").read()

    start, end = locate_block(html)
    current = html[start:end]
    expected = render_block(stdlib_src)

    if current == expected:
        print(f"同期済み：repl.html の埋め込み stdlib は {STDLIB.name} と一致しています")
        return 0

    if check_only:
        print(f"同期ずれ：repl.html の埋め込み stdlib が {STDLIB.name} と一致しません", file=sys.stderr)
        diff = difflib.unified_diff(
            current.splitlines(), expected.splitlines(),
            "repl.html（現在の埋め込み）", "stdlib.yui から生成される内容",
            lineterm="", n=2,
        )
        for line in diff:
            print(line, file=sys.stderr)
        print("\n`python3 tools/build_repl.py` を実行して再生成してください", file=sys.stderr)
        return 1

    io.open(REPL, "w", encoding="utf-8").write(html[:start] + expected + html[end:])
    changed = sum(
        1 for line in difflib.unified_diff(current.splitlines(), expected.splitlines(), lineterm="")
        if line[:1] in "+-" and line[:3] not in ("---", "+++")
    )
    print(f"生成しました：repl.html の埋め込み stdlib を更新（{changed} 行の差分）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="stdlib.yui を repl.html へ埋め込む")
    ap.add_argument("--check", action="store_true",
                    help="書き換えず、同期していなければ差分を表示して終了コード1")
    args = ap.parse_args()
    return build(args.check)


if __name__ == "__main__":
    sys.exit(main())
