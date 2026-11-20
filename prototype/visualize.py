"""Writes graph.html: the LangGraph diagram with a step-through player."""
import json

NODE_DOC = {
    "consume_event": "Takes the next event off the persisted event bus. Ends the run when the bus is empty.",
    "guardrails_route": "Hard rules, no LLM: borrower active? someone else owns it? daily contact cap hit? agent budget left? Then picks the agent (DPD rules). Skips or queues if a guardrail fails.",
    "assign": "Sets the owner lock and writes the cursor (current_borrower) before the agent starts.",
    "execute_agent": "Calls the stub agent. Catches crashes, timeouts and loops (no progress after 3 tries).",
    "validate_output": "Checks the agent's result against the agreed schema. A healthy-looking agent can still return garbage.",
    "monitor": "Monitor agent: reads health, cursor and contact log, then files request_recovery(action). It never changes state itself.",
    "recover": "Supervisor executes the monitor's request: RESUME, RESTART_SKIP_CURRENT, REROUTE or QUARANTINE.",
    "commit": "Saves borrower state, contact count and cursor (last_committed). Writes the trace entry.",
    "release_owner": "Clears the owner lock so another agent can act on this borrower.",
    "check_queue": "If an event was held while the agent ran, puts it back on the bus to go through guardrails again.",
}

TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Supervisor Graph</title>
<style>
:root{--bg:#fff;--fg:#1c1c1e;--mut:#6b6b70;--card:#f5f5f7;--line:#dcdce0;--acc:#2b6cb0;--hl:#f6c343;--bad:#c0392b;--ok:#2f855a}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#17181a;--fg:#ececee;--mut:#9a9aa0;--card:#222326;--line:#36373b;--acc:#63a4e6;--hl:#c9971c}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
header{padding:14px 16px;border-bottom:1px solid var(--line)}
h1{font-size:18px;margin:0}header p{margin:2px 0 0;color:var(--mut);font-size:13px}
main{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(300px,1fr);gap:16px;padding:16px}
@media(max-width:900px){main{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
#graph{background:#fff;overflow:auto;border-radius:8px;text-align:center}
#graph svg{max-width:100%;height:auto}
.controls{display:flex;gap:8px;align-items:center;margin-bottom:10px;flex-wrap:wrap}
button{background:var(--acc);color:#fff;border:0;border-radius:6px;padding:6px 12px;font:inherit;cursor:pointer}
button.sec{background:transparent;color:var(--fg);border:1px solid var(--line)}
input[type=range]{flex:1;min-width:120px}
h2{font-size:14px;margin:12px 0 4px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em}
#node{font-size:18px;font-weight:600}#acc{color:var(--mut)}
table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:3px 6px;border-bottom:1px solid var(--line);text-align:left}
.pill{padding:1px 8px;border-radius:99px;font-size:12px;border:1px solid var(--line)}
.NEEDS_REVIEW,.QUARANTINED,.CRASHED,.LOOPING,.MALFORMED,.UNRESPONSIVE{color:var(--bad);border-color:var(--bad)}
.RUNNING{color:var(--acc);border-color:var(--acc)}.ACTIVE,.IDLE{color:var(--ok)}
.trail{display:flex;flex-wrap:wrap;gap:3px}.trail span{font-size:11px;padding:1px 6px;border-radius:4px;background:var(--line)}
.trail span.cur{background:var(--hl);color:#000}
svg g.node.hl rect,svg g.node.hl polygon,svg g.node.hl path{fill:#f6c343 !important;stroke:#b7791f !important;stroke-width:3px !important}
svg g.node.hl .nodeLabel,svg g.node.hl span,svg g.node.hl p{color:#000 !important}
</style></head><body>
<header><h1>Supervisor graph: step-through</h1>
<p>Press Play or use the slider. The highlighted node is the one that just ran.</p></header>
<main>
<div class="card"><div id="graph">Loading graph...</div></div>
<div class="card">
 <div class="controls">
  <button id="prev" class="sec">&larr;</button><button id="play">Play</button><button id="next" class="sec">&rarr;</button>
  <input id="slider" type="range" min="0" value="0"><span id="count"></span>
 </div>
 <div><span id="node"></span> <span id="acc"></span></div>
 <p id="doc" style="color:var(--mut);margin:4px 0"></p>
 <h2>What happened</h2><div id="note"></div>
 <h2>Borrowers</h2><table id="borrowers"></table>
 <h2>Stub agents</h2><table id="agents"></table>
 <h2>Contact log (one line per message sent)</h2><div id="clog"></div>
 <h2>Path so far</h2><div id="trail" class="trail"></div>
</div></main>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"></script>
<script>
const MERMAID = __MERMAID__;
const TL = __TIMELINE__;
const DOC = __DOC__;
let i = 0, timer = null;
const $ = id => document.getElementById(id);
const pill = s => `<span class="pill ${s}">${s}</span>`;
$('slider').max = TL.length - 1;

function highlight(node){
  document.querySelectorAll('#graph g.node').forEach(g=>{
    const m = g.id.match(/^flowchart-(.+)-\d+$/);
    g.classList.toggle('hl', !!m && m[1]===node);
  });
}
function show(n){
  i = Math.max(0, Math.min(TL.length-1, n));
  const s = TL[i];
  $('slider').value = i; $('count').textContent = `${i+1}/${TL.length}`;
  $('node').textContent = s.node; $('acc').textContent = s.account_id ? ' on '+s.account_id : '';
  $('doc').textContent = DOC[s.node] || '';
  $('note').textContent = s.note;
  $('borrowers').innerHTML = '<tr><th>borrower</th><th>status</th><th>owner</th><th>contacts</th></tr>' +
    Object.entries(s.borrowers).map(([k,v])=>`<tr><td>${k}</td><td>${pill(v.status)}</td><td>${v.owner||'-'}</td><td>${v.contacts}</td></tr>`).join('');
  $('agents').innerHTML = '<tr><th>agent</th><th>status</th><th>current</th><th>last committed</th></tr>' +
    Object.entries(s.agents).map(([k,v])=>`<tr><td>${k}</td><td>${pill(v.status)}</td><td>${v.current||'-'}</td><td>${v.last_committed||'-'}</td></tr>`).join('');
  $('clog').textContent = s.contact_log.length ? s.contact_log.map(c=>`${c.account_id} <- ${c.agent}`).join(' | ') : 'none yet';
  $('trail').innerHTML = TL.slice(Math.max(0,i-14), i+1).map((t,k,a)=>`<span class="${k===a.length-1?'cur':''}">${t.node}${t.account_id?':'+t.account_id:''}</span>`).join('');
  highlight(s.node);
}
$('prev').onclick = ()=>show(i-1);
$('next').onclick = ()=>show(i+1);
$('slider').oninput = e=>show(+e.target.value);
$('play').onclick = ()=>{
  if(timer){clearInterval(timer);timer=null;$('play').textContent='Play';return;}
  $('play').textContent='Pause';
  timer = setInterval(()=>{ if(i>=TL.length-1){clearInterval(timer);timer=null;$('play').textContent='Play';return;} show(i+1); }, 900);
};
mermaid.initialize({startOnLoad:false, theme:'default', flowchart:{htmlLabels:true}});
mermaid.render('g', MERMAID).then(r=>{ $('graph').innerHTML = r.svg; show(0); })
  .catch(e=>{ $('graph').textContent = 'Could not render graph: '+e; show(0); });
</script></body></html>
"""


def write_html(mermaid_text, timeline, path):
    html = (TEMPLATE
            .replace("__MERMAID__", json.dumps(mermaid_text))
            .replace("__TIMELINE__", json.dumps(timeline))
            .replace("__DOC__", json.dumps(NODE_DOC)))
    open(path, "w").write(html)
