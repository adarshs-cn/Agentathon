// End-to-end check of the Workflow Studio (graph from the compiled LangGraph, zoom, trace pad streaming, hover) in a real (headless) Chrome, with real clicks against the real API.
//   node e2e/studio.mjs [outDir] [width] [height]
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
const api = async (p, opt) => (await fetch(API + p, opt)).json();
const EV = process.env.STUDIO_EVENT || 'demo-13';

await fetch(`${API}/api/scenario/reset`, { method: 'POST' });
const g = await api('/api/graph');

// the Overview no longer carries the walkthrough
await send('Page.navigate', { url: UI });
await waitFor("/Customers handled/.test(document.body.innerText)");
check(!(await ev("!!document.querySelector('[data-testid=event-picker]') || /Workflow walkthrough|Message sent\b(?! )|What happened/.test(document.body.innerText.replace('Messages sent',''))")), 'the Overview has only the live tiles (no walkthrough, phone or step log)');

await send('Page.navigate', { url: UI + 'studio' });
check(await waitFor(`document.querySelectorAll('[data-node]').length === ${g.nodes.length}`), `the studio draws every node of the compiled graph (${g.nodes.length})`);
check(await ev(`document.querySelectorAll('[data-edge]').length`) === g.edges.length, `and every edge (${g.edges.length})`);
check(await ev("document.querySelectorAll('[data-node] text').length > 0 && [...document.querySelectorAll('[data-node]')].filter(n=>/AI/.test(n.textContent)).length") === 5, 'five steps carry the AI badge');
await shot('40-studio-idle');

// pick the scenario and run it
await ev(`document.querySelector('[data-testid="event-picker"] [role=combobox]').dispatchEvent(new MouseEvent('mousedown',{bubbles:true}))`);
await sleep(400); await ev(`document.querySelector('li[data-event="${EV}"]').click()`); await sleep(700);
await ev(`window.__zoom = []; window.__pad = []; setInterval(() => { const c = document.querySelector('[data-testid=camera]'); window.__zoom.push([c.dataset.focus, +c.dataset.scale]);
  const t = document.querySelector('[data-testid=trace-live] [data-testid=trace-text]'); if (t) window.__pad.push([document.querySelector('[data-testid=trace-live]').dataset.node, t.innerText.length]); }, 150)`);
const runStarted = Date.now();
await ev("document.querySelector('[data-testid=run]').click()");
check(await waitFor("document.querySelector('[data-testid=camera]').dataset.scale > 1.5", 15000), 'on Run the camera zooms in on the working step');
await sleep(400);
const a = await ev(`(() => { const act = document.querySelector('[data-node][data-state=active]'); const pend = [...document.querySelectorAll('[data-node][data-state=pending]')];
  return { active: act && act.dataset.node, scale: act && +act.querySelector('[data-scale]').dataset.scale,
           pendingOpacity: pend.length ? Math.max(...pend.map(p => +getComputedStyle(p.querySelector('[data-scale]')).opacity)) : null, pending: pend.length }; })()`);
console.log('   while running:', JSON.stringify(a));
check(a.active && a.scale >= 1.25, 'the working step is enlarged on top of the zoom');
check(a.pending > 0 && a.pendingOpacity <= 0.15, 'steps not reached yet fade to near-transparent');
await shot('41-running-a');
check(await waitFor("!!document.querySelector('[data-testid=trace-live] [data-testid=trace-text]') && document.querySelector('[data-testid=trace-live] [data-testid=trace-text]').innerText.length > 20", 20000), 'the trace pad streams text for the working step');
check(await waitFor("document.querySelector('[data-testid=trace-live]')?.dataset.node === 'route'", 60000), 'the route step comes up');
await sleep(2500);
await shot('42-running-route');
check(await waitFor("!!document.querySelector('[data-testid=studio-outcome]')", 400000), 'the run finishes');
const zoom = await ev('window.__zoom'); const pad = await ev('window.__pad');
console.log(`   the run took ${Math.round((Date.now() - runStarted) / 1000)} s`);
const focuses = [...new Set(zoom.filter(z => z[1] > 1.5).map(z => z[0]))];
console.log('   camera followed:', focuses.join(' > '));
check(focuses.length >= 8, 'the camera followed the steps one by one');
const grew = {}; pad.forEach(([n, l]) => { grew[n] = Math.max(grew[n] || 0, l); });
const streamedNodes = Object.keys(grew).filter(n => grew[n] > 0);
console.log('   streamed in the pad:', streamedNodes.join(', '));
check(streamedNodes.length >= 8, 'every visited step streamed into the pad');
check(await ev("document.querySelector('[data-testid=camera]').dataset.scale") === '1', 'after the run the camera zooms back out');
await sleep(1000);
await shot('43-done');

// saved traces: LLM steps really came from the model
const steps = (await api(`/api/scenario/${EV}/steps`)).steps;
const llmSteps = steps.filter(s => ['validate_event', 'route', 'assign', 'monitor', 'recover'].includes(s.node));
console.log('   sources:', steps.map(s => `${s.node}:${s.trace?.source}`).join(' '));
check(steps.every(s => s.trace && s.trace.text), 'every step saved its trace');
check(llmSteps.length && llmSteps.every(s => s.trace.source === 'llm' || s.trace.source === 'rules-fallback'), 'the AI steps were explained by the LLM (or fell back)');
check(llmSteps.some(s => s.trace.source === 'llm'), 'at least one AI step got a real LLM explanation');

// hover after the run: node enlarges, others dim, pad shows the saved text (no streaming)
const box = await ev(`(() => { const r = document.querySelector('[data-node="route"] rect').getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()`);
await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: box[0], y: box[1] });
check(await waitFor("document.querySelector('[data-node=route]').dataset.hovered === '1'", 3000), 'hovering a step after the run emphasises it');
await sleep(800);
const h = await ev(`(() => ({ scale: +document.querySelector('[data-node=route] [data-scale]').dataset.scale,
  other: +getComputedStyle(document.querySelector('[data-node=guardrails] [data-scale]')).opacity,
  saved: document.querySelector('[data-testid=trace-saved]')?.dataset.node, live: !!document.querySelector('[data-testid=trace-live]'),
  text: (document.querySelector('[data-testid=trace-saved] [data-testid=trace-text]')||{}).innerText || '' }))()`);
console.log('   hover:', JSON.stringify({ ...h, text: h.text.slice(0, 120) }));
check(h.scale >= 1.4 && h.other < 0.3, 'the hovered step grows a lot and the others dim');
check(h.saved === 'route' && !h.live && h.text.length > 20, 'the pad shows the saved trace of that step (no streaming)');
await sleep(700);
await shot('44-hover-route');

// click pins it: the trace stays after the cursor leaves; clicking the canvas unpins
await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: box[0], y: box[1], button: 'left', clickCount: 1 });
await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: box[0], y: box[1], button: 'left', clickCount: 1 });
await sleep(300);
const corner = await ev(`(() => { const r = document.querySelector('[data-testid=studio-graph]').getBoundingClientRect(); return [r.x + 30, r.y + r.height - 30]; })()`);
await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: corner[0], y: corner[1] });
await sleep(900);
check(await ev("document.querySelector('[data-node=route]').dataset.pinned") === '1', 'clicking a step pins it');
check(await ev("document.querySelector('[data-testid=trace-saved]')?.dataset.node") === 'route', 'its trace stays in the pad after the cursor moves away');
await shot('45-pinned');
await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: corner[0], y: corner[1], button: 'left', clickCount: 1 });
await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: corner[0], y: corner[1], button: 'left', clickCount: 1 });
await sleep(500);
check(await ev("document.querySelector('[data-node=route]').dataset.pinned") === '0', 'clicking the empty canvas unpins it');
console.log(problems.length ? 'page errors: ' + problems.join(' | ') : 'no page errors');
check(problems.length === 0, 'no page errors');
ws.close(); chrome.kill();
process.exit(failed ? 1 : 0);
