/**
 * ブラウザ向け HTML を実際のブラウザで検証する
 *
 * tests/js_test.mjs は Node の vm 上でインタプリタを動かすため、HTML の UI 側
 * ——とくに WebLLM を使う ai_*.html——には手が届かない。この道具は Chromium を
 * 実際に起動し、5つの HTML を開いて操作し、ページ例外が出ないことを確かめる。
 *
 * WebLLM の CDN はスタブに差し替える。各ページが期待する応答書式で返すので、
 * 「LLM 出力 → 解析 → Yui コード生成 → インタプリタ実行 → 描画」という
 * 本来の経路がモデルの実体なしで通る。ダウンロードもネットワークも要らない。
 *
 * テストではなく調査用。Playwright を別途入れる必要があるため、
 * 依存なしで走る tests/ には含めていない。
 *
 *     npm install playwright && npx playwright install chromium
 *     node tools/browser_check.mjs
 *     node tools/browser_check.mjs --show    # 画面を出して実行
 *
 * 著作権表記：RTCK
 */
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const HEADED = process.argv.includes('--show');
const OK = '  OK  ', NG = '  NG  ';

let chromium;
try {
  ({ chromium } = createRequire(import.meta.url)('playwright'));
} catch {
  console.error('Playwright が見つかりません。次を実行してください：');
  console.error('  npm install playwright && npx playwright install chromium');
  process.exit(2);
}

/** 各ページが期待する書式で返す偽エンジン。CDN の代わりに配る ES module。 */
function stubModule(kind) {
  return `
globalThis.__engineCalls = 0;
export async function CreateMLCEngine(modelId, opts = {}) {
  globalThis.__modelId = modelId;
  if (opts.initProgressCallback) opts.initProgressCallback({ progress: 1, text: 'スタブ' });
  let n = 0;
  const player = (i) => '【描写】葵は窓の外を見た' + i + '。\\n【心情】言葉を探している' + i + '。\\n【発言】そうだね、' + i + '。\\n【関係】+2';
  const branch = (i) => [
    '場面：教室の午後' + i,
    '分岐A：', '描写：葵は本を閉じた' + i, '心情：話しかけようか迷った' + i, '台詞：……読み終わった' + i, '変動：+3',
    '分岐B：', '描写：葵は窓を見た' + i, '心情：外の光がまぶしい' + i, '台詞：いい天気だな' + i, '変動：+1',
    '分岐C：', '描写：葵は席を立った' + i, '心情：ここにいたくない' + i, '台詞：先に行く' + i, '変動：-2',
  ].join('\\n');
  const dialog = (i) => 'そう思っているよ' + i + '。';
  const KIND = ${JSON.stringify(kind)};
  return {
    modelId, interruptGenerate() {}, async unload() {},
    chat: { completions: { async create() {
      globalThis.__engineCalls++; n++;
      const text = KIND === 'player' ? player(n) : KIND === 'branch' ? branch(n) : dialog(n);
      return { choices: [{ message: { role: 'assistant', content: text }, delta: { content: text }, finish_reason: 'stop' }],
               usage: { total_tokens: 1 } };
    } } },
  };
}
export default { CreateMLCEngine };`;
}

/** 本文が増えなくなるまで待つ。動き続けるページのために上限を切る。 */
async function settle(page, { maxMs = 8000, step = 500 } = {}) {
  let prev = -1, stable = 0;
  for (let waited = 0; waited < maxMs && stable < 4; waited += step) {
    await page.waitForTimeout(step);
    const len = await page.evaluate(() => document.body.innerText.length);
    if (len === prev) stable++; else stable = 0;
    prev = len;
  }
}

const CASES = [
  {
    file: 'repl.html', kind: null,
    async run(page) {
      const r = await page.evaluate(() => runYui('『{［1,2,3］の合計}』を表示せよ'));
      return { 'REPL で Yui 実行': r.ok ? r.output : 'エラー' };
    },
    expect: { 'REPL で Yui 実行': '6' },
  },
  {
    file: 'drama_player.html', kind: null,
    async run(page) {
      await page.click('#introClose').catch(() => {});
      await page.evaluate(() => {
        const s = document.querySelector('input[type=range]');
        if (s) { s.value = s.max; s.dispatchEvent(new Event('input', { bubbles: true })); }
      });
      await settle(page, { maxMs: 45000 });
      await page.fill('#newAffinity', '1200').catch(() => {});
      await page.click('#confirmEdit').catch(() => {});
      await settle(page, { maxMs: 30000 });
      const t = await page.evaluate(() => document.body.innerText);
      return { 'エピローグ到達': /── 完 ──/.test(t) ? 'はい' : 'いいえ',
               '真EDルート': /真ED/.test(t) ? 'はい' : 'いいえ' };
    },
    expect: { 'エピローグ到達': 'はい', '真EDルート': 'はい' },
  },
  {
    file: 'ai_player.html', kind: 'player',
    async run(page) {
      await page.click('#loader-start').catch(() => {});
      await page.waitForTimeout(1500);
      await page.fill('#user-input', 'こんにちは').catch(() => {});
      await page.click('#sendBtn').catch(() => {});
      await settle(page, { maxMs: 12000 });
      const t = await page.evaluate(() => document.body.innerText);
      return { 'モデルID': await page.evaluate(() => globalThis.__modelId ?? '-'),
               '推論の実行': String(await page.evaluate(() => globalThis.__engineCalls ?? 0) > 0),
               '生成物の描画': /窓の外を見た/.test(t) ? 'はい' : 'いいえ' };
    },
    expect: { '推論の実行': 'true', '生成物の描画': 'はい' },
  },
  {
    file: 'ai_dialog.html', kind: 'dialog',
    async run(page) {
      await page.click('#loader-start').catch(() => {});
      await page.waitForTimeout(1500);
      await page.click('button:has-text("2者対話")').catch(() => {});
      await page.waitForTimeout(300);
      await page.click('#startBtn').catch(() => {});
      await settle(page, { maxMs: 20000 });
      await page.click('#stopBtn').catch(() => {});
      const t = await page.evaluate(() => document.body.innerText);
      return { 'モデルID': await page.evaluate(() => globalThis.__modelId ?? '-'),
               '推論の実行': String(await page.evaluate(() => globalThis.__engineCalls ?? 0) > 0),
               '生成物の描画': /そう思っているよ/.test(t) ? 'はい' : 'いいえ' };
    },
    expect: { '推論の実行': 'true', '生成物の描画': 'はい' },
  },
  {
    file: 'ai_branch.html', kind: 'branch',
    async run(page) {
      await page.click('#loader-start').catch(() => {});
      await page.waitForTimeout(1500);
      await page.click('#startBtn').catch(() => {});
      await settle(page, { maxMs: 25000 });
      await page.click('#stopBtn').catch(() => {});
      const t = await page.evaluate(() => document.body.innerText);
      return { 'モデルID': await page.evaluate(() => globalThis.__modelId ?? '-'),
               '推論の実行': String(await page.evaluate(() => globalThis.__engineCalls ?? 0) > 0),
               '生成 Yui の実行': /好感度加算/.test(t) ? 'はい' : 'いいえ' };
    },
    expect: { '推論の実行': 'true', '生成 Yui の実行': 'はい' },
  },
];

const browser = await chromium.launch({ headless: !HEADED });
let failed = 0;

for (const c of CASES) {
  const page = await browser.newPage();
  page.setDefaultTimeout(8000);
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
  page.on('dialog', d => d.accept('1'));
  if (c.kind) {
    const body = stubModule(c.kind);
    await page.route(/esm\.run|jsdelivr|unpkg|mlc-ai|huggingface/, r =>
      r.fulfill({ status: 200, contentType: 'application/javascript; charset=utf-8', body }));
  }

  let result = {};
  let crashed = null;
  try {
    await page.goto('file://' + path.join(ROOT, c.file), { waitUntil: 'load' });
    result = await c.run(page);
  } catch (e) {
    crashed = e.message.split('\n')[0];
  }

  const bad = crashed || errors.length
    || Object.entries(c.expect).some(([k, v]) => String(result[k]) !== v);
  if (bad) failed++;
  console.log(`${bad ? NG : OK} ${c.file}`);
  for (const [k, v] of Object.entries(result)) {
    const want = c.expect[k];
    const mark = want !== undefined && String(v) !== want ? '  ★期待 ' + want : '';
    console.log(`        ${k}: ${v}${mark}`);
  }
  if (crashed) console.log(`        ★操作中に失敗: ${crashed}`);
  if (errors.length) console.log(`        ★ページ例外: ${errors.slice(0, 3).join(' / ')}`);
  await page.close();
}

await browser.close();
console.log();
if (failed) { console.log(`失敗：${failed} / ${CASES.length}`); process.exit(1); }
console.log(`すべて成功（${CASES.length} ファイル）`);
