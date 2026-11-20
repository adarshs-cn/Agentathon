import { tokens } from '../../theme/muiTheme';
import { edgePath } from './layout';

// idle: grey. active: teal, dashes flowing toward the next station. done: solid teal. skipped: faint dashes.
export default function Edge({ from, to, state, reduced }) {
  const d = edgePath(from, to);
  const color = state === 'active' ? tokens.navbarBg : state === 'done' ? tokens.navbarBg : state === 'warn' ? '#c9a100' : tokens.dividerGrey;
  const width = state === 'active' ? 3 : state === 'done' ? 2 : 1.5;
  const marker = state === 'active' || state === 'done' ? 'url(#arrow-on)' : state === 'warn' ? 'url(#arrow-warn)' : 'url(#arrow-idle)';
  const dashed = state === 'idle' && (to === 'stopped' || from === 'recover' || to === 'recover');
  return (
    <path
      data-edge={`${from}>${to}`}
      data-state={state}
      d={d}
      fill="none"
      stroke={color}
      strokeWidth={width}
      strokeLinecap="round"
      markerEnd={marker}
      strokeDasharray={state === 'active' ? '8 6' : dashed ? '4 5' : undefined}
      style={state === 'active' && !reduced ? { animation: 'wf-flow 0.8s linear infinite' } : { transition: reduced ? 'none' : 'stroke 200ms' }}
    />
  );
}
