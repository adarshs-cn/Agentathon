// End-to-end check of the notification panel (live mode, two scripted faults) in a real (headless) Chrome, with real clicks against the real API.
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
const toastText = () => ev("(document.querySelector('.MuiSnackbar-root .MuiAlert-message')||{}).innerText || ''");
const click = (sel) => ev(`document.querySelector('${sel}').click()`);

await send('Page.navigate', { url: UI });
check(await waitFor("!!document.querySelector('[data-testid=bell]')"), 'the header has the bell');
const text0 = await ev('document.body.innerText');
check(!/Judge demo build|synthetic/.test(text0.split('CreditNirvana')[0]) && !text0.includes('Judge demo build'), 'the "Judge demo build" label is gone');
check(!text0.includes('MT-02 SUPERVISOR'), 'the "MT-02 SUPERVISOR" label is gone');

// 1st fault: the alert drops in; we IGNORE it
check(await waitFor("!!document.querySelector('.MuiSnackbar-root .MuiAlert-message')", 170000), 'an alert drops in at the top when a fault happens');
const t1 = await toastText();
console.log('   alert:', t1.replace(/\s+/g, ' '));
check(/^Alert Supervisor Agent - .+\/.+ happened and recovering/.test(t1), 'it reads "Alert Supervisor Agent - {Agent}/{fault} happened and recovering"');
check(await ev("[...document.querySelectorAll('.MuiSnackbar-root button')].map(b=>b.innerText).join('|')") === 'Mark as read|Ignore', 'it offers Mark as read and Ignore');
await shot('30-alert');
await click('[data-testid=toast-ignore]');
check(await waitFor("!document.querySelector('.MuiSnackbar-root .MuiAlert-message')", 5000), 'Ignore closes the alert');
check(+(await count()) >= 1, `an ignored alert stays unread on the bell (${await count()})`);
const unreadAfterIgnore = +(await count());

// the bell opens a panel (it does not navigate) and lists the unread alert
await click('[data-testid=bell]');
check(await waitFor("!!document.querySelector('[data-testid=notif-panel]')"), 'clicking the bell opens a simple panel');
check(await ev("location.pathname") === '/', 'and does not leave the current page');
check(await ev("document.querySelectorAll('[data-testid=notif-item]').length") === unreadAfterIgnore, 'the panel lists the unread alert(s)');
check(/Alert Supervisor Agent - /.test(await ev("document.querySelector('[data-testid=notif-item]').innerText")), 'with the alert message');
await shot('31-panel');
await click('[data-testid=bell]'); // MUI popover: close by Escape instead
await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
await sleep(500);

// 2nd fault: Mark as read from the alert itself
check(await waitFor("!!document.querySelector('.MuiSnackbar-root .MuiAlert-message')", 200000), 'a second alert drops in');
const before = +(await count());
await click('[data-testid=toast-read]');
await sleep(1200);
check(+(await count()) === before - 1, 'marking the new alert as read takes it off the count');
check(!(await ev("!!document.querySelector('.MuiSnackbar-root .MuiAlert-message')")), 'and closes the alert');
await click('[data-testid=bell]');
await waitFor("!!document.querySelector('[data-testid=notif-panel]')");
check(await ev("document.querySelectorAll('[data-testid=notif-item]').length") === before - 1, 'the read alert is not in the panel; the ignored one is');

// mark the remaining one as read in the panel: panel empty, count gone
await click('[data-testid=mark-read]');
check(await waitFor("!!document.querySelector('[data-testid=notif-empty]')", 6000), 'once read, the panel is empty ("all caught up")');
check((await count()) === '0', 'and the unread number vanishes from the bell');
await shot('32-empty');
await send('Page.reload'); await sleep(3000);
await click('[data-testid=bell]');
await waitFor("!!document.querySelector('[data-testid=notif-panel]')");
check(await ev("!!document.querySelector('[data-testid=notif-empty]')") && (await count()) === '0', 'after a reload it is still empty (read state is saved)');
console.log(problems.length ? 'page errors: ' + problems.join(' | ') : 'no page errors');
check(problems.length === 0, 'no page errors');
ws.close(); chrome.kill();
process.exit(failed ? 1 : 0);
