import { useCallback, useEffect, useRef, useState } from 'react';
import { Box, Typography, useMediaQuery } from '@mui/material';
import { tokens } from '../../theme/muiTheme';
import Edge from './Edge';
import Station from './Station';
import NodeHoverCard from './NodeHoverCard';
import { EDGES, STATIONS, VIEW_H, VIEW_W, boxes, edgeKey } from './layout';
import { deriveView } from './logic';

// Stop paths that are rare (an invalid event, a lost lock) appear only when they are taken.
const RARE = new Set(['event>stopped', 'ownership>stopped']);

const STYLE = `
@keyframes wf-flow { to { stroke-dashoffset: -28; } }
`;

export default function WorkflowGraph({ run, borrower }) {
  const reduced = useMediaQuery('(prefers-reduced-motion: reduce)');
  const wrap = useRef(null);
  const [hover, setHover] = useState(null);
  const view = deriveView(run);
  useEffect(() => setHover(null), [run.phase, run.eventId]);
  const running = run.phase === 'running';

  const enter = useCallback((id, el) => {
    const w = wrap.current?.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    if (!w) return;
    setHover({ id, left: r.left - w.left + r.width / 2, top: r.top - w.top - 8 });
  }, []);
  const leave = useCallback(() => setHover(null), []);

  const edgeState = (a, b) => {
    const key = edgeKey(a, b);
    if (run.activeEdge === key) return 'active';
    if (view.usedEdges.has(key)) return b === 'recover' || a === 'recover' ? 'warn' : 'done';
    return 'idle';
  };

  return (
    <Box ref={wrap} sx={{ position: 'relative', width: '100%', maxWidth: 1360, mx: 'auto' }}>
      <style>{STYLE}</style>
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        width="100%"
        role="group"
        aria-label="Supervisor workflow"
        style={{ display: 'block', overflow: 'visible' }}
        data-phase={run.phase}
      >
        <defs>
          {[['idle', tokens.dividerGrey], ['on', tokens.navbarBg], ['warn', '#c9a100']].map(([id, fill]) => (
            <marker key={id} id={`arrow-${id}`} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill={fill} />
            </marker>
          ))}
        </defs>
        {EDGES.filter(([a, b]) => !RARE.has(edgeKey(a, b)) || edgeState(a, b) !== 'idle').map(([a, b]) => (
          <Edge key={`${a}>${b}`} from={a} to={b} state={edgeState(a, b)} reduced={reduced} />
        ))}
        {STATIONS.map((s) => (
          <Station key={s.id} def={s} box={boxes[s.id]} view={view.stations[s.id]} running={running} reduced={reduced} onEnter={enter} onLeave={leave} />
        ))}
      </svg>
      {hover && (
        <NodeHoverCard
          title={STATIONS.find((s) => s.id === hover.id).name}
          borrower={borrower}
          view={view.stations[hover.id]}
          left={hover.left}
          top={hover.top}
        />
      )}
      <Typography sx={{ position: 'absolute', right: 4, bottom: 0, fontSize: 10.5, color: tokens.statLabelGrey }}>
        Hover a step to see what happened there
      </Typography>
    </Box>
  );
}
