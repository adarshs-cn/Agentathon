import { Box, Stack, Typography } from '@mui/material';
import GavelIcon from '@mui/icons-material/Gavel';
import Section from '../Section';
import RuleChip from '../RuleChip';
import EmptyState from '../EmptyState';
import { tokens } from '../../theme/muiTheme';

// Which policy rules stopped or delayed a contact, most often first, in plain words.
export default function WhyStopped({ rules }) {
  const items = (rules || []).slice(0, 6);
  const max = Math.max(1, ...items.map((r) => r.count));
  return (
    <Section title="Why contacts were stopped" subtitle="The policy rules that held a contact back today." sx={{ height: '100%' }}>
      {items.length ? (
        <Stack spacing={1.4} data-testid="why-stopped">
          {items.map((r) => (
            <Box key={r.rule_id}>
              <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between">
                <Stack direction="row" spacing={1} alignItems="center" sx={{ minWidth: 0 }}>
                  <RuleChip id={r.rule_id} />
                  <Typography noWrap sx={{ fontSize: 12, color: tokens.statValueGrey }} title={r.why}>{r.headline}</Typography>
                </Stack>
                <Typography sx={{ fontSize: 12, fontWeight: 600, color: tokens.statValueGrey }} className="tabular-nums">{r.count}</Typography>
              </Stack>
              <Box sx={{ mt: 0.5, height: 5, borderRadius: 3, backgroundColor: tokens.cardGroupedBg }}>
                <Box sx={{ height: '100%', width: `${(r.count / max) * 100}%`, borderRadius: 3, backgroundColor: tokens.statusDegraded }} />
              </Box>
            </Box>
          ))}
        </Stack>
      ) : <EmptyState icon={GavelIcon} title="Nothing stopped yet" hint="When a rule holds a contact back (a promise to pay, contact hours, a limit), it is listed here." />}
    </Section>
  );
}
