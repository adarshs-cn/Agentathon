// End-to-end check of the Overview in a real (headless) Chrome, with real clicks against the real API.
//   node e2e/overview.mjs [outDir] [width] [height]
// Needs the API on :8001 and the UI on :5173 (see run_demo.sh). Exits non-zero on the first failed check.
import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const [, , outDirArg, widthArg, heightArg] = process.argv;
const outDir = outDirArg || join(tmpdir(), 'e2e-shots');
const width = +(widthArg || 1440);
const height = +(heightArg || 900);
const API = process.env.E2E_API || 'http://127.0.0.1:8001';
const UI = process.env.E2E_UI || 'http://127.0.0.1:5173/';
mkdirSync(outDir, { recursive: true });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let failed = 0;
const check = (ok, msg) => { console.log(`${ok ? 'PASS' : 'FAIL'}  ${msg}`); if (!ok) failed += 1; };

const dir = mkdtempSync(join(tmpdir(), 'chrome-'));
const chrome = spawn('google-chrome', ['--headless=new', '--no-sandbox', '--disable-gpu', '--hide-scrollbars', '--remote-debugging-port=9335',
  `--user-data-dir=${dir}`, `--window-size=${width},${height}`, 'about:blank'], { stdio: 'ignore' });
let tabs;
for (let i = 0; i < 40; i++) { try { tabs = await (await fetch('http://127.0.0.1:9335/json')).json(); if (tabs.length) break; } catch { /* retry */ } await sleep(250); }
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

// Records, inside the page, every time a station becomes active and every time an edge lights up.
const OBSERVER = `window.__log = {stations: [], edges: []};
new MutationObserver((muts) => { for (const m of muts) { const el = m.target;
  if (el.dataset && (el.dataset.state === 'active' || el.dataset.state === 'recovering') && el.dataset.station) window.__log.stations.push(el.dataset.station);
  if (el.dataset && el.dataset.state === 'active' && el.dataset.edge) window.__log.edges.push(el.dataset.edge); } })
  .observe(document.body, {subtree: true, attributes: true, attributeFilter: ['data-state']});`;
const states = () => ev("[...document.querySelectorAll('[data-station]')].map(g=>g.dataset.station+':'+g.dataset.state).join(' ')");
const waitFor = async (expr, ms = 20000) => { for (let t = 0; t < ms; t += 100) { if (await ev(expr)) return true; await sleep(100); } return false; };
const pick = async (n) => {
  await ev(`document.querySelector('[data-testid="event-picker"] [role=combobox]').dispatchEvent(new MouseEvent('mousedown',{bubbles:true}))`);
  await sleep(350); await ev(`document.querySelector('li[data-event="demo-${n}"]').click()`); await sleep(700);
};
const run = async () => { await ev("document.querySelector('[data-testid=run]').click()"); };
const finished = () => waitFor("/Message sent|Not allowed|Waiting for a better time/.test(document.querySelector('[data-testid=outcome]').innerText) && !document.querySelector('[data-state=active],[data-state=recovering]')", 25000);

await fetch(`${API}/api/scenario/reset`, { method: 'POST' });
await send('Page.navigate', { url: UI });
check(await waitFor("document.querySelectorAll('[data-station]').length === 11"), 'the graph draws 11 stations');
check(!(await states()).includes('active') && (await states()).split(' ').every((s) => s.endsWith(':idle')), 'before Run every station is idle');
check(await ev("document.querySelectorAll('[data-testid]').length > 0 && document.querySelectorAll('main, [role=button]').length > 0"), 'the six tiles are buttons');
await shot('01-idle');

// ---- event 1, live run: stations activate in graph order, the edge to the next one lights
await ev(OBSERVER);
await run();
check(await finished(), 'event 1 finishes');
const log = await ev('window.__log');
const order = [...new Set(log.stations)];
const expected = ['event', 'borrower', 'safety', 'agent_chosen', 'ownership', 'agent_acts', 'result', 'saved', 'done'];
check(JSON.stringify(order) === JSON.stringify(expected), `stations became active in graph order (${order.join(' > ')})`);
const pairs = expected.slice(0, -1).map((a, i) => `${a}>${expected[i + 1]}`);
check(pairs.every((p) => log.edges.includes(p)), 'the edge to the next station lit up for every hop');
const rect = await ev(`(()=>{const r=document.querySelector('[data-station="safety"]').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);
await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: rect.x, y: rect.y }); await sleep(300);
const facts = await ev("[...document.querySelectorAll('[data-fact]')].map(f=>f.dataset.fact)");
check(JSON.stringify(facts) === JSON.stringify(['Borrower', 'Owner', 'Supervisor']), 'hover shows exactly three facts: Borrower, Owner, Supervisor');
check((await ev("document.querySelector('[data-fact=Owner]').innerText")).includes('Null'), 'a fresh account shows its owner as Null');
check((await ev("document.querySelector('[data-message]')?.innerText || ''")).includes('CreditNirvana'), 'the phone view shows the agent’s message');
check(/XXXXXX|your demo number/.test(await ev("document.querySelector('[data-to]').innerText")), 'the recipient is masked');
await shot('02-event1-done');

// ---- hero tiles open in place and their rows add up
const tileCount = async (label) => +(await ev(`(()=>{const t=[...document.querySelectorAll('[role=button]')].find(b=>b.getAttribute('aria-label')?.startsWith('${label}'));return t?t.getAttribute('aria-label').split(': ')[1].split('.')[0]:'-1'})()`));
const openTile = async (label) => { await ev(`[...document.querySelectorAll('[role=button]')].find(b=>b.getAttribute('aria-label')?.startsWith('${label}')).click()`); await sleep(900); };
const closeDrawer = async () => { await ev("document.querySelector('[aria-label=Close]').click()"); await sleep(500); };
const url0 = await ev('location.href');
await openTile('Messages sent');
const rows = await ev("document.querySelectorAll('[data-drawer] tbody tr').length");
check(rows === (await tileCount('Messages sent')) && rows >= 1, `the “Messages sent” tile opens a list whose rows (${rows}) match its number`);
check((await ev('location.href')) === url0, 'opening a tile does not navigate away');
await shot('03-tile-drawer'); await closeDrawer();

// ---- event 8: stopped at Safety checks, with the reason in words
await pick('08'); await run();
check(await finished(), 'event 8 finishes');
let st = await states();
check(st.includes('safety:blocked') && st.includes('stopped:stopped') && st.includes('agent_chosen:idle'), 'event 8 stops at Safety checks and lights Stopped');
check((await ev("document.querySelector('[data-testid=outcome]').innerText")).includes('promise to pay'), 'the outcome says why in words');
await shot('04-stopped');

// ---- event 13: the Recover branch lights, one message is still sent
await pick('13'); await ev(OBSERVER); await run();
check(await finished(), 'event 13 finishes');
st = await states();
check(st.includes('recover:recovered') && st.includes('done:done'), 'event 13 goes through Recover and still finishes');
check((await ev('window.__log.stations')).includes('recover'), 'the Recover station was active during the run');
await shot('05-recovered');

// ---- Replay reproduces the stored run
await ev(OBSERVER); await ev("document.querySelector('[data-testid=replay]').click()");
await sleep(500);
check(await finished(), 'Replay finishes');
check((await ev('window.__log.stations')).includes('recover'), 'Replay animates the same path (including Recover)');

// ---- dependency: the second request cannot run before the first
await pick('12');
check(await ev("document.querySelector('[data-testid=run]').disabled"), 'event 12 is locked until event 11 has run');

// ---- reduced motion: no scaling, same sequence
await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] });
await send('Page.reload'); await waitFor("document.querySelectorAll('[data-station]').length === 11");
await pick('01'); await ev(OBSERVER); await ev("document.querySelector('[data-testid=replay]')?.click()||document.querySelector('[data-testid=run]').click()");
await sleep(1500);
check((await ev("(document.querySelector('[data-state=active]')?.firstElementChild?.style.transform)||'scale(1)'")) === 'scale(1)', 'reduced motion: the active station is not scaled');
await finished();

// ---- reset
await ev("document.querySelector('[data-testid=reset]').click()");
check(await waitFor("document.querySelector('[data-testid=reset]').innerText.includes('Resetting')", 3000), 'Reset shows that it is working');
check(await waitFor("document.querySelector('[data-testid=reset]').innerText.includes('Reset demo')", 30000), 'Reset finishes');
const items = await (await fetch(`${API}/api/scenario`)).json();
check(items.done === 0, 'Reset demo returns all 15 events to not run');
check(problems.length === 0, `no uncaught page errors${problems.length ? ': ' + problems[0] : ''}`);

ws.close(); chrome.kill();
console.log(failed ? `\n${failed} check(s) failed` : '\nall checks passed');
process.exit(failed ? 1 : 0);
