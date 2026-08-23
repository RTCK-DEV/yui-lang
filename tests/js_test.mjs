/**
 * 結（Yui）テストランナー（ブラウザ実装）
 *
 * ブラウザも Playwright も使わない。Node の vm 上に最小限の DOM スタブを置いて
 * インタプリタを直接動かす。`node tests/js_test.mjs` だけで走る。
 *
 * 検証する内容:
 *   1. 言語ケース   yui.js + stdlib.yui を読み込み tests/cases.json を実行
 *   2. 埋め込み同期 5つの HTML が同一の生成ブロックを持つか
 *   3. 構文         5つの <script> 全体が構文として妥当か
 *   4. 実際の読込   ES module でない HTML を実際に読み込んで動かす
 *   5. REPLサンプル repl.html の組み込みサンプル
 *
 * tests/cases.json は Python 側の tests/run_tests.py と共有している。
 *   js: false      → このテストでは対象外
 *   js_expect      → ブラウザ実装だけ出力が異なる既知のケースの期待値
 *   known_failure  → 未解決の不具合。終了コードには影響しないが必ず表示する
 *
 * 著作権表記：RTCK
 */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import os from 'node:os';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const OK = '  OK  ', NG = '  NG  ', KN = ' 既知 ';
const TARGETS = ['repl.html', 'drama_player.html', 'ai_player.html', 'ai_dialog.html', 'ai_branch.html'];
const BEGIN = '/* ── YUI:BEGIN', END = '/* ── YUI:END ── */';

let failed = 0;
const known = [];

/** HTML の UI コードが起動時に触る DOM を最小限だけ用意する。 */
function makeElement() {
  const el = {
    value: '', innerHTML: '', textContent: '', selectedIndex: 0, className: '', id: '',
    options: [], children: [], style: {}, dataset: {},
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    addEventListener() {}, removeEventListener() {},
    appendChild(child) { el.children.push(child); return child; },
    setAttribute() {}, getAttribute: () => null,
    focus() {}, blur() {}, remove() {}, scrollIntoView() {}, scrollTo() {},
    insertAdjacentHTML() {}, replaceChildren() {}, prepend() {}, before() {}, after() {},
    querySelector: () => makeElement(), querySelectorAll: () => [],
    cloneNode: () => makeElement(), closest: () => null, contains: () => false,
  };
  return el;
}

function makeContext() {
  const ctx = {
    document: {
      getElementById: makeElement, createElement: makeElement, addEventListener() {},
      body: makeElement(), querySelector: () => makeElement(), querySelectorAll: () => [],
    },
    window: { addEventListener() {}, location: { hash: '', search: '' } },
    prompt: () => null, alert() {}, console,
    setTimeout, clearTimeout, setInterval, clearInterval,
    requestAnimationFrame: (fn) => fn(0),
  };
  ctx.globalThis = ctx;
  return vm.createContext(ctx);
}

function scriptOf(file) {
  const html = fs.readFileSync(path.join(ROOT, file), 'utf8');
  const m = html.match(/<script([^>]*)>([\s\S]*?)<\/script>/);
  if (!m) throw new Error(`${file} に <script> が見つかりません`);
  return { attrs: m[1], body: m[2], isModule: /type\s*=\s*["']module["']/.test(m[1]) };
}

function escapeForTemplateLiteral(s) {
  return s.replace(/\\/g, '\\\\').replace(/`/g, '\\`').replace(/\$\{/g, '\\${');
}

/** yui.js / stdlib.yui / builtin_types.json からインタプリタを組み立てて読み込む。 */
function loadInterpreter() {
  const core = fs.readFileSync(path.join(ROOT, 'yui.js'), 'utf8');
  const stdlib = escapeForTemplateLiteral(fs.readFileSync(path.join(ROOT, 'stdlib.yui'), 'utf8').replace(/\n+$/, ''));
  const raw = JSON.parse(fs.readFileSync(path.join(ROOT, 'builtin_types.json'), 'utf8'));
  const sigs = Object.fromEntries(Object.entries(raw).filter(([k]) => !k.startsWith('_')));
  const src = `${core}\nconst BUILTIN_ARG_TYPES = ${JSON.stringify(sigs)};\n`
    + `const STDLIB_SRC = \`${stdlib}\n\`;\n;globalThis.__STDLIB_SRC = STDLIB_SRC;`;
  const ctx = makeContext();
  vm.runInContext(src, ctx, { filename: 'yui.js' });
  if (typeof ctx.runYui !== 'function') throw new Error('yui.js が runYui を定義していません');
  return ctx;
}

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

function runCases(ctx) {
  console.log('── 1. 言語ケース（yui.js）──');
  const cases = JSON.parse(fs.readFileSync(path.join(ROOT, 'tests', 'cases.json'), 'utf8'));
  const target = cases.filter(c => c.js !== false);
  let passed = 0;
  for (const c of target) {
    const r = ctx.runYui(c.src);
    const [ok, detail] = judge(c, r);
    if (c.known_failure) {
      if (ok) { console.log(`${OK} ${c.name}（既知の未解決として登録されているが成功した。cases.json の known_failure を外すこと）`); passed++; }
      else known.push(`${c.name}：${detail}`);
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
}

function checkEmbedded() {
  console.log('\n── 2. 5つの HTML の埋め込み同期 ──');
  const core = fs.readFileSync(path.join(ROOT, 'yui.js'), 'utf8').trimEnd();
  const coreTail = core.split('\n').slice(-3).join('\n');
  const blocks = {};
  for (const f of TARGETS) {
    const s = scriptOf(f).body;
    const b = s.indexOf(BEGIN), e = s.indexOf(END);
    if (b === -1 || e === -1) { failed++; console.log(`${NG} ${f} に生成ブロックのマーカーがありません`); continue; }
    blocks[f] = s.slice(b, e + END.length);
    if (!blocks[f].includes(coreTail)) { failed++; console.log(`${NG} ${f} の生成ブロックが yui.js の内容で終わっていません`); }
  }
  const values = Object.values(blocks);
  if (values.length === TARGETS.length && values.every(v => v === values[0])) {
    console.log(`${OK} ${TARGETS.length}本すべてが同一の生成ブロックを持っています（${values[0].length} 文字）`);
  } else {
    failed++;
    console.log(`${NG} 生成ブロックが一致しません（python3 tools/build_html.py で再生成）`);
  }
}

function checkSyntax() {
  console.log('\n── 3. <script> 全体の構文 ──');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'yui-syntax-'));
  try {
    for (const f of TARGETS) {
      const { body, isModule } = scriptOf(f);
      const tmp = path.join(dir, f.replace('.html', isModule ? '.mjs' : '.js'));
      fs.writeFileSync(tmp, body);
      try {
        execFileSync(process.execPath, ['--check', tmp], { stdio: 'pipe' });
        console.log(`${OK} ${f.padEnd(20)} (${isModule ? 'module' : 'script'})`);
      } catch (e) {
        failed++;
        console.log(`${NG} ${f} ${String(e.stderr).split('\n').slice(0, 3).join(' ')}`);
      }
    }
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

function runHtmlFiles() {
  console.log('\n── 4. HTML を実際に読み込んで動かす ──');
  const probes = [
    ['補間とメソッド記法', '『{［1,2,3］の合計}』を表示せよ', '6'],
    ['比較(右辺が識別子)', 'B を 5 とする\ni を 1 とする\nもし i が B 以下 ならば\n「真」を表示せよ\nおわり', '真'],
    ['助詞入り組み込み', '(5 を 文字列にする) を 表示せよ', '5'],
  ];
  for (const f of TARGETS) {
    const { body, isModule } = scriptOf(f);
    if (isModule) {
      console.log(`  --   ${f.padEnd(20)} ES module（外部 CDN を import するため読み込みは対象外。生成ブロックは 2 と 3 で確認済み）`);
      continue;
    }
    const ctx = makeContext();
    try {
      vm.runInContext(body, ctx, { filename: f });
    } catch (e) {
      failed++;
      console.log(`${NG} ${f} 読み込み時に例外：${e.message}`);
      continue;
    }
    const results = probes.map(([label, src, want]) => {
      const r = ctx.runYui(src);
      const got = r.ok ? String(r.output).trim() : `エラー`;
      if (got !== want) { failed++; return `${label}=${got}（期待 ${want}）★`; }
      return `${label}=${got}`;
    });
    console.log(`${OK} ${f.padEnd(20)} ${results.join('  ')}`);
  }
}

function runReplSamples() {
  console.log('\n── 5. repl.html の組み込みサンプル ──');
  const { body } = scriptOf('repl.html');
  const ctx = makeContext();
  vm.runInContext(body + ';globalThis.__SAMPLES = typeof SAMPLES !== "undefined" ? SAMPLES : null;', ctx, { filename: 'repl.html' });
  const samples = ctx.__SAMPLES;
  if (!samples) { failed++; console.log(`${NG} SAMPLES を取り出せませんでした`); return; }
  let sp = 0, sf = 0;
  for (const [name, src] of Object.entries(samples)) {
    const r = ctx.runYui(src);
    if (r.ok) sp++;
    else { sf++; failed++; console.log(`${NG} ${name}\n        ${r.error}`); }
  }
  console.log(`  ${sp} 成功 / ${sf} 失敗（全 ${sp + sf} 本）`);
}

function main() {
  console.log(`結（Yui）テスト — ブラウザ実装 / Node ${process.version}\n`);
  runCases(loadInterpreter());
  checkEmbedded();
  checkSyntax();
  runHtmlFiles();
  runReplSamples();

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
