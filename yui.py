#!/usr/bin/env python3
"""
結（Yui）言語インタプリタ — リファレンス実装
著作権表記：RTCK

仕様：./SPEC.md
使い方：
    python3 yui.py <ファイル.yui>
    python3 yui.py        # REPL
"""
from __future__ import annotations
import sys
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# =============================================================================
# 0. 文字正規化
# =============================================================================

# 全角→半角の正規化マップ（句読点は除く。文字列リテラル内の「、」を保護するため）
_ZEN2HAN = str.maketrans({
    "０":"0","１":"1","２":"2","３":"3","４":"4",
    "５":"5","６":"6","７":"7","８":"8","９":"9",
    "＋":"+","－":"-","×":"*","÷":"/","％":"%",
    "＝":"=","＜":"<","＞":">",
    "（":"(","）":")","［":"[","］":"]","｛":"{","｝":"}",
    "：":":",
    "　":" ",
})

# 漢数字 → 数値
_KAN_DIGIT = {"零":0,"〇":0,"一":1,"二":2,"三":3,"四":4,
              "五":5,"六":6,"七":7,"八":8,"九":9}
_KAN_UNIT  = {"十":10,"百":100,"千":1000,"万":10000,"億":10**8}

def _kan2int(s: str) -> Optional[int]:
    """漢数字文字列を整数に変換。失敗したら None。"""
    if not s or any(c not in _KAN_DIGIT and c not in _KAN_UNIT for c in s):
        return None
    total = 0
    section = 0
    current = 0
    for c in s:
        if c in _KAN_DIGIT:
            current = _KAN_DIGIT[c]
        else:
            unit = _KAN_UNIT[c]
            if unit >= 10000:
                base = section + current
                if base == 0:
                    base = 1
                section = base * unit
                total += section
                section = 0
            else:
                section += (current if current else 1) * unit
            current = 0
    return total + section + current

def _norm_char(c: str) -> str:
    """1文字単位の正規化。"""
    return c.translate(_ZEN2HAN)

def _norm_chunk(s: str) -> str:
    """文字列の正規化（リテラル外側のみ呼ぶこと）。"""
    s = s.replace("≠", "!=").replace("≦", "<=").replace("≧", ">=")
    return s.translate(_ZEN2HAN)

# =============================================================================
# 1. 字句解析（Lexer）
# =============================================================================

# 助詞（v0.2 で「の」追加）
PARTICLES = ["から", "まで", "より", "について", "を", "に", "で", "へ", "と", "は", "が", "の"]
# キーワード
KEYWORDS  = [
    "もし", "ならば", "そうでなければ", "おわり",
    "繰り返す", "のあいだ", "各",
    "関数", "戻り値", "戻る",
    "真", "偽", "無",
    "かつ", "または", "でない",
    "とする", "である", "せよ", "だろうか",
    "以上", "以下", "未満",
    "等しい", "等しくない", "大きい", "小さい",
    "やめる", "次へ",
    "種族", "属性", "新しい",
    "試す", "ならば失敗",
]

# 多文字演算子と区切り（順序が長いもの優先）
SYMBOLS = ["==", "!=", "<=", ">=", "<", ">", "+", "-", "*", "/", "%", "=",
           "(", ")", "[", "]", "{", "}", ":", ",", "."]

@dataclass
class Token:
    kind: str      # NUM, STR, IDENT, PARTICLE, KW, SYM, NEWLINE, EOF
    value: Any
    line: int

class LexError(Exception): pass

_IDENT_CHAR = re.compile(r"[ぁ-んァ-ヶー一-龥a-zA-Z_0-9々〆ヵヶ]")
_IDENT_START = re.compile(r"[ぁ-んァ-ヶー一-龥a-zA-Z_々〆ヵヶ]")
# 助詞・キーワードを長い順にソートして最長マッチに使う
_KW_OR_PARTICLE_SORTED = sorted(set(KEYWORDS + PARTICLES), key=len, reverse=True)

def tokenize(source: str) -> list[Token]:
    """ソースコードを字句解析する。
    文字列リテラル・コメントの内側は正規化しないで保持し、
    それ以外はトークン化時に文字単位で正規化する。
    """
    src = source
    tokens: list[Token] = []
    i = 0
    line = 1
    n = len(src)

    def emit(kind, value):
        tokens.append(Token(kind, value, line))

    while i < n:
        c = src[i]

        # 改行
        if c == "\n":
            if tokens and tokens[-1].kind != "NEWLINE":
                emit("NEWLINE", "\n")
            line += 1
            i += 1
            continue

        # 空白・タブ・全角空白・読点（区切り文字として無視）
        if c in " \t\r　、，":
            i += 1
            continue

        # 行コメント ※...
        if c == "※":
            while i < n and src[i] != "\n":
                i += 1
            continue

        # ブロックコメント 〔...〕
        if c == "〔":
            depth = 1
            i += 1
            while i < n and depth > 0:
                if src[i] == "〔": depth += 1
                elif src[i] == "〕": depth -= 1
                elif src[i] == "\n": line += 1
                i += 1
            continue

        # 文字列リテラル「...」（生）/ 『...』（補間あり）
        if c in "「『":
            close = "」" if c == "「" else "』"
            is_raw = (c == "「")
            i += 1
            buf = []
            while i < n and src[i] != close:
                if not is_raw and src[i] == "\\" and i+1 < n:
                    nx = src[i+1]
                    buf.append({"n":"\n","t":"\t","r":"\r","\\":"\\",
                                "「":"「","」":"」","『":"『","』":"』",
                                "{":"\x01","}":"\x02"}.get(nx, nx))
                    i += 2
                else:
                    if src[i] == "\n": line += 1
                    buf.append(src[i])
                    i += 1
            if i >= n:
                raise LexError(f"{line}行目：文字列リテラルが閉じていません")
            i += 1  # 閉じ括弧
            kind = "STR_RAW" if is_raw else "STR_COOKED"
            emit(kind, "".join(buf))
            continue

        # 数字（半角・全角・桁区切り「_」許容）
        nc = _norm_char(c)
        if nc.isdigit():
            j = i
            buf = []
            while j < n:
                cn = _norm_char(src[j])
                if cn == "_":   # 桁区切り：読み飛ばす
                    j += 1
                    continue
                if cn.isdigit() or cn == ".":
                    buf.append(cn); j += 1
                else:
                    break
            num_str = "".join(buf)
            val = float(num_str) if "." in num_str else int(num_str)
            emit("NUM", val)
            i = j
            continue

        # 漢数字（先読みで助詞境界まで）
        if c in _KAN_DIGIT or c in _KAN_UNIT:
            j = i
            while j < n and (src[j] in _KAN_DIGIT or src[j] in _KAN_UNIT):
                j += 1
            # 漢数字の直後が識別子文字でない or 助詞 のとき、数値として扱う
            ok = (j == n) or (not _IDENT_CHAR.match(src[j])) or _starts_with_kw_or_particle(src, j)
            if ok:
                val = _kan2int(src[i:j])
                if val is not None:
                    emit("NUM", val)
                    i = j
                    continue

        # 多文字記号（正規化後の文字を見て判定）
        matched_sym = None
        # まず2文字記号（≠ ≦ ≧）と長い記号を優先
        for sym in ["==", "!=", "<=", ">=", "≠", "≦", "≧"]:
            if src.startswith(sym, i):
                matched_sym = {"≠":"!=","≦":"<=","≧":">="}.get(sym, sym)
                i += len(sym)
                break
        if matched_sym:
            emit("SYM", matched_sym); continue
        # 「→」（辞書リテラル用）
        if c == "→":
            emit("SYM", "→")
            i += 1
            continue

        # 1文字記号（全角・半角両方を見る）
        if nc in "+-*/%=()[]{}:,.<>":
            emit("SYM", nc)
            i += 1
            continue

        # 助詞を含む組み込み関数名（「文字列にする」など）は分割せず1識別子にする。
        # 直後が識別子文字なら別の名前なので対象外（「整数にする2」など）。
        composite = None
        for cname in _composite_builtin_names():
            if src.startswith(cname, i):
                j = i + len(cname)
                if j >= n or not _IDENT_CHAR.match(src[j]):
                    composite = cname
                    break
        if composite:
            emit("IDENT", composite)
            i += len(composite)
            continue

        # 助詞・キーワードの最長マッチを試す
        kp = _match_kw_or_particle(src, i)
        if kp:
            kind = "KW" if kp in KEYWORDS else "PARTICLE"
            emit(kind, kp)
            i += len(kp)
            continue

        # 識別子（次が助詞/KW/記号に当たるまで読む）
        if _IDENT_START.match(c):
            j = i + 1
            while j < n:
                if not _IDENT_CHAR.match(src[j]):
                    break
                # 次の位置が助詞/KWで始まるなら識別子はそこで終了
                if _match_kw_or_particle(src, j):
                    break
                j += 1
            emit("IDENT", src[i:j])
            i = j
            continue

        raise LexError(f"{line}行目：解釈できない文字「{c}」(U+{ord(c):04X})")

    if tokens and tokens[-1].kind != "NEWLINE":
        emit("NEWLINE", "\n")
    emit("EOF", None)
    return tokens


def _match_kw_or_particle(src: str, i: int) -> Optional[str]:
    for w in _KW_OR_PARTICLE_SORTED:
        if src.startswith(w, i):
            return w
    return None

def _starts_with_kw_or_particle(src: str, i: int) -> bool:
    return _match_kw_or_particle(src, i) is not None


_COMPOSITE_BUILTINS: Optional[list[str]] = None

def _composite_builtin_names() -> list[str]:
    """助詞を含む組み込み関数名の一覧を長い順で返す。

    「文字列にする」のような名前は助詞「に」の位置で識別子が切れてしまい、
    そのままでは呼び出せない（「文字列」「に」「する」の3トークンになる）。
    字句解析の時点でこれらを1つの識別子として切り出すことで、通常の呼び出し・
    「の」後置記法・高階関数への文字列渡しのすべてで到達できるようにする。

    一覧は _BUILTINS から導出するので、あとから助詞入りの組み込みが増えても
    自動で追随する。tokenize から呼ばれる時点では _BUILTINS は定義済み。
    """
    global _COMPOSITE_BUILTINS
    if _COMPOSITE_BUILTINS is None:
        names = [
            name for name in _BUILTINS
            if any(_match_kw_or_particle(name, k) for k in range(1, len(name)))
        ]
        _COMPOSITE_BUILTINS = sorted(names, key=len, reverse=True)
    return _COMPOSITE_BUILTINS


# =============================================================================
# 2. 抽象構文木（AST）
# =============================================================================

class Node: pass

@dataclass
class NumLit(Node): value: Any
@dataclass
class StrLit(Node):
    value: str
    is_cooked: bool = False  # True なら {式} 補間を行う
@dataclass
class BoolLit(Node): value: bool
@dataclass
class NoneLit(Node): pass
@dataclass
class Ident(Node): name: str
@dataclass
class ListLit(Node): items: list
@dataclass
class DictLit(Node): pairs: list  # [(key_node, value_node), ...]
@dataclass
class Break(Node): pass
@dataclass
class Continue(Node): pass
@dataclass
class RaceDef(Node):
    name: str
    attrs: list  # 属性名のリスト
@dataclass
class NewInstance(Node):
    race_name: str
    fields: dict  # {属性名: 式ノード}
@dataclass
class TryCatch(Node):
    try_body: list
    catch_body: list
@dataclass
class Lambda(Node):
    params: list  # [(name, particle)]
    body: Node    # 戻り値となる式
@dataclass
class BinOp(Node):
    op: str; left: Node; right: Node
@dataclass
class UnaryOp(Node):
    op: str; operand: Node
@dataclass
class Call(Node):
    """関数呼び出し：助詞ベース。args は {助詞: 式} の辞書、verb は動詞句。"""
    verb: str
    args: dict[str, Node]
    is_command: bool = False  # 〜せよ
@dataclass
class Assign(Node):
    name: str; value: Node; is_const: bool = False
@dataclass
class If(Node):
    cond: Node; then_body: list; else_body: list
@dataclass
class While(Node):
    cond: Node; body: list
@dataclass
class ForRange(Node):
    var: str; start: Node; end: Node; body: list
@dataclass
class ForEach(Node):
    var: str; iterable: Node; body: list
@dataclass
class FuncDef(Node):
    verb: str
    params: list  # [(name, particle)]
    body: list
@dataclass
class Return(Node):
    value: Optional[Node]
@dataclass
class TopicBlock(Node):
    """主題ブロック：<ident>について／おわり"""
    topic: Node
    body: list
@dataclass
class ExprStmt(Node):
    expr: Node
@dataclass
class Program(Node):
    body: list


# =============================================================================
# 3. 構文解析（Parser）
# =============================================================================

class ParseError(Exception): pass

class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    # ── 基本ユーティリティ ─────────────────────────────────────
    def peek(self, offset: int = 0) -> Token:
        return self.tokens[self.pos + offset]

    def advance(self) -> Token:
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    def check(self, kind: str, value: Any = None) -> bool:
        t = self.peek()
        if t.kind != kind: return False
        if value is not None and t.value != value: return False
        return True

    def match(self, kind: str, value: Any = None) -> Optional[Token]:
        if self.check(kind, value):
            return self.advance()
        return None

    def expect(self, kind: str, value: Any = None) -> Token:
        t = self.peek()
        if not self.check(kind, value):
            raise ParseError(f"{t.line}行目：期待 {kind}({value}) 実際 {t.kind}({t.value!r})")
        return self.advance()

    def skip_newlines(self):
        while self.check("NEWLINE"):
            self.advance()

    # ── プログラム ─────────────────────────────────────────────
    def parse_program(self) -> Program:
        body = []
        self.skip_newlines()
        while not self.check("EOF"):
            stmt = self.parse_statement()
            if stmt is not None:
                body.append(stmt)
            self.skip_newlines()
        return Program(body)

    # ── 文 ────────────────────────────────────────────────────
    def parse_statement(self) -> Optional[Node]:
        # ブロック構造を最初に判定
        if self.check("KW", "もし"):
            return self.parse_if()
        if self.check("KW", "各"):
            return self.parse_for()
        if self.check("KW", "関数") and self.peek(1).kind == "SYM" and self.peek(1).value == ":":
            return self.parse_func_def()
        if self.check("KW", "戻り値"):
            return self.parse_return_value()
        if self.check("KW", "戻る"):
            self.advance()
            return Return(None)
        if self.check("KW", "やめる"):
            self.advance()
            return Break()
        if self.check("KW", "次へ"):
            self.advance()
            return Continue()
        if self.check("KW", "種族"):
            return self.parse_race_def()
        if self.check("KW", "試す"):
            return self.parse_try()

        # 行をいったん収集して、文末ムードで判定
        line_tokens = self._collect_line()
        return self._parse_line(line_tokens)

    def _collect_line(self) -> list[Token]:
        """次の改行までトークンを収集（カッコ内の改行は無視）。"""
        toks = []
        depth = 0
        while not self.check("EOF"):
            t = self.peek()
            if t.kind == "NEWLINE" and depth == 0:
                self.advance()
                break
            if t.kind == "SYM" and t.value in "([{":
                depth += 1
            elif t.kind == "SYM" and t.value in ")]}":
                depth -= 1
            toks.append(self.advance())
        return toks

    def _parse_line(self, toks: list[Token]) -> Optional[Node]:
        if not toks:
            return None

        # 「のあいだ繰り返す」を末尾に含む？
        if len(toks) >= 2 and toks[-1].value == "繰り返す" and toks[-2].value == "のあいだ":
            cond = self._parse_expr_from(toks[:-2])
            body = self._parse_block_until(["おわり"])
            return While(cond, body)

        # 「<id>について」 主題ブロック
        if len(toks) >= 2 and toks[-1].kind == "PARTICLE" and toks[-1].value == "について":
            topic = self._parse_expr_from(toks[:-1])
            body = self._parse_block_until(["おわり"])
            return TopicBlock(topic, body)

        # 文末ムード判定
        last = toks[-1]
        if last.kind == "KW" and last.value == "とする":
            return self._parse_assign(toks[:-1], const=False)
        if last.kind == "KW" and last.value == "である":
            return self._parse_assign(toks[:-1], const=True)
        if last.kind == "KW" and last.value == "せよ":
            expr = self._parse_call_from(toks[:-1], is_command=True)
            return ExprStmt(expr)
        if last.kind == "KW" and last.value == "だろうか":
            # 単独の述語式文（普通はもしの内側で使う）
            expr = self._parse_predicate_from(toks[:-1])
            return ExprStmt(expr)

        # 純粋な式文
        return ExprStmt(self._parse_expr_from(toks))

    def _parse_assign(self, toks: list[Token], const: bool) -> Assign:
        """<ident> を/は <式> [とする|である] の左辺解析"""
        # 「<ident> を …」または「<ident> は …」の最初の助詞で分割
        if not toks or toks[0].kind != "IDENT":
            raise ParseError(f"代入文の左辺は識別子である必要があります")
        name = toks[0].value
        # 次のトークンが「を」または「は」
        if len(toks) < 3 or toks[1].kind != "PARTICLE" or toks[1].value not in ("を", "は"):
            raise ParseError(f"{toks[0].line}行目：代入は「<名前>を/は <式>」の形")
        rhs = self._parse_expr_from(toks[2:])
        return Assign(name, rhs, is_const=const)

    # ── 制御構文 ──────────────────────────────────────────────
    def parse_if(self) -> If:
        self.expect("KW", "もし")
        # 条件部を「ならば」まで収集
        cond_toks = []
        while not (self.check("KW", "ならば")):
            if self.check("EOF") or self.check("NEWLINE"):
                raise ParseError(f"もし文に「ならば」がありません")
            cond_toks.append(self.advance())
        self.expect("KW", "ならば")
        self.skip_newlines()

        # then節
        then_body = []
        while not (self.check("KW", "そうでなければ") or self.check("KW", "おわり")):
            if self.check("EOF"):
                raise ParseError("もし文に「おわり」がありません")
            stmt = self.parse_statement()
            if stmt is not None:
                then_body.append(stmt)
            self.skip_newlines()

        else_body = []
        if self.match("KW", "そうでなければ"):
            # 「そうでなければ もし …」のチェイン
            if self.check("KW", "もし"):
                else_body = [self.parse_if()]
                # ネストされたifの内側で「おわり」が消費されているので、ここではそれ以上消費しない
                return If(self._parse_predicate_from(cond_toks), then_body, else_body)
            self.skip_newlines()
            while not self.check("KW", "おわり"):
                if self.check("EOF"):
                    raise ParseError("もし文に「おわり」がありません")
                stmt = self.parse_statement()
                if stmt is not None:
                    else_body.append(stmt)
                self.skip_newlines()

        self.expect("KW", "おわり")
        return If(self._parse_predicate_from(cond_toks), then_body, else_body)

    def parse_for(self) -> Node:
        """各 <id> を <range>から<range>まで 繰り返す
           各 <id> を <expr> について 繰り返す"""
        self.expect("KW", "各")
        var_tok = self.expect("IDENT")
        self.expect("PARTICLE", "を")
        # 「繰り返す」までトークンを収集
        body_toks = []
        while not self.check("KW", "繰り返す"):
            if self.check("EOF") or self.check("NEWLINE"):
                raise ParseError("各文に「繰り返す」がありません")
            body_toks.append(self.advance())
        self.expect("KW", "繰り返す")

        # 末尾が「について」なら ForEach、そうでなければ「Aから Bまで」
        if body_toks and body_toks[-1].kind == "PARTICLE" and body_toks[-1].value == "について":
            iterable = self._parse_expr_from(body_toks[:-1])
            block = self._parse_block_until(["おわり"])
            return ForEach(var_tok.value, iterable, block)

        # から〜までを探す
        kara_idx = mada_idx = -1
        for i, t in enumerate(body_toks):
            if t.kind == "PARTICLE" and t.value == "から":
                kara_idx = i
            elif t.kind == "PARTICLE" and t.value == "まで":
                mada_idx = i
        if kara_idx == -1 or mada_idx == -1 or mada_idx <= kara_idx:
            raise ParseError("各文は「<開始>から<終了>まで」または「<配列>について」の形")
        start = self._parse_expr_from(body_toks[:kara_idx])
        end   = self._parse_expr_from(body_toks[kara_idx+1:mada_idx])
        block = self._parse_block_until(["おわり"])
        return ForRange(var_tok.value, start, end, block)

    def parse_func_def(self) -> FuncDef:
        """関数：[A]を[B]に足す
              文...
              戻り値：式
           おわり"""
        self.expect("KW", "関数")
        self.expect("SYM", ":")
        # シグネチャ行を改行まで収集
        sig_toks = []
        while not self.check("NEWLINE") and not self.check("EOF"):
            sig_toks.append(self.advance())
        self.expect("NEWLINE")
        # シグネチャ解析: ([名前]助詞)+ 動詞
        params = []
        i = 0
        verb_parts = []
        while i < len(sig_toks):
            t = sig_toks[i]
            if t.kind == "SYM" and t.value == "[":
                # [名前]助詞
                if i+2 >= len(sig_toks):
                    raise ParseError("関数シグネチャ：[]助詞の形が壊れています")
                name_tok = sig_toks[i+1]
                if sig_toks[i+2].kind != "SYM" or sig_toks[i+2].value != "]":
                    raise ParseError("関数シグネチャ：]がありません")
                particle_tok = sig_toks[i+3] if i+3 < len(sig_toks) else None
                if particle_tok is None or particle_tok.kind != "PARTICLE":
                    raise ParseError("関数シグネチャ：仮引数の後に助詞が必要")
                params.append((name_tok.value, particle_tok.value))
                i += 4
            else:
                # 動詞句
                if t.kind in ("IDENT", "KW"):
                    verb_parts.append(t.value)
                i += 1
        verb = "".join(verb_parts)
        body = self._parse_block_until(["おわり"])
        return FuncDef(verb, params, body)

    def parse_return_value(self) -> Return:
        self.expect("KW", "戻り値")
        self.expect("SYM", ":")
        toks = self._collect_line()
        return Return(self._parse_expr_from(toks))

    def parse_try(self) -> TryCatch:
        """試す
               <文>...
           ならば失敗
               <文>...   ※ 失敗値 で失敗メッセージ参照
           おわり
        """
        self.expect("KW", "試す")
        self.skip_newlines()
        try_body: list = []
        while not self.check("KW", "ならば失敗"):
            if self.check("EOF"):
                raise ParseError("試す文に「ならば失敗」がありません")
            s = self.parse_statement()
            if s is not None:
                try_body.append(s)
            self.skip_newlines()
        self.expect("KW", "ならば失敗")
        self.skip_newlines()
        catch_body: list = []
        while not self.check("KW", "おわり"):
            if self.check("EOF"):
                raise ParseError("試す文に「おわり」がありません")
            s = self.parse_statement()
            if s is not None:
                catch_body.append(s)
            self.skip_newlines()
        self.advance()  # おわり
        return TryCatch(try_body, catch_body)

    def parse_race_def(self) -> RaceDef:
        """種族 <名前>：
               属性：<a>, <b>, ...
               属性：<c>           ※ 複数行可
           おわり
        """
        self.expect("KW", "種族")
        name_tok = self.expect("IDENT")
        self.expect("SYM", ":")
        self.skip_newlines()
        attrs: list = []
        while not self.check("KW", "おわり"):
            if self.check("EOF"):
                raise ParseError("種族定義に「おわり」がありません")
            if self.check("KW", "属性"):
                self.advance()
                self.expect("SYM", ":")
                attrs.append(self.expect("IDENT").value)
                while self.match("SYM", ","):
                    attrs.append(self.expect("IDENT").value)
                self.skip_newlines()
            else:
                raise ParseError(f"{self.peek().line}行目：種族定義の中で「属性：」が期待されますが「{self.peek().value}」が見つかりました")
        self.advance()  # おわり
        return RaceDef(name_tok.value, attrs)

    def _parse_block_until(self, terminators: list[str]) -> list[Node]:
        body = []
        self.skip_newlines()
        while not any(self.check("KW", t) for t in terminators):
            if self.check("EOF"):
                raise ParseError(f"ブロックの終端 {terminators} が見つかりません")
            stmt = self.parse_statement()
            if stmt is not None:
                body.append(stmt)
            self.skip_newlines()
        # 終端を消費
        self.advance()
        return body

    # ── 式 ────────────────────────────────────────────────────
    def _parse_predicate_from(self, toks: list[Token]) -> Node:
        """述語式（〜だろうか の中身、もしの条件）。
        パターン：
        - 「Aが Bと等しい」「AがBより大きい」「Aが正」など
        - 「A == B」「A < B」など標準演算子
        を許容する。
        """
        return self._parse_expr_from(toks)

    def _parse_expr_from(self, toks: list[Token]) -> Node:
        sub = Parser(toks + [Token("NEWLINE","\n",0), Token("EOF",None,0)])
        node = sub._parse_expr()
        # 残りトークンが少しあれば呼び出しの可能性
        if not (sub.check("NEWLINE") or sub.check("EOF")):
            # 残りが助詞列＋動詞 の関数呼び出しパターン → やり直し
            sub2 = Parser(toks + [Token("NEWLINE","\n",0), Token("EOF",None,0)])
            return sub2._parse_call_or_expr()
        return node

    def _parse_call_from(self, toks: list[Token], is_command: bool=False) -> Node:
        sub = Parser(toks + [Token("NEWLINE","\n",0), Token("EOF",None,0)])
        node = sub._parse_call_or_expr()
        if isinstance(node, Call):
            node.is_command = is_command
        return node

    def _parse_call_or_expr(self) -> Node:
        """呼び出しまたは式。トークンを (項 助詞)+ 動詞 に分解できれば呼び出しとして扱う。"""
        # まず「項 助詞」の列を貪欲に収集
        args: dict[str, Node] = {}
        verb_parts: list[str] = []
        saved_pos = self.pos
        # スキャン用：助詞で区切られた区間を順に項として解釈
        pieces = self._scan_pieces()
        if pieces is None:
            # ふつうの式
            self.pos = saved_pos
            return self._parse_expr()

        seg_toks, particles, tail = pieces
        if particles and tail:
            for s, p in zip(seg_toks, particles):
                node = self._parse_expr_from(s)
                args[p] = node
            verb = "".join([t.value for t in tail])
            return Call(verb=verb, args=args, is_command=False)
        # 助詞がなければ式評価
        self.pos = saved_pos
        return self._parse_expr()

    def _scan_pieces(self):
        """残りのトークンを「項助詞 ... 動詞」のリストに分解する。
        失敗したら None。"""
        seg: list[list[Token]] = [[]]
        particles: list[str] = []
        tail: list[Token] = []
        depth = 0
        in_tail = False
        toks = []
        while not (self.check("NEWLINE") or self.check("EOF")):
            toks.append(self.advance())
        # スキャン
        for t in toks:
            if t.kind == "SYM" and t.value in "([{":
                depth += 1
                seg[-1].append(t) if not in_tail else tail.append(t)
                continue
            if t.kind == "SYM" and t.value in ")]}":
                depth -= 1
                seg[-1].append(t) if not in_tail else tail.append(t)
                continue
            # 「の」「は」は scan_pieces では区切らない（前者は postfix、後者は代入文と衝突）
            if not in_tail and depth == 0 and t.kind == "PARTICLE" and t.value in ("を","に","で","へ","と","から","まで","より","が"):
                particles.append(t.value)
                seg.append([])
                continue
            if not in_tail:
                seg[-1].append(t)
            else:
                tail.append(t)
        # 最後のセグメントを動詞句にする
        if not particles:
            return None
        # seg[-1] が動詞句、seg[:-1] が引数たち
        tail = seg[-1]
        seg = seg[:-1]
        # 助詞の数 == セグメント数（先頭セグメント含む）
        if len(seg) != len(particles):
            return None
        # 動詞句は IDENT/KW のみで構成されているはず
        if not tail or any(t.kind not in ("IDENT","KW") for t in tail):
            return None
        # 末尾が比較語なら呼び出しではなく式として扱う（自然語比較）
        if len(tail) == 1 and tail[0].kind == "KW" and tail[0].value in (
            "大きい","小さい","以上","以下","未満","等しい","等しくない"
        ):
            return None
        return seg, particles, tail

    # ── 演算子優先度法による式パーサ ───────────────────────────
    def _parse_expr(self) -> Node:
        return self._parse_or()

    def _parse_or(self) -> Node:
        left = self._parse_and()
        while self.check("KW", "または"):
            self.advance()
            right = self._parse_and()
            left = BinOp("or", left, right)
        return left

    def _parse_and(self) -> Node:
        left = self._parse_not()
        while self.check("KW", "かつ"):
            self.advance()
            right = self._parse_not()
            left = BinOp("and", left, right)
        return left

    def _parse_not(self) -> Node:
        if self.match("KW", "でない"):
            return UnaryOp("not", self._parse_not())
        return self._parse_compare()

    def _parse_compare(self) -> Node:
        left = self._parse_add()

        # 「が」マーカー：比較式として試行、失敗したら巻き戻す（呼び出しとの曖昧性を許容）
        if self.peek().kind == "PARTICLE" and self.peek().value == "が":
            save = self.pos
            try:
                self.advance()  # が
                right = self._parse_add()
                if self.match("PARTICLE", "より"):
                    if self.match("KW","大きい"): return BinOp(">",  left, right)
                    if self.match("KW","小さい"): return BinOp("<",  left, right)
                    if self.match("KW","以上"):   return BinOp(">=", left, right)
                    if self.match("KW","以下"):   return BinOp("<=", left, right)
                    if self.match("KW","未満"):   return BinOp("<",  left, right)
                    raise ParseError("「より」の後に比較語が必要")
                if self.match("PARTICLE", "と"):
                    if self.match("KW","等しい"):     return BinOp("==", left, right)
                    if self.match("KW","等しくない"): return BinOp("!=", left, right)
                    raise ParseError("「と」の後に比較語が必要")
                if self.match("KW","以上"): return BinOp(">=", left, right)
                if self.match("KW","以下"): return BinOp("<=", left, right)
                if self.match("KW","未満"): return BinOp("<",  left, right)
                if self.peek().kind == "SYM" and self.peek().value in ("==","!=","<",">","<=",">="):
                    op = self.advance().value
                    right2 = self._parse_add()
                    return BinOp(op, right, right2)
                raise ParseError("「が」の後に比較形式が必要")
            except ParseError:
                self.pos = save
                # 「が」消費せず、leftをそのまま返す → 上位で関数呼び出しとして再解釈される

        # 「が」なしの場合：標準演算子
        if self.peek().kind == "SYM" and self.peek().value in ("==","!=","<",">","<=",">="):
            op = self.advance().value
            right = self._parse_add()
            return BinOp(op, left, right)

        # 「より～」「と～」を直接続ける記法（バックトラック付き）
        if self.peek().kind == "PARTICLE" and self.peek().value == "より":
            save = self.pos
            self.advance()
            right = self._parse_add()
            if self.match("KW","大きい"): return BinOp(">",  left, right)
            if self.match("KW","小さい"): return BinOp("<",  left, right)
            if self.match("KW","以上"):   return BinOp(">=", left, right)
            if self.match("KW","以下"):   return BinOp("<=", left, right)
            if self.match("KW","未満"):   return BinOp("<",  left, right)
            self.pos = save

        if self.peek().kind == "PARTICLE" and self.peek().value == "と":
            save = self.pos
            self.advance()
            right = self._parse_add()
            if self.match("KW","等しい"):     return BinOp("==", left, right)
            if self.match("KW","等しくない"): return BinOp("!=", left, right)
            self.pos = save

        return left

    def _parse_add(self) -> Node:
        left = self._parse_mul()
        while self.peek().kind == "SYM" and self.peek().value in ("+", "-"):
            op = self.advance().value
            right = self._parse_mul()
            left = BinOp(op, left, right)
        return left

    def _parse_mul(self) -> Node:
        left = self._parse_unary()
        while self.peek().kind == "SYM" and self.peek().value in ("*", "/", "%"):
            op = self.advance().value
            right = self._parse_unary()
            left = BinOp(op, left, right)
        return left

    def _parse_unary(self) -> Node:
        if self.peek().kind == "SYM" and self.peek().value == "-":
            self.advance()
            return UnaryOp("neg", self._parse_unary())
        return self._parse_postfix()

    def _parse_lambda(self) -> Lambda:
        """関数（[X]を [Y]に） <式>"""
        self.expect("KW", "関数")
        self.expect("SYM", "(")
        params = []
        while not self.check("SYM", ")"):
            self.expect("SYM", "[")
            name = self.expect("IDENT").value
            self.expect("SYM", "]")
            ptok = self.peek()
            if ptok.kind != "PARTICLE":
                raise ParseError(f"{ptok.line}行目：ラムダ仮引数の後に助詞が必要")
            self.advance()
            params.append((name, ptok.value))
        self.expect("SYM", ")")
        body = self._parse_expr()
        return Lambda(params, body)

    def _parse_new_instance(self) -> NewInstance:
        """新しい <種族名>(属性 → 値, ...)"""
        self.expect("KW", "新しい")
        race = self.expect("IDENT").value
        self.expect("SYM", "(")
        self.skip_newlines()
        fields: dict = {}
        if not self.check("SYM", ")"):
            while True:
                self.skip_newlines()
                key = self.expect("IDENT").value
                self.expect("SYM", "→")
                val = self._parse_expr()
                fields[key] = val
                self.skip_newlines()
                if not self.match("SYM", ","):
                    break
                self.skip_newlines()
        self.skip_newlines()
        self.expect("SYM", ")")
        return NewInstance(race, fields)

    def _parse_postfix(self) -> Node:
        """原子式の後置：
        - <expr> の <ident>  → Call(verb=ident, {の: expr}) （連鎖可）
        - <expr> でない       → UnaryOp("not", expr)
        - <expr> [ <idx> ]    → 配列インデックス（番目取り出すの糖衣、1始まり）
        """
        node = self._parse_atom()
        while True:
            if self.peek().kind == "PARTICLE" and self.peek().value == "の" and self.peek(1).kind == "IDENT":
                self.advance()  # の
                verb_tok = self.advance()
                node = Call(verb=verb_tok.value, args={"の": node}, is_command=False)
                continue
            if self.peek().kind == "KW" and self.peek().value == "でない":
                self.advance()
                node = UnaryOp("not", node)
                continue
            if self.peek().kind == "SYM" and self.peek().value == "[":
                self.advance()
                idx = self._parse_expr()
                self.expect("SYM", "]")
                node = Call(verb="番目取り出す", args={"から": node, "を": idx}, is_command=False)
                continue
            break
        return node

    def _parse_atom(self) -> Node:
        t = self.peek()
        if t.kind == "NUM":
            self.advance(); return NumLit(t.value)
        if t.kind == "STR_RAW":
            self.advance(); return StrLit(t.value, is_cooked=False)
        if t.kind == "STR_COOKED":
            self.advance(); return StrLit(t.value, is_cooked=True)
        if t.kind == "KW" and t.value == "真":
            self.advance(); return BoolLit(True)
        if t.kind == "KW" and t.value == "偽":
            self.advance(); return BoolLit(False)
        if t.kind == "KW" and t.value == "無":
            self.advance(); return NoneLit()
        if t.kind == "KW" and t.value == "新しい":
            return self._parse_new_instance()
        if t.kind == "KW" and t.value == "関数":
            return self._parse_lambda()
        if t.kind == "SYM" and t.value == "(":
            self.advance()
            self.skip_newlines()
            inner_toks = []
            depth = 1
            while depth > 0:
                tt = self.peek()
                if tt.kind == "EOF":
                    raise ParseError("カッコが閉じていません")
                if tt.kind == "SYM" and tt.value == "(":
                    depth += 1
                elif tt.kind == "SYM" and tt.value == ")":
                    depth -= 1
                    if depth == 0:
                        self.advance()
                        break
                inner_toks.append(self.advance())
            return self._parse_call_from(inner_toks)
        if t.kind == "SYM" and t.value == "[":
            self.advance()
            items = []
            self.skip_newlines()
            if not self.check("SYM", "]"):
                items.append(self._parse_expr())
                self.skip_newlines()
                while self.match("SYM", ","):
                    self.skip_newlines()
                    items.append(self._parse_expr())
                    self.skip_newlines()
            self.skip_newlines()
            self.expect("SYM", "]")
            return ListLit(items)
        if t.kind == "SYM" and t.value == "{":
            self.advance()
            pairs = []
            self.skip_newlines()
            if not self.check("SYM", "}"):
                while True:
                    self.skip_newlines()
                    k = self._parse_expr()
                    self.expect("SYM", "→")
                    v = self._parse_expr()
                    pairs.append((k, v))
                    self.skip_newlines()
                    if not self.match("SYM", ","):
                        break
                    self.skip_newlines()
            self.skip_newlines()
            self.expect("SYM", "}")
            return DictLit(pairs)
        if t.kind == "IDENT":
            self.advance()
            return Ident(t.value)
        raise ParseError(f"{t.line}行目：式の解釈に失敗（{t.kind}:{t.value!r}）")


# =============================================================================
# 4. 評価器（Evaluator）
# =============================================================================

class RuntimeYuiError(Exception): pass


def yui_type_name(v: Any) -> str:
    """値の型を Yui の用語で返す。エラーメッセージ用。"""
    if v is None: return "無"
    if isinstance(v, bool): return "真偽"
    if isinstance(v, int): return "整数"
    if isinstance(v, float): return "小数"
    if isinstance(v, str): return "文字列"
    if isinstance(v, list): return "配列"
    if isinstance(v, dict): return "辞書"
    return type(v).__name__


def _is_num(v: Any) -> bool:
    """整数または小数か。真偽値は数値として扱わない（SPEC 4 で独立した型）。"""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _binop_error(op: str, l: Any, r: Any) -> "RuntimeYuiError":
    return RuntimeYuiError(
        f"「{op}」は {yui_type_name(l)} と {yui_type_name(r)} には使えません"
    )


# ── 二項演算子の型規則（SPEC 3.6 に対応）─────────────────────
#
#   +           数値＋数値／文字列＋文字列／配列＋配列
#   - / %       数値どうしのみ
#   *           数値どうし、または 文字列×整数・配列×整数（繰り返し）
#   < > <= >=   数値どうし、または 文字列どうし
#   == !=       型を問わない（型が違えば不一致）
#
# 真偽値は算術・大小比較のいずれにも使えない。Python では bool が int の
# 派生なので「真 + 1」が 2 になってしまうが、SPEC 4 は 真偽 を整数とは別の
# 型として宣言しているため、宣言に合わせて明示的に弾く。

def _add(l: Any, r: Any) -> Any:
    if _is_num(l) and _is_num(r): return l + r
    if isinstance(l, str) and isinstance(r, str): return l + r
    if isinstance(l, list) and isinstance(r, list): return l + r
    raise _binop_error("+", l, r)


def _sub(l: Any, r: Any) -> Any:
    if _is_num(l) and _is_num(r): return l - r
    raise _binop_error("-", l, r)


def _mul(l: Any, r: Any) -> Any:
    if _is_num(l) and _is_num(r): return l * r
    # 文字列・配列の繰り返し。回数は整数のみ（小数回は意味を持たない）。
    if isinstance(l, (str, list)) and isinstance(r, int) and not isinstance(r, bool):
        return l * r
    if isinstance(r, (str, list)) and isinstance(l, int) and not isinstance(l, bool):
        return r * l
    raise _binop_error("*", l, r)


def _div(l: Any, r: Any) -> Any:
    """整数どうしで割り切れる場合だけ整数を返す。それ以外は小数。"""
    if not (_is_num(l) and _is_num(r)): raise _binop_error("/", l, r)
    if r == 0: raise RuntimeYuiError("0で割ることはできません")
    if isinstance(l, int) and isinstance(r, int) and l % r == 0:
        return l // r
    return l / r


def _mod(l: Any, r: Any) -> Any:
    if not (_is_num(l) and _is_num(r)): raise _binop_error("%", l, r)
    if r == 0: raise RuntimeYuiError("0で割ることはできません")
    return l % r


def _cmp(op: str, fn: Callable[[Any, Any], bool]) -> Callable[[Any, Any], bool]:
    def run(l: Any, r: Any) -> bool:
        if (_is_num(l) and _is_num(r)) or (isinstance(l, str) and isinstance(r, str)):
            return fn(l, r)
        raise _binop_error(op, l, r)
    return run


_BINOPS = {
    "+":  _add,
    "-":  _sub,
    "*":  _mul,
    "/":  _div,
    "%":  _mod,
    "==": lambda l, r: l == r,
    "!=": lambda l, r: l != r,
    "<":  _cmp("<",  lambda l, r: l < r),
    ">":  _cmp(">",  lambda l, r: l > r),
    "<=": _cmp("<=", lambda l, r: l <= r),
    ">=": _cmp(">=", lambda l, r: l >= r),
}
class ReturnSignal(Exception):
    def __init__(self, value): self.value = value
class BreakSignal(Exception): pass
class ContinueSignal(Exception): pass


def _invoke_builtin(name: str, args: dict, env: "Environment") -> Any:
    """組み込み関数を呼ぶ唯一の入口。

    組み込みは Python の str / list / math などをそのまま使っているため、
    想定外の型を渡されると TypeError や AttributeError がそのまま利用者まで
    抜けてしまう。個々の組み込みに型検査を書き足すと 60 箇所へ同じコードを
    複製することになり、必ず抜けが出る。ここ 1 箇所で受け止める。

    制御フロー用のシグナルと Yui 自身のエラーはそのまま通す。
    """
    try:
        return _BUILTINS[name](args, env)
    except (ReturnSignal, BreakSignal, ContinueSignal):
        raise
    except (RuntimeYuiError, LexError, ParseError):
        raise
    except RecursionError:
        raise RuntimeYuiError("再帰が深すぎます") from None
    except Exception as e:
        got = "／".join(f"{p}：{yui_type_name(v)}" for p, v in args.items()) or "引数なし"
        raise RuntimeYuiError(
            f"「{name}」は与えられた引数では実行できません（{got}）"
        ) from None


def _interpolate(text: str, env: "Environment") -> str:
    """文字列補間：{式} を評価して埋め込む。\x01/\x02 はエスケープされた { }。"""
    out = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "{":
            j = text.find("}", i)
            if j == -1:
                raise RuntimeYuiError("文字列補間：}が閉じていません")
            expr_src = text[i+1:j]
            try:
                # 補間式は _parse_expr_from と同じ「式優先・余ったら呼び出し」順で
                # 解釈する。_parse_call_or_expr を直に呼ぶと、比較の右辺が識別子の
                # とき（『{x が B 以下}』）動詞句が「B以下」になってしまう。
                toks = [t for t in tokenize(expr_src)
                        if t.kind not in ("NEWLINE", "EOF")]
                tree = Parser(list(toks))._parse_expr_from(toks)
            except (LexError, ParseError) as e:
                raise RuntimeYuiError(f"補間式「{expr_src}」の解析失敗：{e}")
            val = Evaluator.eval_node(tree, env)
            out.append(yui_to_str(val))
            i = j + 1
        elif c == "\x01":
            out.append("{"); i += 1
        elif c == "\x02":
            out.append("}"); i += 1
        else:
            out.append(c); i += 1
    return "".join(out)

class Environment:
    def __init__(self, parent: Optional["Environment"] = None):
        self.vars: dict[str, Any] = {}
        self.consts: set[str] = set()
        self.parent = parent
        self.topic: Any = None  # 主題（〜について の対象）

    def get(self, name: str) -> Any:
        if name in self.vars:
            return self.vars[name]
        if self.parent:
            return self.parent.get(name)
        raise RuntimeYuiError(f"未定義の名前：{name}")

    def has(self, name: str) -> bool:
        if name in self.vars: return True
        if self.parent: return self.parent.has(name)
        return False

    def set(self, name: str, value: Any, const: bool = False):
        if const:
            if self.has(name):
                raise RuntimeYuiError(f"「{name}」は既に定義されています")
            self.vars[name] = value
            self.consts.add(name)
            return
        # 既存スコープに同名があれば上書き、なければ現在スコープに新設
        env = self
        while env:
            if name in env.vars:
                if name in env.consts:
                    raise RuntimeYuiError(f"「{name}」は不変宣言（〜である）のため再代入できません")
                env.vars[name] = value
                return
            env = env.parent
        self.vars[name] = value

    def get_topic(self) -> Any:
        env = self
        while env:
            if env.topic is not None:
                return env.topic
            env = env.parent
        return None


class Race:
    """種族：属性スキーマを持つ型タグ。インスタンス化されると辞書になる。"""
    def __init__(self, name: str, attrs: list):
        self.name = name
        self.attrs = attrs
    def __repr__(self):
        return f"<種族 {self.name}: {', '.join(self.attrs)}>"

class Function:
    def __init__(self, name: str, params: list, body: list, env: Environment):
        self.name = name
        self.params = params  # [(name, particle)]
        self.body = body
        self.env = env  # 定義時の環境（クロージャ）

    def call(self, args: dict[str, Any]) -> Any:
        local = Environment(self.env)
        for (pname, particle) in self.params:
            if particle not in args:
                raise RuntimeYuiError(f"関数「{self.name}」の引数「{pname}（{particle}）」が不足")
            local.set(pname, args[particle])
        try:
            for stmt in self.body:
                Evaluator.eval_node(stmt, local)
        except ReturnSignal as r:
            return r.value
        return None


def yui_to_str(v: Any) -> str:
    if v is None:
        return "無"
    if isinstance(v, bool):
        return "真" if v else "偽"
    if isinstance(v, list):
        return "［" + ", ".join(yui_to_str(x) for x in v) + "］"
    return str(v)


class Evaluator:
    # 関数テーブル: 動詞 → Function or builtin
    @staticmethod
    def make_global_env(load_stdlib: bool = True) -> Environment:
        env = Environment()
        env.vars["__builtins__"] = _BUILTINS
        # 数学定数
        env.vars["円周率"] = math.pi
        env.vars["ネイピア数"] = math.e
        env.consts.add("円周率")
        env.consts.add("ネイピア数")
        # stdlib.yui を自動ロード
        if load_stdlib:
            import os as _os
            stdlib_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "stdlib.yui")
            if _os.path.exists(stdlib_path):
                with open(stdlib_path, encoding="utf-8") as f:
                    stdlib_src = f.read()
                try:
                    tokens = tokenize(stdlib_src)
                    prog = Parser(tokens).parse_program()
                    Evaluator.eval_program(prog, env)
                except Exception as e:
                    print(f"警告：stdlib.yuiの読み込みに失敗：{e}", file=sys.stderr)
        return env

    @staticmethod
    def eval_program(prog: Program, env: Environment):
        for stmt in prog.body:
            Evaluator.eval_node(stmt, env)

    @staticmethod
    def eval_node(node: Node, env: Environment) -> Any:
        if isinstance(node, NumLit): return node.value
        if isinstance(node, StrLit):
            if node.is_cooked and ("{" in node.value or "\x01" in node.value):
                return _interpolate(node.value, env)
            # \x01/\x02 はエスケープした { } の内部表現
            return node.value.replace("\x01","{").replace("\x02","}")
        if isinstance(node, BoolLit): return node.value
        if isinstance(node, NoneLit): return None
        if isinstance(node, ListLit):
            return [Evaluator.eval_node(x, env) for x in node.items]
        if isinstance(node, DictLit):
            d = {}
            for k, v in node.pairs:
                kv = Evaluator.eval_node(k, env)
                vv = Evaluator.eval_node(v, env)
                d[kv] = vv
            return d
        if isinstance(node, Break): raise BreakSignal()
        if isinstance(node, Continue): raise ContinueSignal()

        if isinstance(node, RaceDef):
            env.set(node.name, Race(node.name, node.attrs))
            return None

        if isinstance(node, TryCatch):
            try:
                for s in node.try_body:
                    Evaluator.eval_node(s, env)
            except RuntimeYuiError as e:
                catch_env = Environment(env)
                catch_env.set("失敗値", str(e))
                for s in node.catch_body:
                    Evaluator.eval_node(s, catch_env)
            return None

        if isinstance(node, NewInstance):
            race = env.get(node.race_name)
            if not isinstance(race, Race):
                raise RuntimeYuiError(f"「{node.race_name}」は種族ではありません")
            inst: dict = {}
            evaluated = {k: Evaluator.eval_node(v, env) for k, v in node.fields.items()}
            for attr in race.attrs:
                inst[attr] = evaluated.get(attr, None)
            # 未宣言属性も保持（柔軟性のため）
            for k, v in evaluated.items():
                if k not in inst:
                    inst[k] = v
            inst["__種族__"] = race.name
            return inst
        if isinstance(node, Ident):
            if node.name == "主題":
                t = env.get_topic()
                if t is None:
                    raise RuntimeYuiError("「主題」は〜について ブロックの内側でのみ使えます")
                return t
            if env.has(node.name):
                return env.get(node.name)
            # 組み込み関数を引数なし呼び出しとして試す（主題ブロック内では主題を「を」に渡す）
            if node.name in _BUILTINS:
                args: dict[str, Any] = {}
                topic = env.get_topic()
                if topic is not None:
                    args["を"] = topic
                return _invoke_builtin(node.name, args, env)
            raise RuntimeYuiError(f"未定義の名前：{node.name}")

        if isinstance(node, BinOp):
            l = Evaluator.eval_node(node.left, env)
            r = Evaluator.eval_node(node.right, env)
            op = node.op
            if op == "and": return bool(l) and bool(r)
            if op == "or":  return bool(l) or bool(r)
            if op not in _BINOPS:
                raise RuntimeYuiError(f"未対応の演算子：{op}")
            try:
                return _BINOPS[op](l, r)
            except ZeroDivisionError:
                raise RuntimeYuiError("0で割ることはできません") from None
            except TypeError:
                raise RuntimeYuiError(
                    f"「{op}」は {yui_type_name(l)} と {yui_type_name(r)} には使えません"
                ) from None

        if isinstance(node, UnaryOp):
            v = Evaluator.eval_node(node.operand, env)
            if node.op == "neg":
                if not _is_num(v):
                    raise RuntimeYuiError(f"符号反転は {yui_type_name(v)} には使えません")
                return -v
            if node.op == "not": return not bool(v)

        if isinstance(node, Assign):
            v = Evaluator.eval_node(node.value, env)
            env.set(node.name, v, const=node.is_const)
            return None

        if isinstance(node, If):
            cond = Evaluator.eval_node(node.cond, env)
            body = node.then_body if cond else node.else_body
            for s in body:
                Evaluator.eval_node(s, env)
            return None

        if isinstance(node, While):
            while True:
                c = Evaluator.eval_node(node.cond, env)
                if not c: break
                try:
                    for s in node.body:
                        Evaluator.eval_node(s, env)
                except BreakSignal:
                    break
                except ContinueSignal:
                    continue
            return None

        if isinstance(node, ForRange):
            start = Evaluator.eval_node(node.start, env)
            end = Evaluator.eval_node(node.end, env)
            for i in range(int(start), int(end)+1):
                env.set(node.var, i)
                try:
                    for s in node.body:
                        Evaluator.eval_node(s, env)
                except BreakSignal:
                    return None
                except ContinueSignal:
                    continue
            return None

        if isinstance(node, ForEach):
            seq = Evaluator.eval_node(node.iterable, env)
            for x in seq:
                env.set(node.var, x)
                try:
                    for s in node.body:
                        Evaluator.eval_node(s, env)
                except BreakSignal:
                    return None
                except ContinueSignal:
                    continue
            return None

        if isinstance(node, FuncDef):
            f = Function(node.verb, node.params, node.body, env)
            env.set(node.verb, f, const=False)
            return None

        if isinstance(node, Lambda):
            # 無名関数：式評価で値（Function）を返す。本体は単一式。
            body_stmt = [Return(node.body)]
            return Function("<無名>", node.params, body_stmt, env)

        if isinstance(node, Return):
            v = Evaluator.eval_node(node.value, env) if node.value else None
            raise ReturnSignal(v)

        if isinstance(node, TopicBlock):
            topic_val = Evaluator.eval_node(node.topic, env)
            inner = Environment(env)
            inner.topic = topic_val
            for s in node.body:
                Evaluator.eval_node(s, inner)
            return None

        if isinstance(node, ExprStmt):
            return Evaluator.eval_node(node.expr, env)

        if isinstance(node, Call):
            return Evaluator.eval_call(node, env)

        raise RuntimeYuiError(f"未対応のノード：{type(node).__name__}")

    @staticmethod
    def eval_call(node: Call, env: Environment) -> Any:
        verb = node.verb
        args = {p: Evaluator.eval_node(v, env) for p, v in node.args.items()}
        topic = env.get_topic()

        def _alias_no_to_wo(a: dict) -> dict:
            """「の」を「を」にエイリアス変換。"""
            if "の" in a and "を" not in a:
                a = {**a}
                a["を"] = a.pop("の")
            return a

        # 1. 組み込み関数：「の」→「を」変換、主題の暗黙追加
        if verb in _BUILTINS:
            ba = _alias_no_to_wo(args)
            if topic is not None and "を" not in ba and verb in _TOPIC_VERBS:
                ba["を"] = topic
            return _invoke_builtin(verb, ba, env)

        # 2. ユーザー定義関数：仮引数の助詞に「の」がなければ「を」にエイリアス、あればそのまま
        if env.has(verb):
            f = env.get(verb)
            if isinstance(f, Function):
                param_particles = {p for _, p in f.params}
                ua = args
                if "の" in ua and "の" not in param_particles and "を" in param_particles and "を" not in ua:
                    ua = _alias_no_to_wo(ua)
                return f.call(ua)

        # 3. 辞書アクセス：単一引数で verb がキーとして存在
        if len(args) == 1:
            target = next(iter(args.values()))
            if isinstance(target, dict) and verb in target:
                return target[verb]

        # 4. 主題のメソッド呼び出しとして再試行
        if topic is not None:
            if verb in _TOPIC_METHODS:
                ba = _alias_no_to_wo(args)
                return _TOPIC_METHODS[verb](topic, ba, env)

        raise RuntimeYuiError(f"関数「{verb}」が定義されていません")


# =============================================================================
# 5. 組み込み関数
# =============================================================================

def _bi_print(args, env):
    v = args.get("を")
    if v is None and env.get_topic() is not None:
        v = env.get_topic()
    print(yui_to_str(v))
    return None

def _bi_input(args, env):
    prompt = args.get("を", "")
    return input(yui_to_str(prompt))

def _bi_length(args, env):
    v = args.get("を", env.get_topic())
    if v is None: raise RuntimeYuiError("長さを求める対象がありません")
    return len(v)

def _bi_to_str(args, env):
    return yui_to_str(args.get("を"))

def _bi_to_int(args, env):
    return int(args.get("を"))

def _bi_to_float(args, env):
    return float(args.get("を"))

def _bi_append(args, env):
    """<配列>に X を 追加せよ ／ 主題ブロック内では X を 追加せよ"""
    target = args.get("に", env.get_topic())
    item = args.get("を")
    if target is None:
        raise RuntimeYuiError("追加先がありません")
    if not isinstance(target, list):
        raise RuntimeYuiError("「追加」の追加先は配列です")
    target.append(item)
    return None

def _bi_append_tail(args, env):
    """<配列>へ X を 末尾追加せよ ／ 主題ブロック内では X を 末尾追加せよ"""
    target = args.get("へ")
    if target is None:
        target = env.get_topic()
    if target is None:
        raise RuntimeYuiError("追加先がありません")
    if not isinstance(target, list):
        raise RuntimeYuiError("「末尾追加」の追加先は配列です")
    item = args.get("を")
    target.append(item)
    return None

def _bi_concat(args, env):
    a = args.get("を")
    b = args.get("と")
    return a + b

def _bi_sum(args, env):
    v = args.get("を", env.get_topic())
    return sum(v)

def _bi_max(args, env):
    return max(args.get("を", env.get_topic()))

def _bi_min(args, env):
    return min(args.get("を", env.get_topic()))

def _bi_nth(args, env):
    """<X>から<I>番目を取り出す"""
    seq = args.get("から", env.get_topic())
    i = args.get("を")
    if not isinstance(i, int):
        raise RuntimeYuiError("番目は整数で指定してください")
    return seq[i-1]

def _bi_range(args, env):
    """<A>から<B>までの範囲"""
    a = args.get("から")
    b = args.get("まで")
    return list(range(int(a), int(b)+1))

import math
import random as _random

# ── 数学 ──
def _bi_abs(args, env):     return abs(args.get("を", env.get_topic()))
def _bi_sqrt(args, env):    return math.sqrt(args.get("を", env.get_topic()))
def _bi_pow(args, env):     return args["を"] ** args["で"]  # <X>を<Y>で累乗
def _bi_round(args, env):   return round(args.get("を", env.get_topic()))
def _bi_floor(args, env):   return math.floor(args.get("を", env.get_topic()))
def _bi_ceil(args, env):    return math.ceil(args.get("を", env.get_topic()))
def _bi_random(args, env):
    a, b = args["から"], args["まで"]
    return _random.randint(int(a), int(b))

def _bi_sin(args, env):  return math.sin(args.get("を", env.get_topic()))
def _bi_cos(args, env):  return math.cos(args.get("を", env.get_topic()))
def _bi_tan(args, env):  return math.tan(args.get("を", env.get_topic()))
def _bi_log(args, env):  return math.log(args.get("を", env.get_topic()))
def _bi_exp(args, env):  return math.exp(args.get("を", env.get_topic()))

def _bi_shuffle(args, env):
    v = list(args.get("を", env.get_topic()))
    _random.shuffle(v)
    return v

def _bi_choice(args, env):
    v = args.get("を", env.get_topic())
    return _random.choice(v)

def _bi_median(args, env):
    v = sorted(args.get("を", env.get_topic()))
    n = len(v)
    if n == 0: return 0
    if n % 2 == 1: return v[n//2]
    a, b = v[n//2 - 1], v[n//2]
    return (a + b) / 2

def _bi_variance(args, env):
    v = args.get("を", env.get_topic())
    if not v: return 0
    m = sum(v) / len(v)
    return sum((x - m) ** 2 for x in v) / len(v)

def _bi_stddev(args, env):
    return math.sqrt(_bi_variance(args, env))

# JSON
import json as _json
def _bi_to_json(args, env):
    v = args.get("を", env.get_topic())
    # __種族__ などの内部キーは出さない
    def _clean(x):
        if isinstance(x, dict):
            return {k: _clean(val) for k, val in x.items() if not str(k).startswith("__")}
        if isinstance(x, list):
            return [_clean(y) for y in x]
        return x
    return _json.dumps(_clean(v), ensure_ascii=False)

def _bi_from_json(args, env):
    s = args.get("を", env.get_topic())
    return _json.loads(s)

# 日付・時刻
import datetime as _dt
def _bi_now(args, env):
    n = _dt.datetime.now()
    return {
        "年":   n.year,
        "月":   n.month,
        "日":   n.day,
        "時":   n.hour,
        "分":   n.minute,
        "秒":   n.second,
        "曜日": ["月","火","水","木","金","土","日"][n.weekday()],
    }

def _bi_today(args, env):
    n = _dt.date.today()
    return f"{n.year}-{n.month:02d}-{n.day:02d}"

# 文字列
def _bi_trim(args, env):
    return args.get("を", env.get_topic()).strip()

def _bi_upper(args, env):
    return args.get("を", env.get_topic()).upper()

def _bi_lower(args, env):
    return args.get("を", env.get_topic()).lower()

def _bi_substr(args, env):
    """<S>の <i>から <j>まで （1始まり、両端含む）"""
    s = args.get("の", args.get("を"))
    i = args.get("から", 1)
    j = args.get("まで", len(s))
    return s[max(0, int(i)-1):int(j)]

def _bi_contains_str(args, env):
    """<X>に <Y>を 含む（文字列・配列・辞書のキー）"""
    return _bi_contains(args, env)

# ── 配列・文字列共通 ──
def _bi_reverse(args, env):
    v = args.get("を", env.get_topic())
    if isinstance(v, str): return v[::-1]
    return list(reversed(v))

def _bi_sort_asc(args, env):
    return sorted(args.get("を", env.get_topic()))
def _bi_sort_desc(args, env):
    return sorted(args.get("を", env.get_topic()), reverse=True)

def _bi_split(args, env):
    s = args.get("を", env.get_topic())
    sep = args.get("で", "")
    return s.split(sep) if sep else list(s)

def _bi_join(args, env):
    seq = args.get("を", env.get_topic())
    sep = args.get("で", "")
    return sep.join(yui_to_str(x) for x in seq)

def _bi_contains(args, env):
    target = args.get("に", env.get_topic())
    item = args["を"]
    return item in target

def _bi_position(args, env):
    """<seq>から<item>の位置"""
    seq = args.get("から", env.get_topic())
    item = args["を"]
    try:
        return seq.index(item) + 1  # 1始まり
    except ValueError:
        return 0

def _bi_replace(args, env):
    """<S>の<A>を<B>に置換"""
    s = args.get("を", env.get_topic())
    return s.replace(args["を"] if "を" in args and "の" not in args else args["の"], args["に"])

def _bi_repeat(args, env):
    """<S>を<N>回繰り返す → 文字列／配列を N 倍"""
    return args["を"] * int(args["に"])

# ── 高階 ──
def _bi_map(args, env):
    """<配列>の各要素に<関数>を適用"""
    seq = args.get("に", args.get("の", env.get_topic()))
    f = args["を"]  # 関数または文字列名
    if isinstance(f, str):
        if f in _BUILTINS: f_call = lambda x: _invoke_builtin(f, {"を": x}, env)
        else: f_call = lambda x: env.get(f).call({"を": x})
    elif isinstance(f, Function):
        # 引数の助詞は「を」想定
        f_call = lambda x: f.call({"を": x})
    else:
        raise RuntimeYuiError("「適用する」の関数引数が不正")
    return [f_call(x) for x in seq]

def _bi_filter(args, env):
    """<配列>から<条件関数>を満たすものを抽出"""
    seq = args.get("から", env.get_topic())
    f = args["を"]
    if isinstance(f, str):
        if f in _BUILTINS: f_call = lambda x: _invoke_builtin(f, {"を": x}, env)
        else: f_call = lambda x: env.get(f).call({"を": x})
    elif isinstance(f, Function):
        f_call = lambda x: f.call({"を": x})
    else:
        raise RuntimeYuiError("「抽出する」の関数引数が不正")
    return [x for x in seq if f_call(x)]

# ── 型判定 ──
def _bi_is_int(args, env):    return isinstance(args.get("を", env.get_topic()), int) and not isinstance(args.get("を", env.get_topic()), bool)
def _bi_is_str(args, env):    return isinstance(args.get("を", env.get_topic()), str)
def _bi_is_list(args, env):   return isinstance(args.get("を", env.get_topic()), list)
def _bi_is_dict(args, env):   return isinstance(args.get("を", env.get_topic()), dict)

# ── 辞書操作 ──
def _bi_keys(args, env):
    d = args.get("を", env.get_topic())
    return list(d.keys())
def _bi_values(args, env):
    d = args.get("を", env.get_topic())
    return list(d.values())
def _bi_set_dict(args, env):
    """<辞書>に <鍵>を <値>で 設定 — 辞書の値を破壊的に更新"""
    d = args.get("に")
    k = args.get("を")
    v = args.get("で")
    if not isinstance(d, dict):
        raise RuntimeYuiError("「設定」の対象（に）は辞書である必要があります")
    d[str(k) if not isinstance(k, str) else k] = v
    return None
def _bi_get_dict(args, env):
    """<辞書>から <鍵>を 取得"""
    d = args.get("から", env.get_topic())
    k = args.get("を")
    if not isinstance(d, dict):
        raise RuntimeYuiError("「取得」の対象（から）は辞書である必要があります")
    return d.get(k)

def _bi_assert(args, env):
    v = args.get("を", env.get_topic())
    if not v:
        msg = args.get("で", "断言失敗")
        raise RuntimeYuiError(yui_to_str(msg))
    return None

def _bi_throw(args, env):
    msg = args.get("を", "失敗")
    raise RuntimeYuiError(yui_to_str(msg))

def _bi_load(args, env):
    """別の .yui ファイルを評価して現在の環境に取り込む"""
    import os as _os
    path = args.get("を")
    if not isinstance(path, str):
        raise RuntimeYuiError("読み込む：ファイルパスは文字列で指定してください")
    if not _os.path.isabs(path):
        base = _os.path.dirname(_os.path.abspath(__file__))
        path = _os.path.join(base, path)
    if not _os.path.exists(path):
        raise RuntimeYuiError(f"読み込み失敗：ファイル「{path}」が見つかりません")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    tokens = tokenize(src)
    prog = Parser(tokens).parse_program()
    Evaluator.eval_program(prog, env)
    return None

_BUILTINS: dict[str, Callable] = {
    # 入出力
    "表示":          _bi_print,
    "入力":          _bi_input,
    # 例外
    "断言":          _bi_assert,
    "投げる":        _bi_throw,
    # モジュール
    "読み込む":      _bi_load,
    # 基本
    "長さ":          _bi_length,
    "文字列にする":  _bi_to_str,
    "整数にする":    _bi_to_int,
    "小数にする":    _bi_to_float,
    # 配列操作
    "追加":          _bi_append,
    "末尾追加":      _bi_append_tail,
    "連結":          _bi_concat,
    "合計":          _bi_sum,
    "最大":          _bi_max,
    "最小":          _bi_min,
    "番目取り出す":  _bi_nth,
    "範囲":          _bi_range,
    "反転":          _bi_reverse,
    "昇順":          _bi_sort_asc,
    "降順":          _bi_sort_desc,
    "含む":          _bi_contains,
    "位置":          _bi_position,
    # 数学
    "絶対値":        _bi_abs,
    "平方根":        _bi_sqrt,
    "累乗":          _bi_pow,
    "四捨五入":      _bi_round,
    "床":            _bi_floor,
    "天井":          _bi_ceil,
    "乱数":          _bi_random,
    "正弦":          _bi_sin,
    "余弦":          _bi_cos,
    "正接":          _bi_tan,
    "対数":          _bi_log,
    "指数":          _bi_exp,
    # 統計
    "中央値":        _bi_median,
    "分散":          _bi_variance,
    "標準偏差":      _bi_stddev,
    # ランダム
    "シャッフル":    _bi_shuffle,
    "選ぶ":          _bi_choice,
    # JSON
    "JSON化":        _bi_to_json,
    "JSON解読":      _bi_from_json,
    # 日付
    "今":            _bi_now,
    "今日":          _bi_today,
    # 文字列詳細
    "整形":          _bi_trim,
    "大文字":        _bi_upper,
    "小文字":        _bi_lower,
    "部分":          _bi_substr,
    # 文字列
    "分割":          _bi_split,
    "結合":          _bi_join,
    "繰り返し":      _bi_repeat,
    # 高階
    "適用":          _bi_map,
    "抽出":          _bi_filter,
    # 型判定
    "整数":          _bi_is_int,
    "文字列":        _bi_is_str,
    "配列":          _bi_is_list,
    "辞書":          _bi_is_dict,
    # 辞書
    "鍵":            _bi_keys,
    "値":            _bi_values,
    "設定":          _bi_set_dict,
    "取得":          _bi_get_dict,
}

# 主題ブロック内で暗黙レシーバを取る動詞
_TOPIC_VERBS = {"表示", "長さ", "合計", "最大", "最小", "反転", "昇順", "降順",
                "絶対値", "平方根", "四捨五入", "床", "天井", "鍵", "値"}

# 主題に対するメソッドディスパッチ
def _tm_length(topic, args, env): return len(topic)
def _tm_print(topic, args, env): print(yui_to_str(topic)); return None

_TOPIC_METHODS = {
    "長さ": _tm_length,
    "表示": _tm_print,
}


# =============================================================================
# 6. 公開API
# =============================================================================

def format_error(msg: str, source: str) -> str:
    """エラーメッセージに該当行をハイライトして付与する"""
    m = re.match(r"(\d+)行目", msg)
    if not m:
        return msg
    line_no = int(m.group(1))
    lines = source.splitlines()
    if not (1 <= line_no <= len(lines)):
        return msg
    line_text = lines[line_no-1]
    pad = " " * (len(str(line_no)) + 2)
    return f"{msg}\n{pad}{line_no} | {line_text}"

def run(source: str, env: Optional[Environment] = None):
    tokens = tokenize(source)
    parser = Parser(tokens)
    prog = parser.parse_program()
    env = env or Evaluator.make_global_env()
    Evaluator.eval_program(prog, env)
    return env

def repl():
    print("結（Yui）言語 REPL — 終了は Ctrl+D / exit")
    env = Evaluator.make_global_env()
    buf = []
    prompt = ">>> "
    while True:
        try:
            line = input(prompt)
        except EOFError:
            print()
            break
        if line.strip() in ("exit", "終了"):
            break
        buf.append(line)
        # 簡易判定：行末が「ならば」「のあいだ繰り返す」などでブロック開始ならcontinue
        joined = "\n".join(buf)
        if any(joined.rstrip().endswith(k) for k in ("ならば","のあいだ繰り返す","繰り返す","：",":","について")):
            prompt = "... "
            continue
        try:
            run(joined, env)
        except (LexError, ParseError, RuntimeYuiError) as e:
            print(f"エラー：{e}")
        except Exception as e:
            print(f"内部エラー：{type(e).__name__}: {e}")
        buf.clear()
        prompt = ">>> "

def main():
    if len(sys.argv) < 2:
        repl()
        return
    path = sys.argv[1]
    with open(path, encoding="utf-8") as f:
        src = f.read()
    try:
        run(src)
    except (LexError, ParseError, RuntimeYuiError) as e:
        print(f"エラー：{format_error(str(e), src)}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
