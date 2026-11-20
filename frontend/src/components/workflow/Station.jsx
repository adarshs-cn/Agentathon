import EventNoteIcon from '@mui/icons-material/EventNote';
import PersonOutlineIcon from '@mui/icons-material/PersonOutline';
import VerifiedUserOutlinedIcon from '@mui/icons-material/VerifiedUserOutlined';
import AltRouteIcon from '@mui/icons-material/AltRoute';
import LockOutlinedIcon from '@mui/icons-material/LockOutlined';
import SendOutlinedIcon from '@mui/icons-material/SendOutlined';
import FactCheckOutlinedIcon from '@mui/icons-material/FactCheckOutlined';
import AutorenewIcon from '@mui/icons-material/Autorenew';
import SaveOutlinedIcon from '@mui/icons-material/SaveOutlined';
import TaskAltIcon from '@mui/icons-material/TaskAlt';
import BlockIcon from '@mui/icons-material/Block';
import { tokens } from '../../theme/muiTheme';
import { H, W } from './layout';

const ICONS = {
  event: EventNoteIcon,
  borrower: PersonOutlineIcon,
  safety: VerifiedUserOutlinedIcon,
  route: AltRouteIcon,
  lock: LockOutlinedIcon,
  send: SendOutlinedIcon,
  check: FactCheckOutlinedIcon,
  recover: AutorenewIcon,
  save: SaveOutlinedIcon,
  done: TaskAltIcon,
  stop: BlockIcon,
};

// How each state looks. Colours are the existing theme tokens only.
const LOOK = {
  idle: { ring: tokens.dividerGrey, w: 1, icon: tokens.statLabelGrey, word: 'Waiting', dash: undefined },
  active: { ring: tokens.navbarBg, w: 2.5, icon: tokens.navbarBg, word: 'Working…' },
  done: { ring: tokens.dividerGrey, w: 1, icon: tokens.navbarBg, word: '' },
  recovering: { ring: tokens.statusDegraded, w: 2.5, icon: tokens.navbarBg, word: 'Recovering…' },
  recovered: { ring: tokens.statusDegraded, w: 2, icon: tokens.navbarBg, word: '' },
  blocked: { ring: tokens.statusFault, w: 2, icon: tokens.statusFault, word: '' },
  stopped: { ring: tokens.statusFault, w: 2.5, icon: tokens.statusFault, word: '' },
};

const clip = (s, n) => (s && s.length > n ? `${s.slice(0, n - 1)}…` : s);

export default function Station({ def, box, view, running, reduced, onEnter, onLeave }) {
  const state = view?.state || 'idle';
  const look = LOOK[state];
  const Icon = ICONS[def.icon];
  const active = state === 'active' || state === 'recovering';
  const dim = running && !active && state !== 'done' && state !== 'recovered' && state !== 'blocked' && state !== 'stopped';
  const word = state === 'idle' ? (running ? 'Waiting' : '') : look.word || clip(view?.label, 17);
  const showCheck = state === 'done' || state === 'recovered';
  return (
    <g
      data-station={def.id}
      data-state={state}
      transform={`translate(${box.x} ${box.y})`}
      tabIndex={0}
      role="img"
      aria-label={`${def.name}: ${view?.did || 'not reached yet'}`}
      onMouseEnter={(e) => onEnter(def.id, e.currentTarget)}
      onMouseLeave={onLeave}
      onFocus={(e) => onEnter(def.id, e.currentTarget)}
      onBlur={onLeave}
      style={{ outline: 'none', cursor: 'default' }}
    >
      <g
        style={{
          transformBox: 'fill-box',
          transformOrigin: 'center',
          transform: active && !reduced ? 'scale(1.12)' : 'scale(1)',
          transition: reduced ? 'none' : 'transform 250ms ease-out, opacity 250ms ease-out',
          opacity: dim ? 0.6 : 1,
          filter: active
            ? 'drop-shadow(0 6px 14px rgba(3, 78, 99, 0.35))'
            : 'drop-shadow(0 3px 8px rgba(151, 151, 154, 0.22))',
        }}
      >
        <rect width={W} height={H} rx={10} fill="#ffffff" stroke={look.ring} strokeWidth={look.w} />
        <circle cx={W / 2} cy={19} r={12} fill={tokens.iconBadgeBg} />
        <foreignObject x={W / 2 - 8} y={11} width={16} height={16} style={{ overflow: 'visible' }}>
          <Icon sx={{ fontSize: 16, color: look.icon, display: 'block' }} />
        </foreignObject>
        <text x={W / 2} y={44} textAnchor="middle" fontSize={12} fontWeight={600} fill={tokens.statValueGrey}>
          {def.name}
        </text>
        <text x={W / 2} y={58} textAnchor="middle" fontSize={10.5} fill={state === 'blocked' || state === 'stopped' ? tokens.statusFault : tokens.statLabelGrey}>
          {word}
        </text>
        {showCheck && (
          <g transform={`translate(${W - 9} 9)`}>
            <circle r={8} fill={state === 'recovered' ? tokens.statusDegraded : tokens.statusHealthy} />
            <path d="M -3.6 0.2 L -1 2.8 L 3.8 -2.6" fill="none" stroke={state === 'recovered' ? '#000' : '#fff'} strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" />
          </g>
        )}
      </g>
    </g>
  );
}
