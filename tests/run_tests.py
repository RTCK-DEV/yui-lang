#!/usr/bin/env python3
"""
結（Yui）テストランナー（Python 実装）

外部依存なし。標準ライブラリだけで動く。

    python3 tests/run_tests.py

実行する内容:
  1. ビルド同期チェック  5つの HTML の埋め込みが yui.js / stdlib.yui と一致するか
  2. 言語ケース          tests/cases.json を Python 実装で実行し期待値と照合
  3. サンプル            samples/*.yui が例外なく完走するか
  4. 組み込みの不変条件  どの組み込みも Python の例外を素通しさせないこと

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
    script = ROOT / "tools" / "build_html.py"
    if not script.exists():
        print(f"{NG} tools/build_html.py が見つかりません")
        return False
    r = subprocess.run([sys.executable, str(script), "--check"],
                       capture_output=True, text=True)
    if r.returncode == 0:
        print(f"{OK} 5つの HTML は yui.js / stdlib.yui と同期しています")
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


def check_builtin_errors() -> int:
    """どの組み込みに何を渡しても Yui のエラーになることを確かめる。

    組み込みは Python の str / list / math をそのまま使っているため、
    型検査を怠ると TypeError や AttributeError が利用者まで抜ける。
    実際に 60 個中 41 個がそうなっていた。個別に直すのではなく
    _invoke_builtin 1 箇所で受け止める設計にしたので、その不変条件を
    総当たりで確かめる。ここが破れたら受け止め漏れがあるということ。
    """
    print("\n── 4. 組み込みの不変条件（Python 実装）──")
    values = {"整数": 5, "小数": 1.5, "文字列": "abc", "真偽": True,
              "無": None, "配列": [1, 2, 3], "辞書": {"k": 1}}
    combos = [("を",), ("を", "に"), ("を", "で"), ("から", "を"),
              ("を", "と"), ("へ", "を"), ("を", "まで")]
    # 副作用があるもの・入力を待つものは対象外
    skip = {"入力", "読み込む"}
    leaks: dict[str, set[str]] = {}
    checked = 0
    for name in sorted(yui._BUILTINS):
        if name in skip:
            continue
        for v in values.values():
            for combo in combos:
                checked += 1
                try:
                    with contextlib.redirect_stdout(io.StringIO()):
                        yui._invoke_builtin(name, {p: v for p in combo}, yui.Environment())
                except (yui.RuntimeYuiError, yui.LexError, yui.ParseError):
                    pass
                except (yui.ReturnSignal, yui.BreakSignal, yui.ContinueSignal):
                    pass
                except Exception as e:
                    leaks.setdefault(name, set()).add(type(e).__name__)
    if not leaks:
        print(f"{OK} {checked} 通りを試して、Yui 以外の例外は 1 件も漏れませんでした")
        return 0
    for name, kinds in sorted(leaks.items()):
        print(f"{NG} {name} が {'、'.join(sorted(kinds))} を素通しさせています")
    print(f"  {len(leaks)} 個の組み込みで例外が漏れています（全 {checked} 通り中）")
    return len(leaks)


def main() -> int:
    cases = json.load(io.open(ROOT / "tests" / "cases.json", encoding="utf-8"))
    print(f"結（Yui）テスト — Python {sys.version.split()[0]}\n")

    sync_ok = check_build_sync()
    _, case_failed, known = run_cases(cases)
    _, sample_failed = run_samples()
    leak_failed = check_builtin_errors()

    if known:
        print("\n── 既知の未解決 ──")
        print("  未修正の不具合として意図的に残しているケース。"
              "終了コードには影響しないが、直ったら cases.json の known_failure を外すこと。")
        for k in known:
            print(f"{KN} {k}")

    total_failed = case_failed + sample_failed + leak_failed + (0 if sync_ok else 1)
    print()
    if total_failed:
        print(f"失敗：{total_failed} 件")
        return 1
    print(f"すべて成功（既知の未解決 {len(known)} 件は除く）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
