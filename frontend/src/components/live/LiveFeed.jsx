import { Box } from '@mui/material';
import FeedIcon from '@mui/icons-material/DynamicFeedOutlined';
import { useNavigate } from 'react-router-dom';
import Section from '../Section';
import EventRow from '../EventRow';
import EmptyState from '../EmptyState';

// Every step the supervisor takes on real customers, newest first (fed by the live stream).
export default function LiveFeed({ events }) {
  const navigate = useNavigate();
  const items = (events || []).slice(0, 30);
  return (
    <Section title="Live activity" subtitle="Each step the supervisor takes, as it happens. Click a line to open the customer." noPad sx={{ height: '100%' }}>
      <Box sx={{ maxHeight: 380, overflow: 'auto', px: 1 }} data-testid="live-feed">
        {items.length ? items.map((e) => (
          <EventRow key={e.event_id} event={e} onClick={() => navigate(`/trace?account=${e.account_id && e.account_id !== '-' ? e.account_id : e.customer_id}`)} />
        )) : <EmptyState icon={FeedIcon} title="Nothing yet" hint="Steps appear here as soon as the supervisor handles an event inside the contact window." />}
      </Box>
    </Section>
  );
}
