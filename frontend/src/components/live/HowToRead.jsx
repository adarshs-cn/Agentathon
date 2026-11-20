import { useState } from 'react';
import { Box, Collapse, Stack, Typography } from '@mui/material';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import { tokens } from '../../theme/muiTheme';

const LINES = [
  'The supervisor runs on its own. Inside the contact window it picks up each event on a customer’s account and decides who may contact them, on which channel, or why nobody may.',
  'The six tiles are live counts for real customers only. Click one to see the rows behind it.',
  'One customer, one outreach: ownership and contact limits apply to the person across all their loans.',
  'When a channel fails, the supervisor checks with the provider and retries or re-routes without sending twice. You get an alert only after it has been handled.',
  'To see how one decision is made step by step, open the Workflow Studio.',
];

export default function HowToRead() {
  const [open, setOpen] = useState(false);
  return (
    <Box>
      <Stack direction="row" spacing={0.75} alignItems="center" onClick={() => setOpen((o) => !o)} role="button" tabIndex={0}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && setOpen((o) => !o)}
        sx={{ cursor: 'pointer', width: 'fit-content', color: tokens.navbarBg }} data-testid="how-to-read">
        <InfoOutlinedIcon sx={{ fontSize: 16 }} />
        <Typography sx={{ fontSize: 12, fontWeight: 600 }}>{open ? 'Hide' : 'How to read this page'}</Typography>
      </Stack>
      <Collapse in={open}>
        <Box component="ul" sx={{ m: 0, mt: 1, pl: 2.5, color: tokens.statLabelGrey }}>
          {LINES.map((l) => <Typography component="li" key={l} sx={{ fontSize: 12, mb: 0.4 }}>{l}</Typography>)}
        </Box>
      </Collapse>
    </Box>
  );
}
