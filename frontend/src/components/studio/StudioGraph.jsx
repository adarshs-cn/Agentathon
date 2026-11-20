import { useMemo } from 'react';
import { Box } from '@mui/material';
import PlayCircleOutlineIcon from '@mui/icons-material/PlayCircleOutline';
import FactCheckOutlinedIcon from '@mui/icons-material/FactCheckOutlined';
import PersonSearchOutlinedIcon from '@mui/icons-material/PersonSearchOutlined';
import ShieldOutlinedIcon from '@mui/icons-material/ShieldOutlined';
import AltRouteIcon from '@mui/icons-material/AltRoute';
import LockOutlinedIcon from '@mui/icons-material/LockOutlined';
import WhatsAppIcon from '@mui/icons-material/WhatsApp';
import EmailOutlinedIcon from '@mui/icons-material/EmailOutlined';
import PhoneInTalkOutlinedIcon from '@mui/icons-material/PhoneInTalkOutlined';
import RuleIcon from '@mui/icons-material/Rule';
import MonitorHeartOutlinedIcon from '@mui/icons-material/MonitorHeartOutlined';
import AutorenewIcon from '@mui/icons-material/Autorenew';
import SaveOutlinedIcon from '@mui/icons-material/SaveOutlined';
import LockOpenOutlinedIcon from '@mui/icons-material/LockOpenOutlined';
import TaskAltIcon from '@mui/icons-material/TaskAlt';
import FlagOutlinedIcon from '@mui/icons-material/FlagOutlined';
import { POS, NODE, TERMINAL_R, VIEW, edgePath, cameraOn } from './studioLayout';
import { edgeState, nodeState } from './studioLogic';
import { C } from './studioTheme';

const ICONS = {
  __start__: PlayCircleOutlineIcon, validate_event: FactCheckOutlinedIcon, load_customer: PersonSearchOutlinedIcon,
  guardrails: ShieldOutlinedIcon, route: AltRouteIcon, assign: LockOutlinedIcon, whatsapp: WhatsAppIcon,
  email: EmailOutlinedIcon, voice: PhoneInTalkOutlinedIcon, validate_output: RuleIcon, monitor: MonitorHeartOutlinedIcon,
  recover: AutorenewIcon, commit: SaveOutlinedIcon, release: LockOpenOutlinedIcon, close_event: TaskAltIcon, __end__: FlagOutlinedIcon,
};
const ZOOM = 1.9; // camera zoom on the working node
const ACTIVE_SCALE = 1.3; // the working node itself grows on top of the zoom
const HOVER_SCALE = 2;

const STROKE = { idle: C.line, pending: C.line, done: C.green, active: C.cyan, fault: C.red, stop: C.amber };

function Node({ meta, state, hovered, pinned, dimmedByHover, onHover, onPin, reduced, label }) {
  const id = meta.id;
  const [x, y] = POS[id] || [0, 0];
  const Icon = ICONS[id] || TaskAltIcon;
  const terminal = id.startsWith('__');
  const big = state === 'active' ? ACTIVE_SCALE : hovered ? HOVER_SCALE : 1;
  const opacity = dimmedByHover ? 0.18 : state === 'pending' ? 0.1 : state === 'done' || state === 'stop' ? 0.62 : 1;
  const stroke = hovered && state === 'idle' ? C.cyan : STROKE[state] || C.line;
  const glow = state === 'active' || hovered ? 'url(#studio-glow)' : undefined;
  const t = reduced ? 'none' : 'transform 650ms cubic-bezier(.2,.8,.2,1), opacity 450ms ease';
  return (
    <g transform={`translate(${x} ${y})`} data-node={id} data-state={state} data-hovered={hovered ? '1' : '0'} data-pinned={pinned ? '1' : '0'}
      onMouseEnter={() => onHover(id)} onMouseLeave={() => onHover(null)} onClick={(e) => { e.stopPropagation(); onPin(id); }}
      style={{ cursor: 'pointer' }}>
      <g style={{ transform: `scale(${big})`, transformOrigin: '0px 0px', opacity, transition: t }} data-scale={big}>
        {pinned && (
          <rect x={-NODE.w / 2 - 7} y={-NODE.h / 2 - 7} width={NODE.w + 14} height={NODE.h + 14} rx={20}
            fill="none" stroke={C.violet} strokeWidth={1.5} strokeDasharray="4 4" />
        )}
        {state === 'active' && !reduced && (
          <rect x={-NODE.w / 2 - 10} y={-NODE.h / 2 - 10} width={NODE.w + 20} height={NODE.h + 20} rx={22}
            fill="none" stroke={C.cyan} strokeWidth={2} className="studio-ring" />
        )}
        {terminal ? (
          <circle r={TERMINAL_R} fill={C.node} stroke={stroke} strokeWidth={2} filter={glow} />
        ) : (
          <rect x={-NODE.w / 2} y={-NODE.h / 2} width={NODE.w} height={NODE.h} rx={16} fill={C.node} stroke={stroke}
            strokeWidth={state === 'active' ? 2.5 : 1.5} filter={glow} />
        )}
        <foreignObject x={terminal ? -14 : -NODE.w / 2 + 12} y={terminal ? -14 : -15} width={28} height={28} style={{ pointerEvents: 'none' }}>
          <Icon sx={{ fontSize: 26, color: state === 'active' ? C.cyan : state === 'fault' ? C.red : C.text, display: 'block' }} />
        </foreignObject>
        {!terminal && (
          <>
            <text x={-NODE.w / 2 + 48} y={-5} fill={C.text} fontSize={17} fontWeight={600} style={{ pointerEvents: 'none' }}>{meta.label}</text>
            <text x={-NODE.w / 2 + 48} y={17} fill={C.sub} fontSize={12.5} style={{ pointerEvents: 'none' }}>
              {(label || (meta.kind === 'channel' ? 'Channel agent' : meta.llm ? 'LLM explained' : 'Rule check')).slice(0, 20)}
            </text>
            {meta.llm && (
              <g transform={`translate(${NODE.w / 2 - 26} ${-NODE.h / 2 + 2})`} style={{ pointerEvents: 'none' }}>
                <rect x={-14} y={-9} width={30} height={17} rx={8.5} fill={C.violetBg} stroke={C.violet} strokeWidth={1} />
                <text x={1} y={3.5} fill={C.violet} fontSize={9.5} fontWeight={700} textAnchor="middle">AI</text>
              </g>
            )}
          </>
        )}
        {terminal && (
          <text y={TERMINAL_R + 22} fill={C.sub} fontSize={14} textAnchor="middle" style={{ pointerEvents: 'none' }}>{meta.label}</text>
        )}
      </g>
    </g>
  );
}

function Edge({ e, state, touchesHover, hoverActive, reduced }) {
  const d = edgePath(e.from, e.to);
  const key = `${e.from}>${e.to}`;
  const on = state === 'live' || state === 'travelled';
  let stroke = C.line;
  let opacity = 0.38;
  let width = 1.4;
  if (state === 'dim') opacity = 0.06;
  if (on) { stroke = C.cyan; opacity = state === 'live' ? 1 : 0.7; width = state === 'live' ? 3 : 2.2; }
  if (hoverActive) { opacity = touchesHover ? 0.95 : 0.05; if (touchesHover) { stroke = C.cyan; width = 2.4; } }
  const marker = on || (hoverActive && touchesHover) ? 'url(#studio-arrow-on)' : 'url(#studio-arrow)';
  return (
    <g data-edge={key} data-estate={state}>
      <path d={d} fill="none" stroke={stroke} strokeWidth={width} opacity={opacity} markerEnd={marker}
        strokeDasharray={on ? '7 6' : e.conditional ? '5 6' : undefined}
        className={on && !reduced ? 'studio-flow' : undefined}
        style={{ transition: reduced ? 'none' : 'opacity 400ms ease, stroke 400ms ease' }} />
      {state === 'live' && !reduced && (
        <circle r={6} fill={C.cyan} filter="url(#studio-glow)">
          <animateMotion dur="0.9s" repeatCount="indefinite" path={d} />
        </circle>
      )}
    </g>
  );
}

export default function StudioGraph({ graph, run, hover, pinned, onHover, onPin, reduced }) {
  const running = run.phase === 'running';
  const cam = running && run.active ? cameraOn(run.active, ZOOM) : { x: 0, y: 0, scale: 1 };
  const focus = hover || pinned;            // hovering previews a step; clicking pins it
  const hoverActive = !running && !!focus;
  const labels = useMemo(() => {
    const m = {};
    run.visits.forEach((v) => { if (v.label) m[v.node] = v.label; });
    return m;
  }, [run.visits]);

  return (
    <Box sx={{ position: 'relative', width: '100%', aspectRatio: `${VIEW.w} / ${VIEW.h}`, background: C.bg, borderRadius: 3, overflow: 'hidden' }}>
      <svg viewBox={`0 0 ${VIEW.w} ${VIEW.h}`} width="100%" height="100%" preserveAspectRatio="xMidYMid meet" data-testid="studio-graph"
        role="img" aria-label="The supervisor's LangGraph workflow">
        <defs>
          <pattern id="studio-dots" width="28" height="28" patternUnits="userSpaceOnUse">
            <circle cx="2" cy="2" r="1.2" fill={C.grid} />
          </pattern>
          <filter id="studio-glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="6" result="b" />
            <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          <marker id="studio-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill={C.line} />
          </marker>
          <marker id="studio-arrow-on" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill={C.cyan} />
          </marker>
          <style>{`
            .studio-flow { animation: studio-dash 0.8s linear infinite; }
            @keyframes studio-dash { to { stroke-dashoffset: -26; } }
            .studio-ring { animation: studio-pulse 1.4s ease-in-out infinite; transform-origin: 0 0; }
            @keyframes studio-pulse { 0%,100% { opacity: .9; } 50% { opacity: .25; } }
          `}</style>
        </defs>
        <rect width={VIEW.w} height={VIEW.h} fill="url(#studio-dots)" onClick={() => onPin(null)} data-testid="canvas" />
        <g data-testid="camera" data-scale={cam.scale} data-focus={running ? run.active || '' : ''}
          style={{ transform: `translate(${cam.x}px, ${cam.y}px) scale(${cam.scale})`, transformOrigin: '0 0',
            transition: reduced ? 'none' : 'transform 900ms cubic-bezier(.2,.8,.2,1)' }}>
          {(graph?.edges || []).map((e) => {
            const key = `${e.from}>${e.to}`;
            return (
              <Edge key={key} e={e} state={edgeState(run, key)} reduced={reduced} hoverActive={hoverActive}
                touchesHover={hoverActive && (e.from === focus || e.to === focus)} />
            );
          })}
          {(graph?.nodes || []).map((n) => (
            <Node key={n.id} meta={n} state={nodeState(run, n.id)} label={labels[n.id]} reduced={reduced}
              hovered={hoverActive && focus === n.id} pinned={!running && pinned === n.id} dimmedByHover={hoverActive && focus !== n.id}
              onHover={(id) => onHover(running ? null : id)} onPin={(id) => { if (!running) onPin(pinned === id ? null : id); }} />
          ))}
        </g>
      </svg>
    </Box>
  );
}
