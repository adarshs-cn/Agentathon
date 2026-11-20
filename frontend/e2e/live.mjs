// End-to-end check of the live monitor and demo isolation in a real (headless) Chrome, with real clicks against the real API.
//   node e2e/live.mjs [outDir] [width] [height]
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
const tiles = () => ev("JSON.stringify([...document.querySelectorAll('[data-testid=stat-tile], .MuiPaper-root')].filter(e=>/Conflicting contacts|Faults recovered|Decision speed|Customers handled|Messages sent|Stopped or waiting/.test(e.innerText) && e.innerText.length<120).map(e=>e.innerText.replace(/\\s+/g,' ')))");
const api = async (p) => (await fetch(API + p)).json();

await send('Page.navigate', { url: UI });
check(await waitFor("!!document.querySelector('[data-testid=monitor-pill]')"), 'the header shows the monitor status');
check(await ev("document.querySelector('[data-testid=monitor-pill]').dataset.state") === 'monitoring', 'it says Monitoring live (we are inside the contact window)');
console.log('   pill:', await ev("document.querySelector('[data-testid=monitor-pill]').innerText"));
await shot('20-overview-live');

// the real monitor appends and runs events by itself; the tiles follow
const startDone = (await api('/api/overview')).counters.events_done;
check(await waitFor(`/Customers handled/.test(document.body.innerText)`), 'the six tiles are there');
const grew = await (async () => { for (let i = 0; i < 100; i++) { if ((await api('/api/overview')).counters.events_done > startDone + 2) return true; await sleep(1000); } return false; })();
check(grew, 'with nobody clicking anything, the monitor runs real events on its own');
const real = (await api('/api/overview')).counters;
console.log('   real counters now:', JSON.stringify({ done: real.events_done, sent: real.contacts_made, handled: real.borrowers_handled, blocked: real.blocked_or_deferred }));

// a demo run must not change them
const before = (await api('/api/overview')).counters;
const jr0 = (await api('/api/journeys')).total;
await fetch(`${API}/api/scenario/reset`, { method: 'POST' });
await fetch(`${API}/api/scenario/demo-01/run?pace_ms=0`, { method: 'POST' });
check(await (async () => { for (let i = 0; i < 120; i++) { if ((await api('/api/scenario')).done === 1) return true; await sleep(500); } return false; })(), 'the demo event runs (Workflow Studio)');
await sleep(1500);
const demo = await api('/api/scenario');
check(demo.done === 1, 'the walkthrough recorded its run');
const after = (await api('/api/overview')).counters;
check(after.faults_injected >= before.faults_injected && after.contacts_made - before.contacts_made === (after.events_done - before.events_done ? after.contacts_made - before.contacts_made : 0), 'demo run did not add to Messages sent beyond what the monitor itself did');
const jr1 = (await api('/api/journeys')).total;
check((await api('/api/journeys?page_size=200')).items.every((r) => !r.event_id.startsWith('demo-')), 'no demo run appears in Journey Runs');
check((await api('/api/overview/drilldown/borrowers')).rows.every((r) => !String(r.event_id).startsWith('demo-')), 'no demo run appears in the tile drawers');
await shot('21-after-demo-run');
console.log(problems.length ? 'page errors: ' + problems.join(' | ') : 'no page errors');
check(problems.length === 0, 'no page errors');
ws.close(); chrome.kill();
process.exit(failed ? 1 : 0);
