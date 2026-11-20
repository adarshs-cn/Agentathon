import { Box, Typography } from '@mui/material';
import { tokens } from '../../theme/muiTheme';

const ROLE = { reminder: 'Reminder', negotiation: 'Negotiation', servicing: 'Servicing', legal: 'Legal' };
const roleWord = (r) => (r ? ROLE[r] || r : 'Null');

// Exactly three facts: who the borrower is, who owns them, and what the supervisor did and why.
export default function NodeHoverCard({ title, borrower, view, left, top }) {
  const before = view?.ownerBefore;
  const after = view?.ownerAfter;
  const hasOwner = view && view.ownerBefore !== undefined;
  const owner = !hasOwner ? 'Null' : before !== after && after ? `${roleWord(before)} → ${roleWord(after)}` : roleWord(after ?? before);
  const did = view?.did || 'Not reached yet. Press Run.';
  const rows = [
    ['Borrower', `${borrower?.masked || '—'} · ${borrower?.id || ''}`],
    ['Owner', owner],
    ['Supervisor', did],
  ];
  return (
    <Box
      role="tooltip"
      data-hovercard
      sx={{
        position: 'absolute',
        left,
        top,
        transform: 'translate(-50%, -100%)',
        width: 280,
        zIndex: 5,
        pointerEvents: 'none',
        backgroundColor: '#fff',
        border: `1px solid ${tokens.dividerGrey}`,
        borderRadius: 2.5,
        boxShadow: tokens.cardShadow,
        overflow: 'hidden',
      }}
    >
      <Box sx={{ px: 1.5, py: 0.8, backgroundColor: tokens.cardGroupedBg, borderBottom: `1px solid ${tokens.dividerGrey}` }}>
        <Typography sx={{ fontSize: 12, fontWeight: 600, color: tokens.statTitleGrey }}>{title}</Typography>
      </Box>
      <Box sx={{ px: 1.5, py: 1, display: 'grid', rowGap: 0.9 }}>
        {rows.map(([k, v]) => (
          <Box key={k} data-fact={k} sx={{ display: 'grid', gridTemplateColumns: '78px 1fr', columnGap: 1 }}>
            <Typography sx={{ fontSize: 11, color: tokens.statLabelGrey, fontWeight: 600 }}>{k}</Typography>
            <Typography sx={{ fontSize: 12, color: tokens.statValueGrey, lineHeight: 1.35 }}>{v}</Typography>
          </Box>
        ))}
      </Box>
    </Box>
  );
}
