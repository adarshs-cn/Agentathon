import RouteIcon from '@mui/icons-material/AltRoute';
import PersonAddIcon from '@mui/icons-material/PersonAddAlt1';
import PersonRemoveIcon from '@mui/icons-material/PersonRemoveAlt1';
import CallIcon from '@mui/icons-material/Call';
import BugReportIcon from '@mui/icons-material/BugReport';
import HealingIcon from '@mui/icons-material/Healing';
import HandshakeIcon from '@mui/icons-material/Handshake';
import BlockIcon from '@mui/icons-material/Block';
import { tokens } from '../theme/muiTheme';

export const EVENT_META = {
  ROUTING_DECISION: { icon: RouteIcon, color: tokens.navbarBg, label: 'Routing decision' },
  OWNER_ASSIGNED: { icon: PersonAddIcon, color: tokens.statusHealthy, label: 'Owner assigned' },
  OWNER_RELEASED: { icon: PersonRemoveIcon, color: tokens.statLabelGrey, label: 'Owner released' },
  CONTACT_ATTEMPTED: { icon: CallIcon, color: tokens.linkBlue, label: 'Contact attempted' },
  FAULT_DETECTED: { icon: BugReportIcon, color: tokens.statusFault, label: 'Fault detected' },
  RECOVERY_ACTION: { icon: HealingIcon, color: tokens.statusDegraded, label: 'Recovery action' },
  COMMITMENT_RECORDED: { icon: HandshakeIcon, color: tokens.statusHealthy, label: 'Commitment recorded' },
  REQUEST_REFUSED: { icon: BlockIcon, color: tokens.statusFault, label: 'Request refused' },
};

export function metaFor(type) {
  return EVENT_META[type] || { icon: RouteIcon, color: tokens.statLabelGrey, label: type };
}
