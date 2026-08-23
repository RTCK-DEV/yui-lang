/**
 * 結（Yui）テストランナー（ブラウザ実装）
 *
 * repl.html の <script> を取り出し、Node の vm 上で最小限の DOM スタブとともに
 * 実行して runYui() を直接叩く。ブラウザも Playwright も要らないので
 * `node tests/js_test.mjs` だけで走る。
 *
 * tests/cases.json は Python 側の tests/run_tests.py と共有している。
 *   js: false      → このテストでは対象外（ブラウザ実装に無い機能を使うケース）
 *   js_expect      → ブラウザ実装だけ出力が異なる既知のケースの期待値
 *   known_failure  → 未解決の不具合。終了コードには影響しないが必ず表示する
 *
 * 著作権表記：RTCK
 */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const OK = '  OK  ', NG = '  NG  ', KN = ' 既知 ';

/** repl.html の UI コードが起動時に触る DOM を最小限だけ用意する。 */
function makeElement() {
  const el = {
    value: '', innerHTML: '', textContent: '', selectedIndex: 0,
    options: [], children: [], style: {},
    classList: { add() {}, remove() {}, toggle() {} },
    addEventListener() {}, removeEventListener() {},
    appendChild(child) { el.children.push(child); return child; },
    setAttribute() {}, focus() {}, blur() {},
  };
  return el;
}

function loadInterpreter() {
  const html = fs.readFileSync(path.join(ROOT, 'repl.html'), 'utf8');
  const m = html.match(/<script>([\s\S]*?)<\/script>/);
  if (!m) throw new Error('repl.html に <script> ブロックが見つかりません');

  // SAMPLES / STDLIB_SRC は const 宣言でグローバルオブジェクトに載らないため、
  // 末尾で明示的に取り出す。
  const source = m[1] + `
;globalThis.__SAMPLES = typeof SAMPLES !== "undefined" ? SAMPLES : null;
;globalThis.__STDLIB_SRC = typeof STDLIB_SRC !== "undefined" ? STDLIB_SRC : null;
`;

  const ctx = {
    document: {
      getElementById: () => makeElement(),
      createElement: () => makeElement(),
      addEventListener() {},
    },
    window: { addEventListener() {} },
    prompt: () => null,
    console,
  };
  ctx.globalThis = ctx;
  vm.createContext(ctx);
  vm.runInContext(source, ctx, { filename: 'repl.html' });
  if (typeof ctx.runYui !== 'function') throw new Error('runYui() が定義されていません');
  return ctx;
}

/** ケースの合否と、実際に起きたことの説明を返す。 */
function judge(c, r) {
  const out = String(r.ok ? r.output : '').replace(/\n+$/, '');
  if (c.expect_error !== undefined) {
    if (r.ok) return [false, `エラーを期待したが正常終了（出力 ${JSON.stringify(out)}）`];
    if (!String(r.error).includes(c.expect_error)) return [false, `エラー文言が不一致：${JSON.stringify(r.error)}`];
    return [true, r.error];
  }
  if (!r.ok) return [false, `エラー：${r.error}`];
  const want = c.js_expect !== undefined ? c.js_expect : c.expect;
  if (out !== want) return [false, `出力が不一致：${JSON.stringify(out)}`];
  return [true, out];
}

function main() {
  console.log(`結（Yui）テスト — ブラウザ実装 / Node ${process.version}\n`);
  const ctx = loadInterpreter();
  const cases = JSON.parse(fs.readFileSync(path.join(ROOT, 'tests', 'cases.json'), 'utf8'));
  let failed = 0;
  const known = [];

  console.log('── 1. 埋め込み stdlib の一致 ──');
  const stdlib = fs.readFileSync(path.join(ROOT, 'stdlib.yui'), 'utf8').replace(/\n+$/, '');
  const embedded = String(ctx.__STDLIB_SRC ?? '').replace(/\n+$/, '');
  if (embedded === stdlib) {
    console.log(`${OK} repl.html が実際に読み込む stdlib は stdlib.yui と一致しています`);
  } else {
    failed++;
    console.log(`${NG} 埋め込み stdlib が stdlib.yui と一致しません（python3 tools/build_repl.py で再生成）`);
  }

  console.log('\n── 2. 言語ケース（ブラウザ実装）──');
  const target = cases.filter(c => c.js !== false);
  let passed = 0;
  for (const c of target) {
    const r = ctx.runYui(c.src);
    const [ok, detail] = judge(c, r);
    if (c.known_failure) {
      if (ok) {
        console.log(`${OK} ${c.name}（既知の未解決として登録されているが成功した。cases.json の known_failure を外すこと）`);
        passed++;
      } else {
        known.push(`${c.name}：${detail}`);
      }
      continue;
    }
    if (ok) { passed++; continue; }
    failed++;
    console.log(`${NG} ${c.name}`);
    console.log(`        期待: ${JSON.stringify(c.expect_error ?? c.js_expect ?? c.expect)}`);
    console.log(`        実際: ${detail}`);
  }
  const skipped = cases.filter(c => c.js === false);
  console.log(`  ${passed} 成功 / ${failed} 失敗 / ${known.length} 既知の未解決`
    + `（対象 ${target.length} ケース${skipped.length ? ` / 対象外 ${skipped.length}` : ''}）`);
  if (skipped.length) {
    console.log('  対象外（Python 実装との差異が未解決のため、ここでは判定しない）:');
    for (const c of skipped) console.log(`        ${c.name} — ${c.note ?? '理由の記載なし'}`);
  }

  console.log('\n── 3. REPL 組み込みサンプル ──');
  const samples = ctx.__SAMPLES;
  if (!samples) {
    failed++;
    console.log(`${NG} SAMPLES を取り出せませんでした`);
  } else {
    let sp = 0, sf = 0;
    for (const [name, src] of Object.entries(samples)) {
      const r = ctx.runYui(src);
      if (r.ok) sp++;
      else { sf++; failed++; console.log(`${NG} ${name}\n        ${r.error}`); }
    }
    console.log(`  ${sp} 成功 / ${sf} 失敗（全 ${sp + sf} 本）`);
  }

  if (known.length) {
    console.log('\n── 既知の未解決 ──');
    console.log('  未修正の不具合として意図的に残しているケース。終了コードには影響しない。');
    for (const k of known) console.log(`${KN} ${k}`);
  }

  console.log();
  if (failed) { console.log(`失敗：${failed} 件`); process.exit(1); }
  console.log(`すべて成功（既知の未解決 ${known.length} 件は除く）`);
}

main();
