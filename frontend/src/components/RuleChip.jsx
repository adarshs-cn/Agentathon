import { Chip, Tooltip, Typography, Box } from '@mui/material';
import { useNavigate } from 'react-router-dom';
import { useRules } from '../hooks/useRules';
import { tokens } from '../theme/muiTheme';

// A D12 rule id that explains itself on hover and filters the Decision Log on click.
export default function RuleChip({ id, link = true, sx }) {
  const rules = useRules();
  const navigate = useNavigate();
  const rule = rules[id];
  const body = rule ? (
    <Box sx={{ maxWidth: 320 }}>
      <Typography sx={{ fontSize: 11.5, fontWeight: 700 }}>
        {id} · {rule.category?.replace(/_/g, ' ')} · {rule.severity}
      </Typography>
      <Typography sx={{ fontSize: 11.5, mt: 0.3 }}>{rule.description}</Typography>
      {link && <Typography sx={{ fontSize: 10.5, mt: 0.6, opacity: 0.8 }}>Click to filter the Decision Log</Typography>}
    </Box>
  ) : (
    id
  );
  return (
    <Tooltip title={body} arrow placement="top">
      <Chip
        size="small"
        label={id}
        clickable={link}
        onClick={link ? (e) => { e.stopPropagation(); navigate(`/decisions?rule_id=${encodeURIComponent(id)}`); } : undefined}
        sx={{
          height: 18,
          fontSize: 10,
          fontFamily: tokens.fontMono,
          fontWeight: 600,
          backgroundColor: '#eff0f0',
          color: tokens.statTitleGrey,
          '& .MuiChip-label': { px: 0.8 },
          ...sx,
        }}
      />
    </Tooltip>
  );
}

export function RuleChips({ ids, max = 6 }) {
  const list = Array.from(new Set(ids || []));
  if (!list.length) return null;
  return (
    <>
      {list.slice(0, max).map((r) => (
        <RuleChip key={r} id={r} />
      ))}
      {list.length > max && (
        <Typography component="span" sx={{ fontSize: 10, color: tokens.statLabelGrey }}>
          +{list.length - max}
        </Typography>
      )}
    </>
  );
}
