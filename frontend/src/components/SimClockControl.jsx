import { useState } from 'react';
import { Paper, Stack, Typography, IconButton, Chip, LinearProgress } from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import PauseIcon from '@mui/icons-material/Pause';
import MonoId from './MonoId';
import { tokens } from '../theme/muiTheme';

const SPEEDS = [1, 60, 300, 900];

function fmtClock(iso) {
  try {
    return new Date(iso).toISOString().slice(11, 19);
  } catch {
    return '--:--:--';
  }
}

export default function SimClockControl({ simClock, onControl }) {
  const [pending, setPending] = useState(false);
  if (!simClock) return null;

  const playing = simClock.status === 'playing';
  const finished = !!simClock.finished;
  const pct = Math.min(
    100,
    (100 * (simClock.position_seconds || 0)) / (simClock.day_length_seconds || 86400)
  );

  const act = async (action, body) => {
    setPending(true);
    try {
      await onControl(action, body);
    } finally {
      setPending(false);
    }
  };

  return (
    <Paper sx={{ p: 1.5, borderRadius: 2.5 }}>
      <Stack direction="row" alignItems="center" spacing={1.5}>
        <IconButton
          size="small"
          disabled={pending || (finished && !playing)}
          onClick={() => act(playing ? 'pause' : 'play')}
          sx={{
            backgroundColor: playing ? '#eff0f0' : tokens.primaryButtonBg,
            color: playing ? tokens.navbarBg : '#fff',
            '&:hover': { backgroundColor: playing ? '#e2e3e3' : '#4fb75f' },
          }}
        >
          {playing ? <PauseIcon fontSize="small" /> : <PlayArrowIcon fontSize="small" />}
        </IconButton>

        <Stack sx={{ minWidth: 150 }}>
          <Stack direction="row" spacing={1} alignItems="baseline">
            <Typography sx={{ fontSize: 11, color: tokens.statLabelGrey }}>Sim time</Typography>
            <MonoId className="tabular-nums" sx={{ fontSize: 14, fontWeight: 700 }}>
              {finished ? '24:00:00' : fmtClock(simClock.sim_time)}
            </MonoId>
          </Stack>
          <LinearProgress
            variant="determinate"
            value={pct}
            sx={{
              height: 4,
              borderRadius: 2,
              mt: 0.4,
              backgroundColor: '#e9eff7',
              '& .MuiLinearProgress-bar': { backgroundColor: tokens.navbarBg },
            }}
          />
        </Stack>

        <Stack direction="row" spacing={0.5}>
          {SPEEDS.map((s) => (
            <Chip
              key={s}
              size="small"
              clickable
              disabled={pending}
              label={`${s}x`}
              onClick={() => act('speed', { speed: s })}
              sx={{
                height: 22,
                fontSize: 11,
                fontWeight: 700,
                color: simClock.speed === s ? '#000' : tokens.statLabelGrey,
                backgroundColor: simClock.speed === s ? tokens.actionPrimaryBg : '#f8f9f9',
              }}
            />
          ))}
        </Stack>

        <Chip
          size="small"
          label={finished ? 'Day over' : playing ? 'Playing' : 'Paused'}
          sx={{
            height: 22,
            fontSize: 11,
            fontWeight: 600,
            backgroundColor: playing ? tokens.statusHealthy : '#eff0f0',
            color: playing ? '#0c3d14' : tokens.statTitleGrey,
          }}
        />
      </Stack>
    </Paper>
  );
}
