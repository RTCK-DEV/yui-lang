#!/usr/bin/env python3
"""
2つの実装（yui.py / repl.html）の挙動差を測る道具

同じ式を両方の実装で評価し、結果が食い違うものを一覧にする。
テストではなく調査用。終了コードは常に 0（差があること自体は現時点では既知）。

    python3 tools/diff_impls.py              # 組み込み関数 × 引数型 の総当たり
    python3 tools/diff_impls.py --ops        # 演算子 × 型の組み合わせ
    python3 tools/diff_impls.py --topic      # 主題ブロック経由の呼び出し
    python3 tools/diff_impls.py --all        # 全部

node が必要（repl.html の JS を Node の vm 上で動かすため）。

背景：この2実装は同じ言語仕様を別々に実装しているため、放っておくと必ず
ずれる。SPEC 16 に既知の差を書いてあるが、網羅的な確認はこの道具で行う。

著作権表記：RTCK
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import yui  # noqa: E402

# 引数に渡す値のリテラル表現。型名 → Yui のソース片。
VALUES = {
    "整数": "5", "小数": "1.5", "文字列": "「abc」", "真偽": "真",
    "無": "無", "配列": "［1, 2, 3］", "辞書": "{「k」→ 1}",
}
# 副作用があるもの・実行のたびに結果が変わるものは比較できない
SKIP = {"入力", "読み込む", "乱数", "シャッフル", "選ぶ", "今", "今日",
        "投げる", "断言", "表示"}

JS_RUNNER = r"""
import fs from 'node:fs'; import vm from 'node:vm';
const html = fs.readFileSync(process.argv[2], 'utf8');
const m = html.match(/<script>([\s\S]*?)<\/script>/);
const el = () => ({value:'',innerHTML:'',textContent:'',options:[],style:{},
  classList:{add(){},remove(){}},addEventListener(){},appendChild(){},setAttribute(){},focus(){}});
const ctx = {document:{getElementById:el,createElement:el,addEventListener(){}},
  window:{addEventListener(){}}, prompt:()=>null, console};
ctx.globalThis = ctx; vm.createContext(ctx);
vm.runInContext(m[1], ctx, {filename:'repl.html'});
const sources = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const out = {};
for (const [key, src] of Object.entries(sources)) {
  const r = ctx.runYui(src);
  out[key] = r.ok ? {ok:true, v:String(r.output).trim()} : {ok:false};
}
process.stdout.write(JSON.stringify(out));
"""


def run_python(sources: dict[str, str]) -> dict[str, dict]:
    out = {}
    for key, src in sources.items():
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                yui.run(src)
            out[key] = {"ok": True, "v": buf.getvalue().strip()}
        except Exception:
            out[key] = {"ok": False}
    return out


def run_js(sources: dict[str, str]) -> dict[str, dict]:
    if not shutil.which("node"):
        print("node が見つかりません。ブラウザ実装側は比較できません。", file=sys.stderr)
        sys.exit(2)
    with tempfile.TemporaryDirectory() as d:
        runner = Path(d) / "runner.mjs"
        payload = Path(d) / "sources.json"
        runner.write_text(JS_RUNNER, encoding="utf-8")
        payload.write_text(json.dumps(sources, ensure_ascii=False), encoding="utf-8")
        r = subprocess.run(
            ["node", str(runner), str(ROOT / "repl.html"), str(payload)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(r.stderr, file=sys.stderr)
            sys.exit(2)
        return json.loads(r.stdout)


def builtin_sources() -> dict[str, str]:
    src = {}
    for name in sorted(yui._BUILTINS):
        if name in SKIP:
            continue
        for tname, lit in VALUES.items():
            src[f"組み込み {name}｜{tname}"] = f"({lit} を {name}) を 表示せよ"
    return src


def topic_sources() -> dict[str, str]:
    """主題ブロックの内側で、助詞を書かずに呼ぶ形。

    助詞を明示する呼び出しとは別経路（暗黙に主題が渡る）なので、
    型検査の抜けがここだけに残ることがある。実際、型署名を入れた直後は
    この経路だけで 18 件の食い違いが残っていた。
    """
    src = {}
    for name in sorted(yui._BUILTINS):
        if name in SKIP:
            continue
        for tname, lit in VALUES.items():
            src[f"主題 {name}｜{tname}"] = (
                f"x を {lit} とする\nxについて\n    ({name}) を 表示せよ\nおわり"
            )
    return src


def operator_sources() -> dict[str, str]:
    src = {}
    for op in ["+", "-", "*", "/", "%", "==", "!=", "<", ">", "<=", ">="]:
        for ln, ll in VALUES.items():
            for rn, rl in VALUES.items():
                src[f"演算 {ln} {op} {rn}"] = f"({ll} {op} {rl}) を 表示せよ"
    return src


def report(sources: dict[str, str]) -> int:
    py = run_python(sources)
    js = run_js(sources)
    diffs = []
    for key in sources:
        P, J = py[key], js[key]
        if P["ok"] == J["ok"] and (not P["ok"] or P["v"] == J["v"]):
            continue
        diffs.append((key,
                      json.dumps(P["v"], ensure_ascii=False) if P["ok"] else "エラー",
                      json.dumps(J["v"], ensure_ascii=False) if J["ok"] else "エラー"))
    total = len(sources)
    print(f"比較 {total} 通り：一致 {total - len(diffs)} / 不一致 {len(diffs)}")
    if diffs:
        print()
        width = max(len(k) for k, _, _ in diffs)
        for key, p, j in diffs:
            print(f"  {key.ljust(width)}  Python {p}  /  ブラウザ {j}")
    return len(diffs)


def main() -> int:
    ap = argparse.ArgumentParser(description="2つの実装の挙動差を測る")
    ap.add_argument("--ops", action="store_true", help="演算子 × 型の組み合わせを比較")
    ap.add_argument("--topic", action="store_true", help="主題ブロック経由の呼び出しを比較")
    ap.add_argument("--all", action="store_true", help="全部")
    a = ap.parse_args()

    selected = a.ops or a.topic
    if a.all or not selected:
        print("── 組み込み関数 × 引数型 ──")
        report(builtin_sources())
    if a.all or a.topic:
        print("\n── 主題ブロック経由 ──" if (a.all or not a.topic) else "── 主題ブロック経由 ──")
        report(topic_sources())
    if a.all or a.ops:
        print("\n── 演算子 × 型 ──" if (a.all or not a.ops) else "── 演算子 × 型 ──")
        report(operator_sources())
    return 0


if __name__ == "__main__":
    sys.exit(main())
