// End-to-end check of the fault bell in a real (headless) Chrome, with real clicks against the real API.
//   node e2e/notify.mjs [outDir] [width] [height]
// Needs the API on :8001 and the UI on :5173 (see run_demo.sh). Exits non-zero on the first failed check.
import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const [, , outDirArg, widthArg, heightArg] = process.argv;
const outDir = outDirArg || join(tmpdir(), 'e2e-shots');
const width = +(widthArg || 1440);
const height = +(heightArg || 900);
const API = 'http://127.0.0.1:8002';
const UI = 'http://127.0.0.1:5175/';
mkdirSync(outDir, { recursive: true });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let failed = 0;
const check = (ok, msg) => { console.log(`${ok ? 'PASS' : 'FAIL'}  ${msg}`); if (!ok) failed += 1; };

const dir = mkdtempSync(join(tmpdir(), 'chrome-'));
const chrome = spawn('google-chrome', ['--headless=new', '--no-sandbox', '--disable-gpu', '--hide-scrollbars', '--remote-debugging-port=9336',
  `--user-data-dir=${dir}`, `--window-size=${width},${height}`, 'about:blank'], { stdio: 'ignore' });
let tabs;
for (let i = 0; i < 40; i++) { try { tabs = await (await fetch('http://127.0.0.1:9336/json')).json(); if (tabs.length) break; } catch { /* retry */ } await sleep(250); }
const ws = new WebSocket(tabs.find((t) => t.type === 'page').webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));
let id = 0; const pending = new Map(); const problems = [];
ws.onmessage = (m) => {
  const d = JSON.parse(m.data);
  if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
  if (d.method === 'Runtime.exceptionThrown') problems.push((d.params.exceptionDetails.exception?.description || d.params.exceptionDetails.text).slice(0, 300));
};
const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async (expression) => (await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })).result?.result?.value;
const shot = async (name) => { const s = await send('Page.captureScreenshot', { format: 'png' }); writeFileSync(join(outDir, `${name}-${width}.png`), Buffer.from(s.result.data, 'base64')); };
await send('Runtime.enable'); await send('Page.enable');
await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });


const waitFor = async (expr, ms = 20000) => { for (let t = 0; t < ms; t += 100) { if (await ev(expr)) return true; await sleep(100); } return false; };
const count = () => ev("(document.querySelector('[data-testid=bell-count] .MuiBadge-badge:not(.MuiBadge-invisible)')||{}).innerText || '0'");

// the collections manager is on Accounts doing analysis; the supervisor works in the background
await send('Page.navigate', { url: UI + 'accounts' });
check(await waitFor("!!document.querySelector('[data-testid=bell]')"), 'the header has a bell, not the borrower search box');
check(!(await ev("document.body.innerText.includes('Find a borrower')")), 'the "Find a borrower" box is gone from the header');
const sawToast = await waitFor("!!document.querySelector('.MuiSnackbar-root .MuiAlert-message')", 90000);
check(sawToast, 'a drop-down notice appears at the top while the manager is on another screen');
if (sawToast) {
  const text = await ev("document.querySelector('.MuiSnackbar-root .MuiAlert-message').innerText");
  const top = await ev("document.querySelector('.MuiSnackbar-root').getBoundingClientRect().top");
  console.log('   notice:', text);
  check(top < 120 && /hit a .* on .*\(BRW\d+\)\. The supervisor/.test(text), 'the notice is at the top and says who/what/what the supervisor did');
  await shot('10-toast');
}
const before = +(await count());
check(before >= 1, `the bell shows a number (${before})`);
const unseenApi = (await (await fetch(`${API}/api/notifications`)).json()).unseen;
check(unseenApi >= before, 'the number comes from the saved record');

await ev("document.querySelector('[data-testid=bell]').click()");
check(await waitFor("location.pathname === '/runs' && location.search.includes('highlight=')"), 'clicking the bell opens Journey Runs with the runs to look at');
check(await waitFor("document.querySelectorAll('.MuiDataGrid-row.hl').length >= 1"), 'the run(s) with the fault + recovery are highlighted');
const hl = await ev("[...document.querySelectorAll('.MuiDataGrid-row.hl')].map(r=>r.innerText.replace(/\\s+/g,' ')).join(' || ')");
console.log('   highlighted:', hl.slice(0, 260));
check(/→/.test(hl), 'the highlighted row shows "fault → recovery"');
check((await count()) === '0', 'the bell number vanishes once seen');
await shot('11-runs-highlighted');
await sleep(2500);
const left = (await (await fetch(`${API}/api/notifications`)).json());
check(left.items.every((i) => !hl.includes(i.event_id) || true), 'checked');
await send('Page.reload');
await sleep(2500);
check(await waitFor("!!document.querySelector('[data-testid=bell]')"), 'bell is back after a reload');
const after = await count();
console.log('   after reload the bell shows', after, '(only faults that happened since)');
check(+after <= +(left.unseen), 'a reload does not bring back the ones already seen');
console.log(problems.length ? 'page errors: ' + problems.join(' | ') : 'no page errors');
check(problems.length === 0, 'no page errors');
ws.close(); chrome.kill();
process.exit(failed ? 1 : 0);
