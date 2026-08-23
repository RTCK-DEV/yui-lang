#!/usr/bin/env python3
"""
結（Yui）テストランナー（Python 実装）

外部依存なし。標準ライブラリだけで動く。

    python3 tests/run_tests.py

実行する内容:
  1. ビルド同期チェック  repl.html の埋め込み stdlib が stdlib.yui と一致するか
  2. 言語ケース          tests/cases.json を Python 実装で実行し期待値と照合
  3. サンプル            samples/*.yui が例外なく完走するか

tests/cases.json の各ケース:
  name           ケース名
  src            実行する Yui ソース
  expect         期待する標準出力（末尾改行は無視）
  expect_error   期待するエラーメッセージの部分文字列（expect と排他）
  js             false ならブラウザ実装のテストでは対象外
  js_expect      ブラウザ実装だけ出力が異なる既知のケースの期待値
  known_failure  未解決の不具合。失敗しても終了コードには影響しないが必ず表示する

ブラウザ（JS）実装側は tests/js_test.mjs が同じ cases.json を使って検証する。

著作権表記：RTCK
"""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yui  # noqa: E402  （sys.path を通した後に読む必要がある）

OK = "  OK  "
NG = "  NG  "
KN = " 既知 "


def run_source(src: str) -> tuple[str, str | None]:
    """Yui ソースを実行し (標準出力, エラーメッセージ or None) を返す。"""
    buf = io.StringIO()
    err: str | None = None
    try:
        with contextlib.redirect_stdout(buf):
            yui.run(src)
    except (yui.LexError, yui.ParseError, yui.RuntimeYuiError) as e:
        err = str(e)
    except Exception as e:
        # Yui のエラー型以外がここに来るのは、インタプリタ内部の例外が
        # そのまま漏れているということ。区別できるよう型名を残す。
        err = f"{type(e).__name__}: {e}"
    return buf.getvalue().rstrip("\n"), err


def judge(case: dict, out: str, err: str | None) -> tuple[bool, str]:
    """ケースの合否と、実際に起きたことの説明を返す。"""
    if "expect_error" in case:
        if err is None:
            return False, f"エラーを期待したが正常終了（出力 {out!r}）"
        if case["expect_error"] not in err:
            return False, f"エラー文言が不一致：{err!r}"
        return True, err
    if err is not None:
        return False, f"エラー：{err}"
    if out != case["expect"]:
        return False, f"出力が不一致：{out!r}"
    return True, out


def check_build_sync() -> bool:
    print("── 1. ビルド同期チェック ──")
    script = ROOT / "tools" / "build_repl.py"
    if not script.exists():
        print(f"{NG} tools/build_repl.py が見つかりません")
        return False
    r = subprocess.run([sys.executable, str(script), "--check"],
                       capture_output=True, text=True)
    if r.returncode == 0:
        print(f"{OK} repl.html の埋め込み stdlib は stdlib.yui と同期しています")
        return True
    print(f"{NG} 同期ずれを検出しました")
    for line in (r.stdout + r.stderr).splitlines():
        print("        " + line)
    return False


def run_cases(cases: list[dict]) -> tuple[int, int, list[str]]:
    print("\n── 2. 言語ケース（Python 実装）──")
    passed = failed = 0
    known: list[str] = []
    for c in cases:
        out, err = run_source(c["src"])
        ok, detail = judge(c, out, err)
        if c.get("known_failure"):
            if ok:
                # 直ったのに known_failure が残っている状態。これも知らせる必要がある。
                print(f"{OK} {c['name']}（既知の未解決として登録されているが成功した。"
                      f"cases.json の known_failure を外すこと）")
                passed += 1
            else:
                known.append(f"{c['name']}：{detail}")
            continue
        if ok:
            passed += 1
        else:
            failed += 1
            print(f"{NG} {c['name']}")
            expected = c.get("expect_error", c.get("expect"))
            print(f"        期待: {expected!r}")
            print(f"        実際: {detail}")
    print(f"  {passed} 成功 / {failed} 失敗 / {len(known)} 既知の未解決"
          f"（全 {len(cases)} ケース）")
    return passed, failed, known


def run_samples() -> tuple[int, int]:
    print("\n── 3. サンプル実行（Python 実装）──")
    samples = sorted((ROOT / "samples").rglob("*.yui"))
    passed = failed = 0
    for path in samples:
        r = subprocess.run([sys.executable, str(ROOT / "yui.py"), str(path)],
                           capture_output=True, text=True, cwd=ROOT, timeout=60)
        if r.returncode == 0:
            passed += 1
        else:
            failed += 1
            print(f"{NG} {path.relative_to(ROOT)}")
            for line in r.stderr.strip().splitlines()[-3:]:
                print("        " + line)
    print(f"  {passed} 成功 / {failed} 失敗（全 {len(samples)} 本）")
    return passed, failed


def main() -> int:
    cases = json.load(io.open(ROOT / "tests" / "cases.json", encoding="utf-8"))
    print(f"結（Yui）テスト — Python {sys.version.split()[0]}\n")

    sync_ok = check_build_sync()
    _, case_failed, known = run_cases(cases)
    _, sample_failed = run_samples()

    if known:
        print("\n── 既知の未解決 ──")
        print("  未修正の不具合として意図的に残しているケース。"
              "終了コードには影響しないが、直ったら cases.json の known_failure を外すこと。")
        for k in known:
            print(f"{KN} {k}")

    total_failed = case_failed + sample_failed + (0 if sync_ok else 1)
    print()
    if total_failed:
        print(f"失敗：{total_failed} 件")
        return 1
    print(f"すべて成功（既知の未解決 {len(known)} 件は除く）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
