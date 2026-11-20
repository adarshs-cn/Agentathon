import { Chip, IconButton, Stack, Tooltip } from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import PauseIcon from '@mui/icons-material/Pause';
import MonoId from './MonoId';
import { useSim } from '../context/simState';
import { tokens } from '../theme/muiTheme';

const SPEEDS = [1, 60, 300, 900];

// The sim clock, small enough for the header so it is reachable from every page.
export default function SimClockMini() {
  const { data, simControl, connected } = useSim();
  const clock = data?.sim_clock;
  if (!clock) return null;
  const playing = clock.status === 'playing';
  return (
    <Stack direction="row" alignItems="center" spacing={0.75}>
      <Tooltip title={connected ? 'Live stream connected' : 'Live stream disconnected'}>
        <span
          style={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            backgroundColor: connected ? tokens.statusHealthy : tokens.statusFault,
            display: 'inline-block',
          }}
        />
      </Tooltip>
      <Tooltip title={playing ? 'Pause the simulated day' : clock.finished ? 'The day is over. Reset it from Overview.' : 'Play the simulated day'}>
        <span>
          <IconButton
            size="small"
            disabled={clock.finished && !playing}
            onClick={() => simControl(playing ? 'pause' : 'play')}
            sx={{
              width: 26,
              height: 26,
              backgroundColor: playing ? '#eff0f0' : tokens.primaryButtonBg,
              color: playing ? tokens.navbarBg : '#fff',
              '&:hover': { backgroundColor: playing ? '#e2e3e3' : '#4fb75f' },
            }}
          >
            {playing ? <PauseIcon sx={{ fontSize: 16 }} /> : <PlayArrowIcon sx={{ fontSize: 16 }} />}
          </IconButton>
        </span>
      </Tooltip>
      <MonoId className="tabular-nums" sx={{ fontSize: 13, fontWeight: 700, color: tokens.navbarBg }}>
        {clock.finished ? '24:00:00' : clock.sim_time.slice(11, 19)}
      </MonoId>
      <Chip
        size="small"
        clickable
        label={`${clock.speed}x`}
        onClick={() => simControl('speed', { speed: SPEEDS[(SPEEDS.indexOf(clock.speed) + 1) % SPEEDS.length] })}
        sx={{ height: 20, fontSize: 10.5, fontWeight: 700, backgroundColor: tokens.actionPrimaryBg, color: '#000' }}
      />
    </Stack>
  );
}
