import { Stack, Typography } from '@mui/material';
import { tokens } from '../theme/muiTheme';

export default function EmptyState({ icon: Icon, title, hint }) {
  return (
    <Stack alignItems="center" spacing={0.5} sx={{ py: 4, px: 2, textAlign: 'center' }}>
      {Icon && <Icon sx={{ fontSize: 28, color: tokens.dividerGrey }} />}
      <Typography sx={{ fontSize: 13, fontWeight: 600, color: tokens.statTitleGrey }}>{title}</Typography>
      {hint && <Typography sx={{ fontSize: 11.5, color: tokens.statLabelGrey, maxWidth: 420 }}>{hint}</Typography>}
    </Stack>
  );
}
