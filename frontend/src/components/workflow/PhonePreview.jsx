import { Box, Typography } from '@mui/material';
import ChatOutlinedIcon from '@mui/icons-material/ChatOutlined';
import MailOutlineIcon from '@mui/icons-material/MailOutline';
import PhoneInTalkOutlinedIcon from '@mui/icons-material/PhoneInTalkOutlined';
import { tokens } from '../../theme/muiTheme';

const CHANNEL = {
  whatsapp: { title: 'WhatsApp', icon: ChatOutlinedIcon },
  email: { title: 'Email', icon: MailOutlineIcon },
  voice: { title: 'Incoming call (IVR script)', icon: PhoneInTalkOutlinedIcon },
};

// The message as the borrower receives it. A preview of the agent's text: nothing is delivered to a real phone.
export default function PhonePreview({ message, waiting }) {
  const c = message ? CHANNEL[message.channel] || CHANNEL.whatsapp : null;
  const Icon = c?.icon;
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1 }}>
      <Box
        data-phone
        sx={{
          width: 280,
          minHeight: 300,
          border: `8px solid ${tokens.navbarBg}`,
          borderRadius: '30px',
          backgroundColor: tokens.cardGroupedBg,
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <Box sx={{ backgroundColor: tokens.navbarBg, color: '#fff', px: 1.5, py: 1, display: 'flex', alignItems: 'center', gap: 1 }}>
          {Icon && <Icon sx={{ fontSize: 16 }} />}
          <Box sx={{ minWidth: 0 }}>
            <Typography sx={{ fontSize: 12, fontWeight: 600, lineHeight: 1.2 }}>{c ? c.title : 'Messages'}</Typography>
            <Typography sx={{ fontSize: 10.5, opacity: 0.85 }} data-to>
              {message ? `To: ${message.to}` : 'To: demo contact'}
            </Typography>
          </Box>
        </Box>
        <Box sx={{ p: 1.5, flex: 1, display: 'flex', alignItems: message ? 'flex-start' : 'center', justifyContent: message ? 'flex-start' : 'center' }}>
          {message ? (
            <Box
              key={message.body}
              data-message
              sx={{
                backgroundColor: '#fff',
                border: `1px solid ${tokens.dividerGrey}`,
                borderRadius: '12px 12px 12px 2px',
                px: 1.4,
                py: 1,
                animation: 'msg-in 320ms ease-out',
                '@keyframes msg-in': { from: { opacity: 0, transform: 'translateY(10px)' }, to: { opacity: 1, transform: 'none' } },
                '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
              }}
            >
              {message.subject && (
                <Typography sx={{ fontSize: 12, fontWeight: 700, color: tokens.statValueGrey, mb: 0.6 }}>{message.subject}</Typography>
              )}
              <Typography sx={{ fontSize: 12, color: tokens.statValueGrey, whiteSpace: 'pre-wrap', lineHeight: 1.45 }}>{message.body}</Typography>
            </Box>
          ) : (
            <Typography sx={{ fontSize: 12, color: tokens.statLabelGrey, textAlign: 'center', px: 2 }}>
              {waiting ? 'The agent is writing…' : 'No message for this event yet.'}
            </Typography>
          )}
        </Box>
      </Box>
      <Typography sx={{ fontSize: 10.5, color: tokens.statLabelGrey, textAlign: 'center', maxWidth: 280 }}>
        Preview of the agent&apos;s message. Nothing is sent to a real phone.
      </Typography>
    </Box>
  );
}
