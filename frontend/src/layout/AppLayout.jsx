import { useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import {
  Box,
  Stack,
  Typography,
  Avatar,
  Tooltip,
  Snackbar,
  Alert,
  Button,
} from '@mui/material';
import TowerControlIcon from '@mui/icons-material/CellTower';
import ViewListIcon from '@mui/icons-material/ViewListOutlined';
import SearchIcon from '@mui/icons-material/PersonSearch';
import ReportProblemIcon from '@mui/icons-material/ReportProblemOutlined';
import SmartToyIcon from '@mui/icons-material/SmartToyOutlined';
import HandshakeIcon from '@mui/icons-material/HandshakeOutlined';
import SpeedIcon from '@mui/icons-material/SpeedOutlined';
import ListAltIcon from '@mui/icons-material/ListAltOutlined';
import { tokens } from '../theme/muiTheme';
import { OVERVIEW_TITLE } from '../config/labels';
import SimClockMini from '../components/SimClockMini';
import BorrowerSearch from '../components/BorrowerSearch';
import { useSim } from '../context/simState';

const NAV_ITEMS = [
  { to: '/', label: OVERVIEW_TITLE, icon: TowerControlIcon, end: true },
  { to: '/accounts', label: 'Accounts', icon: ViewListIcon },
  { to: '/trace', label: 'Borrower Trace', icon: SearchIcon },
  { to: '/faults', label: 'Faults & Recovery', icon: ReportProblemIcon },
  { to: '/agents', label: 'Agents', icon: SmartToyIcon },
  { to: '/ownership', label: 'Ownership', icon: HandshakeIcon },
  { to: '/budgets', label: 'Budgets', icon: SpeedIcon },
  { to: '/decisions', label: 'Decision Log', icon: ListAltIcon },
];

const RAIL_WIDTH = 56;
const EXPANDED_WIDTH = 230;

function pageTitle(pathname) {
  const match = NAV_ITEMS.find((n) =>
    n.end ? pathname === n.to : pathname.startsWith(n.to)
  );
  return match ? match.label : 'MT-02 Journey Supervisor';
}

export default function AppLayout() {
  const [expanded, setExpanded] = useState(false);
  const location = useLocation();
  const { lastFault, clearFault } = useSim();
  const navigate = useNavigate();

  return (
    <Box sx={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
      <Box
        onMouseEnter={() => setExpanded(true)}
        onMouseLeave={() => setExpanded(false)}
        sx={{
          width: expanded ? EXPANDED_WIDTH : RAIL_WIDTH,
          minWidth: expanded ? EXPANDED_WIDTH : RAIL_WIDTH,
          backgroundColor: tokens.navbarBg,
          color: tokens.navbarColor,
          display: 'flex',
          flexDirection: 'column',
          transition: 'width 0.15s ease, min-width 0.15s ease',
          overflow: 'hidden',
          zIndex: 10,
        }}
      >
        <Stack
          direction="row"
          alignItems="center"
          spacing={1.2}
          sx={{ height: 50, px: 1.5, flexShrink: 0 }}
        >
          <TowerControlIcon sx={{ fontSize: 22, flexShrink: 0 }} />
          {expanded && (
            <Typography
              noWrap
              sx={{ fontSize: 13, fontWeight: 700, letterSpacing: 0.3 }}
            >
              MT-02 SUPERVISOR
            </Typography>
          )}
        </Stack>

        <Stack sx={{ mt: 1, flex: 1 }}>
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const active = item.end
              ? location.pathname === item.to
              : location.pathname.startsWith(item.to);
            return (
              <Tooltip
                key={item.to}
                title={expanded ? '' : item.label}
                placement="right"
              >
                <NavLink
                  to={item.to}
                  end={item.end}
                  style={{ textDecoration: 'none', color: 'inherit' }}
                >
                  <Stack
                    direction="row"
                    alignItems="center"
                    spacing={1.5}
                    sx={{
                      height: 38,
                      mx: 0.75,
                      mb: 0.3,
                      px: 1,
                      borderRadius: 1.5,
                      cursor: 'pointer',
                      backgroundColor: active
                        ? 'rgba(255,255,255,0.14)'
                        : 'transparent',
                      color: active ? '#ffffff' : tokens.navbarColor,
                      '&:hover': {
                        backgroundColor: tokens.navbarHoverBg,
                        color: tokens.navbarHoverColor,
                      },
                    }}
                  >
                    <Icon sx={{ fontSize: 19, flexShrink: 0 }} />
                    {expanded && (
                      <Typography noWrap sx={{ fontSize: 12.5, fontWeight: 500 }}>
                        {item.label}
                      </Typography>
                    )}
                  </Stack>
                </NavLink>
              </Tooltip>
            );
          })}
        </Stack>

        <Box
          sx={{
            borderTop: '1px solid rgba(255,255,255,0.25)',
            height: 44,
            display: 'flex',
            alignItems: 'center',
            px: 1.5,
          }}
        >
          <Typography noWrap sx={{ fontSize: 10, opacity: 0.75 }}>
            {expanded ? 'CreditNirvana · synthetic data' : 'CN'}
          </Typography>
        </Box>
      </Box>

      <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <Stack
          direction="row"
          alignItems="center"
          justifyContent="space-between"
          sx={{
            height: 50,
            px: 2.5,
            backgroundColor: tokens.headerBg,
            borderBottom: '1px solid #f3f3f3',
            flexShrink: 0,
          }}
        >
          <Typography sx={{ fontSize: 18, fontWeight: 500, color: '#222933' }}>
            {pageTitle(location.pathname)}
          </Typography>
          <Stack direction="row" alignItems="center" spacing={2}>
            <SimClockMini />
            <BorrowerSearch />
            <Typography sx={{ fontSize: 11, color: tokens.statLabelGrey, display: { xs: 'none', lg: 'block' } }}>
              Judge demo build &middot; all data synthetic
            </Typography>
            <Avatar
              sx={{
                width: 30,
                height: 30,
                fontSize: 13,
                backgroundColor: tokens.navbarBg,
              }}
            >
              CN
            </Avatar>
          </Stack>
        </Stack>

        <Box
          sx={{
            flex: 1,
            overflow: 'auto',
            backgroundColor: tokens.containerBg,
            p: 2.5,
          }}
        >
          <Outlet />
        </Box>
      </Box>

      <Snackbar
        open={!!lastFault}
        autoHideDuration={6000}
        onClose={clearFault}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Alert
          severity="warning"
          variant="filled"
          onClose={clearFault}
          action={
            <Button
              color="inherit"
              size="small"
              onClick={() => {
                navigate(`/trace?account=${lastFault.account_id}`);
                clearFault();
              }}
            >
              Open trace
            </Button>
          }
          sx={{ alignItems: 'center', fontSize: 12 }}
        >
          Fault detected: {lastFault?.decision} on {lastFault?.agent} for {lastFault?.account_id}. The supervisor is recovering it.
        </Alert>
      </Snackbar>
    </Box>
  );
}
