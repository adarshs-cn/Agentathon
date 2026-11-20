import { useEffect, useRef, useState } from 'react';
import { Box, Stack, Typography } from '@mui/material';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import RuleIcon from '@mui/icons-material/Rule';
import CheckIcon from '@mui/icons-material/Check';
import { C } from './studioTheme';

const MONO = 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace';

function Badge({ visit }) {
  const llm = visit.source === 'llm' || (visit.status === 'active' && visit.llm);
  const fallback = visit.source === 'rules-fallback';
  const Icon = llm ? AutoAwesomeIcon : RuleIcon;
  return (
    <Stack direction="row" spacing={0.5} alignItems="center" sx={{
      px: 0.9, py: 0.2, borderRadius: 10, fontSize: 10.5, fontWeight: 700, letterSpacing: 0.3,
      color: llm ? C.violet : C.cyan, background: llm ? C.violetBg : C.tealBg, border: `1px solid ${llm ? C.violet : C.cyan}55`,
    }}>
      <Icon sx={{ fontSize: 12 }} />
      <span>{fallback ? 'RULE CHECK (model unavailable)' : llm ? 'LLM REASONING' : 'RULE CHECK'}</span>
    </Stack>
  );
}

// The model's hidden reasoning: shown as a live "reasoning" meter; the raw text is kept and can be opened on request.
function Thinking({ visit, live }) {
  const [open, setOpen] = useState(false);
  const tokens = Math.max(1, Math.round(visit.think.length / 4));
  const thinkingNow = live && !visit.text;
  return (
    <Box sx={{ mb: 1 }} data-testid="trace-think">
      <Stack direction="row" spacing={1} alignItems="center">
        <Typography sx={{ fontSize: 11.5, color: C.violet }} className={thinkingNow ? 'studio-blink' : undefined}>
          {thinkingNow ? `Reasoning over the facts… ~${tokens} tokens` : `Reasoned over the facts (~${tokens} tokens)`}
        </Typography>
        {!live && (
          <Typography component="button" onClick={() => setOpen((o) => !o)} sx={{ fontSize: 11, color: C.muted, background: 'none',
            border: 'none', cursor: 'pointer', textDecoration: 'underline', p: 0 }}>
            {open ? 'hide raw thinking' : 'show raw thinking'}
          </Typography>
        )}
      </Stack>
      {thinkingNow && (
        <Box sx={{ mt: 0.8, height: 3, borderRadius: 2, background: C.violetBg, overflow: 'hidden' }}>
          <Box className="studio-scan" sx={{ width: '35%', height: '100%', background: C.violet }} />
        </Box>
      )}
      {open && (
        <Box sx={{ fontFamily: MONO, fontSize: 11, lineHeight: 1.5, color: C.muted, fontStyle: 'italic', borderLeft: `2px solid ${C.violet}66`,
          pl: 1.2, mt: 0.8, maxHeight: 160, overflow: 'auto', whiteSpace: 'pre-wrap' }}>
          {visit.think}
        </Box>
      )}
    </Box>
  );
}

function Visit({ visit, meta, expanded, live }) {
  const name = meta?.label || visit.node;
  if (!expanded) {
    return (
      <Stack direction="row" spacing={1} alignItems="center" sx={{ py: 0.6, opacity: 0.75 }} data-testid="trace-done">
        <CheckIcon sx={{ fontSize: 14, color: visit.fault ? C.red : visit.stop ? C.amber : C.green }} />
        <Typography sx={{ fontSize: 12, color: C.text, fontWeight: 600, minWidth: 110 }}>{name}</Typography>
        <Typography noWrap sx={{ fontSize: 11.5, color: C.sub }}>{visit.did || visit.label}</Typography>
      </Stack>
    );
  }
  return (
    <Box sx={{ py: 1.2 }} data-testid={live ? 'trace-live' : 'trace-saved'} data-node={visit.node}>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
        <Typography sx={{ fontSize: 14, color: C.text, fontWeight: 700 }}>{name}</Typography>
        <Badge visit={visit} />
        {live && <Typography sx={{ fontSize: 11, color: C.cyan }} className="studio-blink">processing…</Typography>}
      </Stack>
      {visit.think && <Thinking visit={visit} live={live} />}
      <Box data-testid="trace-text" sx={{ fontFamily: MONO, fontSize: 12.5, lineHeight: 1.65, color: C.text, whiteSpace: 'pre-wrap' }}>
        {visit.text}
        {live && <span className="studio-cursor">▍</span>}
      </Box>
    </Box>
  );
}

// The trace pad: the working node's stream while a run is going; a node's saved stream on hover afterwards.
export default function TracePad({ run, hover, pinned, onUnpin, metaById, outcome }) {
  const scroller = useRef(null);
  const focused = hover ? run.visits.filter((v) => v.node === hover) : null;
  const total = run.visits.reduce((n, v) => n + v.text.length + v.think.length, 0);

  useEffect(() => {
    const el = scroller.current;
    if (el && !hover) el.scrollTop = el.scrollHeight;
  }, [total, run.visits.length, hover]);

  let body;
  if (focused) {
    body = focused.length ? (
      focused.map((v) => <Visit key={v.seq} visit={v} meta={metaById[v.node]} expanded live={false} />)
    ) : (
      <Typography sx={{ fontSize: 12.5, color: C.sub, py: 2 }}>
        {metaById[hover]?.label || hover}: {metaById[hover]?.what || ''}. This step was not reached in this run.
      </Typography>
    );
  } else if (!run.visits.length) {
    body = (
      <Typography sx={{ fontSize: 12.5, color: C.sub, py: 2, lineHeight: 1.7 }}>
        Pick a scenario and press <b style={{ color: C.text }}>Run demo</b>. Each step of the supervisor will light up, and its
        reasoning streams here as it works. Steps marked <span style={{ color: C.violet }}>AI</span> are explained by the LLM;
        the others show their rule check. The rules always make the decision.
      </Typography>
    );
  } else {
    body = run.visits.map((v) => {
      const live = run.phase === 'running' && v.seq === run.activeSeq;
      return <Visit key={v.seq} visit={v} meta={metaById[v.node]} expanded={live} live={live} />;
    });
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', background: C.panel, borderRadius: 3, border: `1px solid ${C.grid}` }}
      data-testid="trace-pad">
      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ px: 2, py: 1.3, borderBottom: `1px solid ${C.grid}` }}>
        <Typography sx={{ fontSize: 12, letterSpacing: 1.2, color: C.sub, fontWeight: 700 }}>
          {focused ? `TRACE · ${(metaById[hover]?.label || hover).toUpperCase()}` : 'TRACE PAD'}
        </Typography>
        <Typography sx={{ fontSize: 11, color: C.muted }}>
          {run.phase === 'running' ? 'live' : pinned ? (
            <span>pinned · <Typography component="button" onClick={onUnpin} data-testid="unpin" sx={{ fontSize: 11, color: C.cyan, background: 'none',
              border: 'none', cursor: 'pointer', textDecoration: 'underline', p: 0 }}>unpin</Typography></span>
          ) : run.phase === 'done' ? (focused ? 'saved from the run · click to pin' : 'hover a step to read it, click to pin') : ''}
        </Typography>
      </Stack>
      <Box ref={scroller} sx={{ flex: 1, overflow: 'auto', px: 2, py: 0.5 }}>
        {body}
        {!focused && run.phase === 'done' && outcome}
      </Box>
      <style>{`
        .studio-cursor { color: ${C.cyan}; animation: studio-blink 1s steps(2, start) infinite; }
        .studio-blink { animation: studio-blink 1.2s ease-in-out infinite; }
        @keyframes studio-blink { 50% { opacity: 0.2; } }
        .studio-scan { animation: studio-scan 1.1s ease-in-out infinite; }
        @keyframes studio-scan { 0% { transform: translateX(-100%); } 100% { transform: translateX(300%); } }
        @media (prefers-reduced-motion: reduce) { .studio-cursor, .studio-blink, .studio-scan { animation: none; } }
      `}</style>
    </Box>
  );
}
