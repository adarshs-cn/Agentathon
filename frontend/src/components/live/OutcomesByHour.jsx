import { Box } from '@mui/material';
import BarChartIcon from '@mui/icons-material/BarChartOutlined';
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import Section from '../Section';
import EmptyState from '../EmptyState';
import { tokens } from '../../theme/muiTheme';

// Same colours as the outcome chips, so a colour means the same thing everywhere in the app.
const OUTCOME_SERIES = [
  ['CONTACTED', 'Message sent', tokens.statusHealthy],
  ['DEFERRED', 'Waiting for a better time', tokens.linkBlue],
  ['BLOCKED', 'Not allowed', tokens.statusFault],
  ['SUPPRESSED', 'Nobody could act', tokens.statusDegraded],
  ['ESCALATED', 'Sent to a person', tokens.navbarBg],
  ['REJECTED', 'Invalid event', '#b0b0b0'],
];

export default function OutcomesByHour({ timeline }) {
  const rows = timeline || [];
  const any = rows.some((r) => OUTCOME_SERIES.some(([k]) => r[k]));
  return (
    <Section title="Outcomes by hour" subtitle="What happened to each event, by the hour it arrived." sx={{ height: '100%' }}>
      {any ? (
        <Box sx={{ height: 260 }} data-testid="outcomes-chart">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows} margin={{ top: 4, right: 8, left: -18, bottom: 0 }}>
              <CartesianGrid stroke={tokens.dividerGrey} strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="hour" tick={{ fontSize: 11, fill: tokens.statLabelGrey }} tickLine={false} axisLine={{ stroke: tokens.dividerGrey }} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: tokens.statLabelGrey }} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, borderColor: tokens.dividerGrey }} cursor={{ fill: tokens.cardGroupedBg }} />
              <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 11 }}
                formatter={(v) => <span style={{ color: tokens.statLabelGrey }}>{v}</span>} />
              {OUTCOME_SERIES.map(([k, label, color]) => (
                <Bar key={k} dataKey={k} name={label} stackId="o" fill={color} maxBarSize={36} isAnimationActive={false} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </Box>
      ) : <EmptyState icon={BarChartIcon} title="No events yet today" hint="Bars appear as the supervisor handles events inside the contact window." />}
    </Section>
  );
}
