import { IconButton, Badge, Tooltip, Snackbar, Alert, Button } from '@mui/material';
import NotificationsIcon from '@mui/icons-material/NotificationsNoneOutlined';
import { useNavigate } from 'react-router-dom';
import { useSim } from '../context/simState';
import { tokens } from '../theme/muiTheme';

// The bell counts faults the supervisor recovered that the collections manager has not opened yet.
// Click: go to Journey Runs with those runs highlighted; the counter clears because they have now been seen.
export default function NotificationBell() {
  const navigate = useNavigate();
  const { notifs, markSeen } = useSim();
  const n = notifs.unseen;

  const open = () => {
    const ids = notifs.items.map((i) => i.event_id);
    navigate(ids.length ? `/runs?highlight=${encodeURIComponent(ids.join(','))}` : '/runs');
    if (n) markSeen();
  };

  return (
    <Tooltip title={n ? `${n} fault${n === 1 ? '' : 's'} recovered by the supervisor: click to review` : 'No new faults'}>
      <IconButton onClick={open} size="small" aria-label="Fault notifications" data-testid="bell">
        <Badge badgeContent={n} color="error" max={99} invisible={!n} data-testid="bell-count">
          <NotificationsIcon sx={{ color: tokens.statTitleGrey }} />
        </Badge>
      </IconButton>
    </Tooltip>
  );
}

// The drop-down at the top of the screen when a new fault+recovery has just happened.
export function FaultToast() {
  const navigate = useNavigate();
  const { toast, clearToast, markSeen } = useSim();
  const view = () => {
    navigate(`/runs?highlight=${encodeURIComponent(toast.event_id)}`);
    markSeen([toast.event_id]);
    clearToast();
  };
  return (
    <Snackbar
      open={!!toast}
      autoHideDuration={9000}
      onClose={(_, why) => why !== 'clickaway' && clearToast()}
      anchorOrigin={{ vertical: 'top', horizontal: 'center' }}
      sx={{ top: { xs: 56 } }}
    >
      <Alert
        severity="warning"
        variant="filled"
        onClose={clearToast}
        action={<Button color="inherit" size="small" onClick={view}>View run</Button>}
        sx={{ alignItems: 'center', fontSize: 12.5, maxWidth: 640 }}
      >
        {toast?.message}
      </Alert>
    </Snackbar>
  );
}
