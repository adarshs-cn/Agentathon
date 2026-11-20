import { Box, Stack, Typography } from '@mui/material';
import ForumIcon from '@mui/icons-material/ForumOutlined';
import Section from '../Section';
import EmptyState from '../EmptyState';
import { tokens } from '../../theme/muiTheme';

const CHANNELS = { whatsapp: 'WhatsApp', email: 'Email', voice: 'Voice call' };
const ROLE_COLOR = { reminder: tokens.statusHealthy, negotiation: tokens.linkBlue, servicing: tokens.statusDegraded, legal: tokens.navbarBg };
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);

// Messages sent, by channel, split by the role that sent them.
export default function ChannelMix({ mix }) {
  const by = {};
  (mix || []).forEach((r) => { by[r.channel] = by[r.channel] || {}; by[r.channel][r.role] = (by[r.channel][r.role] || 0) + r.n; });
  const total = (c) => Object.values(by[c] || {}).reduce((a, b) => a + b, 0);
  const chans = Object.keys(by).sort((a, b) => total(b) - total(a));
  const max = Math.max(1, ...chans.map(total));
  const roles = [...new Set((mix || []).map((r) => r.role))];
  return (
    <Section title="Channels and roles" subtitle="Messages sent, by channel and by the agent role." sx={{ height: '100%' }}>
      {chans.length ? (
        <Stack spacing={1.6} data-testid="channel-mix">
          {chans.map((c) => (
            <Box key={c}>
              <Stack direction="row" justifyContent="space-between">
                <Typography sx={{ fontSize: 12, color: tokens.statValueGrey }}>{CHANNELS[c] || c}</Typography>
                <Typography sx={{ fontSize: 12, fontWeight: 600, color: tokens.statValueGrey }} className="tabular-nums">{total(c)}</Typography>
              </Stack>
              <Stack direction="row" sx={{ mt: 0.5, height: 8, borderRadius: 4, overflow: 'hidden', backgroundColor: tokens.cardGroupedBg, width: `${(total(c) / max) * 100}%` }}>
                {Object.entries(by[c]).map(([role, n]) => (
                  <Box key={role} title={`${cap(role)}: ${n}`} sx={{ flex: n, backgroundColor: ROLE_COLOR[role] || tokens.statLabelGrey }} />
                ))}
              </Stack>
            </Box>
          ))}
          <Stack direction="row" spacing={1.5} flexWrap="wrap" useFlexGap sx={{ pt: 0.5 }}>
            {roles.map((r) => (
              <Stack key={r} direction="row" spacing={0.5} alignItems="center">
                <Box sx={{ width: 8, height: 8, borderRadius: '50%', backgroundColor: ROLE_COLOR[r] || tokens.statLabelGrey }} />
                <Typography sx={{ fontSize: 11, color: tokens.statLabelGrey }}>{cap(r)}</Typography>
              </Stack>
            ))}
          </Stack>
        </Stack>
      ) : <EmptyState icon={ForumIcon} title="No messages yet" hint="Each message the agents send is counted here by channel." />}
    </Section>
  );
}
