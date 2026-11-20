import { useState } from 'react';
import { Box, Button, Typography } from '@mui/material';
import Section from '../Section';
import MonoId from '../MonoId';
import { tokens } from '../../theme/muiTheme';
import { STATIONS } from './layout';

const NAME = Object.fromEntries(STATIONS.map((s) => [s.id, s.name]));

// One plain sentence per step. Technical detail (node name, time, rule codes) only on request.
export default function EventLog({ steps }) {
  const [tech, setTech] = useState(false);
  return (
    <Section
      title="What happened"
      subtitle={steps.length ? `${steps.length} ${steps.length === 1 ? 'step' : 'steps'}` : 'Run the event to see each step'}
      action={steps.length ? <Button size="small" onClick={() => setTech((t) => !t)}>{tech ? 'Hide technical detail' : 'Show technical detail'}</Button> : null}
      noPad
      sx={{ height: '100%' }}
    >
      {steps.length === 0 ? (
        <Typography sx={{ p: 2, fontSize: 12, color: tokens.statLabelGrey }}>Nothing yet.</Typography>
      ) : (
        <Box component="ol" sx={{ listStyle: 'none', m: 0, p: 0 }}>
          {steps.map((s) => (
            <Box component="li" key={s.seq} sx={{ px: 2, py: 1, borderBottom: `1px solid ${tokens.dividerGrey}`, '&:last-child': { borderBottom: 'none' } }}>
              <Typography sx={{ fontSize: 11, fontWeight: 600, color: tokens.statLabelGrey }}>{NAME[s.station] || s.station}</Typography>
              <Typography sx={{ fontSize: 12.5, color: tokens.statValueGrey }}>{s.did}</Typography>
              {tech && (
                <MonoId sx={{ fontSize: 10.5, color: tokens.statLabelGrey }}>
                  {s.node} · {s.ms} ms{s.rule_ids?.length ? ` · ${s.rule_ids.join(', ')}` : ''}
                </MonoId>
              )}
            </Box>
          ))}
        </Box>
      )}
    </Section>
  );
}
