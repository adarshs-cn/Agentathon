import { useState } from 'react';
import {
  IconButton, Badge, Tooltip, Snackbar, Alert, Button, Popover, Stack, Typography, Divider, Box,
} from '@mui/material';
import NotificationsIcon from '@mui/icons-material/NotificationsNoneOutlined';
import ReportProblemOutlinedIcon from '@mui/icons-material/ReportProblemOutlined';
import { useNavigate } from 'react-router-dom';
import { useSim } from '../context/simState';
import { tokens } from '../theme/muiTheme';

const when = (v) => (v ? String(v).replace('T', ' ').slice(11, 16) : '');

// The bell: a small panel of unread alerts. "Mark as read" removes one from the panel and from the count.
export default function NotificationBell() {
  const navigate = useNavigate();
  const { notifs, markSeen } = useSim();
  const [anchor, setAnchor] = useState(null);
  const n = notifs.unseen;
  const items = notifs.items;

  return (
    <>
      <Tooltip title={n ? `${n} unread` : 'No unread notifications'}>
        <IconButton onClick={(e) => setAnchor(e.currentTarget)} size="small" aria-label="Notifications" data-testid="bell">
          <Badge badgeContent={n} color="error" max={99} invisible={!n} data-testid="bell-count">
            <NotificationsIcon sx={{ color: tokens.statTitleGrey }} />
          </Badge>
        </IconButton>
      </Tooltip>
      <Popover
        open={!!anchor}
        anchorEl={anchor}
        onClose={() => setAnchor(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
        slotProps={{ paper: { sx: { width: 380, maxHeight: 460, borderRadius: 2, mt: 0.5 } } }}
      >
        <Box data-testid="notif-panel">
          <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ px: 2, py: 1.2 }}>
            <Typography sx={{ fontSize: 14, fontWeight: 600 }}>Notifications</Typography>
            {n > 0 && (
              <Button size="small" onClick={() => markSeen()} data-testid="mark-all">Mark all as read</Button>
            )}
          </Stack>
          <Divider />
          {items.length === 0 ? (
            <Typography data-testid="notif-empty" sx={{ px: 2, py: 4, fontSize: 13, color: tokens.statLabelGrey, textAlign: 'center' }}>
              You are all caught up.
            </Typography>
          ) : (
            items.map((i) => (
              <Box key={i.event_id} data-testid="notif-item" sx={{ px: 2, py: 1.4, borderBottom: `1px solid ${tokens.dividerGrey}` }}>
                <Stack direction="row" spacing={1.2} alignItems="flex-start">
                  <ReportProblemOutlinedIcon sx={{ fontSize: 18, color: tokens.statusFault, mt: 0.2 }} />
                  <Box sx={{ flex: 1 }}>
                    <Typography sx={{ fontSize: 13 }}>{i.message}</Typography>
                    <Typography sx={{ fontSize: 11, color: tokens.statLabelGrey, mt: 0.3 }}>
                      {i.borrower_id} &middot; {when(i.finished_at)}
                    </Typography>
                    <Stack direction="row" spacing={1} sx={{ mt: 0.8 }}>
                      <Button size="small" variant="outlined" onClick={() => markSeen([i.event_id])} data-testid="mark-read">
                        Mark as read
                      </Button>
                      <Button size="small" onClick={() => { setAnchor(null); navigate(`/runs?highlight=${encodeURIComponent(i.event_id)}`); }}>
                        View run
                      </Button>
                    </Stack>
                  </Box>
                </Stack>
              </Box>
            ))
          )}
        </Box>
      </Popover>
    </>
  );
}

// The alert that drops in at the top when a fault has just happened. Ignoring it leaves the alert unread in the bell.
export function FaultToast() {
  const { toast, clearToast, markSeen } = useSim();
  return (
    <Snackbar
      open={!!toast}
      autoHideDuration={12000}
      onClose={(_, why) => why === 'timeout' && clearToast()}
      anchorOrigin={{ vertical: 'top', horizontal: 'center' }}
      sx={{ top: { xs: 56 } }}
    >
      <Alert
        severity="warning"
        variant="filled"
        icon={<ReportProblemOutlinedIcon fontSize="small" />}
        action={(
          <Stack direction="row" spacing={0.5}>
            <Button color="inherit" size="small" data-testid="toast-read" onClick={() => { markSeen([toast.event_id]); clearToast(); }}>
              Mark as read
            </Button>
            <Button color="inherit" size="small" data-testid="toast-ignore" onClick={clearToast}>Ignore</Button>
          </Stack>
        )}
        sx={{ alignItems: 'center', fontSize: 13, minWidth: 520 }}
      >
        {toast?.message}
      </Alert>
    </Snackbar>
  );
}
