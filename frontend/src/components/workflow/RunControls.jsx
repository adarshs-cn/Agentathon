import { Button, CircularProgress, Stack, ToggleButton, ToggleButtonGroup, Tooltip } from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import ReplayIcon from '@mui/icons-material/Replay';
import RestartAltIcon from '@mui/icons-material/RestartAlt';

export default function RunControls({ item, running, resetting, onRun, onReplay, onReset, pace, onPace, runLabel = 'Run' }) {
  const done = item?.status === 'done';
  const locked = item && !item.available;
  return (
    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
      {done ? (
        <Button variant="outlined" color="primary" startIcon={<ReplayIcon />} onClick={onReplay} disabled={running} data-testid="replay">
          Replay
        </Button>
      ) : (
        <Tooltip title={locked ? item.why_unavailable : ''}>
          <span>
            <Button variant="contained" color="primary" startIcon={running ? <CircularProgress size={14} color="inherit" /> : <PlayArrowIcon />} onClick={onRun} disabled={!item || running || locked} data-testid="run">
              {resetting ? 'Resetting…' : running ? 'Running…' : runLabel}
            </Button>
          </span>
        </Tooltip>
      )}
      <ToggleButtonGroup size="small" exclusive value={pace} onChange={(_, v) => v && onPace(v)} aria-label="Animation speed">
        <ToggleButton value="normal" sx={{ px: 1.2, fontSize: 11 }}>Normal</ToggleButton>
        <ToggleButton value="slow" sx={{ px: 1.2, fontSize: 11 }}>Slow</ToggleButton>
      </ToggleButtonGroup>
      <Tooltip title="Return all 15 events to “not run” and rebuild the data">
        <span>
          <Button size="small" startIcon={<RestartAltIcon />} onClick={onReset} disabled={running} data-testid="reset">
            {resetting ? 'Resetting…' : 'Reset demo'}
          </Button>
        </span>
      </Tooltip>
    </Stack>
  );
}
