import { Paper, Stack, Typography, Box } from '@mui/material';
import { tokens } from '../theme/muiTheme';

export default function StatTile({ icon: Icon, label, value, sub, accent, onClick }) {
  const clickable = Boolean(onClick);
  return (
    <Paper
      onClick={onClick}
      role={clickable ? 'button' : undefined}
      tabIndex={clickable ? 0 : undefined}
      onKeyDown={clickable ? (e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onClick()) : undefined}
      aria-label={clickable ? `${label}: ${value}. Open the list behind this number.` : undefined}
      sx={{
        height: '100%',
        cursor: clickable ? 'pointer' : 'default',
        transition: 'transform 120ms ease-out, outline-color 120ms',
        outline: '2px solid transparent',
        '&:hover': clickable ? { transform: 'translateY(-2px)', outlineColor: tokens.navbarBg } : undefined,
        '&:focus-visible': { outlineColor: tokens.navbarBg },
        p: 2,
        borderRadius: 2.5,
        display: 'flex',
        flexDirection: 'column',
        gap: 0.5,
        minHeight: 96,
      }}
    >
      <Stack direction="row" alignItems="center" spacing={1}>
        {Icon && (
          <Box
            sx={{
              width: 26,
              height: 26,
              borderRadius: 1.5,
              backgroundColor: tokens.iconBadgeBg,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Icon sx={{ fontSize: 15, color: tokens.navbarBg }} />
          </Box>
        )}
        <Typography sx={{ fontSize: 11, color: tokens.statLabelGrey, fontWeight: 600 }}>
          {label}
        </Typography>
      </Stack>
      <Typography
        className="tabular-nums"
        sx={{
          fontSize: 26,
          fontWeight: 700,
          color: accent || tokens.statValueGrey,
          lineHeight: 1.1,
        }}
      >
        {value}
      </Typography>
      {sub && (
        <Typography sx={{ fontSize: 11, color: tokens.statLabelGrey }}>{sub}</Typography>
      )}
    </Paper>
  );
}
