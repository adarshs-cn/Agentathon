import { FormControl, InputLabel, ListItemText, MenuItem, Select } from '@mui/material';
// "3 · Payment overdue, 31 to 60 days · Message sent" (or "· locked" while its first half has not run)
function optionLabel(item) {
  const tail = item.status === 'done' ? ` · ${item.outcome_label}` : item.available ? '' : ' · locked';
  return `${item.seq} · ${item.label}${tail}`;
}

export default function EventPicker({ items, value, onChange, disabled }) {
  return (
    <FormControl size="small" sx={{ minWidth: 380, maxWidth: '100%' }} disabled={disabled}>
      <InputLabel id="event-picker">Event</InputLabel>
      <Select labelId="event-picker" label="Event" value={value || ''} onChange={(e) => onChange(e.target.value)} data-testid="event-picker" MenuProps={{ PaperProps: { sx: { maxHeight: 420 } } }}>
        {items.map((it) => (
          <MenuItem key={it.event_id} value={it.event_id} data-event={it.event_id}>
            <ListItemText primary={optionLabel(it)} primaryTypographyProps={{ fontSize: 12.5 }} secondary={`${it.event_label} · ${it.borrower_masked}`} secondaryTypographyProps={{ fontSize: 11 }} />
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
}
