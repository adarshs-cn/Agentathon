import { useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import {
  Box,
  Stack,
  Typography,
  Avatar,
  Tooltip,
} from '@mui/material';
import TowerControlIcon from '@mui/icons-material/CellTower';
import ViewListIcon from '@mui/icons-material/ViewListOutlined';
import AccountTreeIcon from '@mui/icons-material/AccountTreeOutlined';
import HistoryIcon from '@mui/icons-material/History';
import ListAltIcon from '@mui/icons-material/ListAltOutlined';
import { tokens } from '../theme/muiTheme';
import { OVERVIEW_TITLE, STUDIO_TITLE } from '../config/labels';
import MonitorPill from '../components/MonitorPill';
import SimClockMini from '../components/SimClockMini';
import NotificationBell, { FaultToast } from '../components/NotificationBell';

const NAV_GROUPS = [
  {
    module: 'Journey Supervisor',
    items: [
      { to: '/', label: OVERVIEW_TITLE, icon: TowerControlIcon, end: true },
      { to: '/studio', label: STUDIO_TITLE, icon: AccountTreeIcon },
      { to: '/runs', label: 'Journey Runs', icon: HistoryIcon },
      { to: '/decisions', label: 'Decision Log', icon: ListAltIcon },
    ],
  },
  {
    module: 'Loan Management',
    items: [
      { to: '/accounts', label: 'Accounts', icon: ViewListIcon },
    ],
  },
];
const NAV_ITEMS = NAV_GROUPS.flatMap((g) => g.items).concat([{ to: '/trace', label: 'Customer Trace' }]);

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
        </Stack>

        <Stack sx={{ mt: 1, flex: 1 }}>
          {NAV_GROUPS.map((g) => (
          <Box key={g.module} sx={{ mb: 1 }}>
            {expanded ? (
              <Typography sx={{ fontSize: 10, letterSpacing: 0.8, textTransform: 'uppercase', opacity: 0.6, px: 2, py: 0.6 }}>
                {g.module}
              </Typography>
            ) : (
              <Box sx={{ mx: 1.5, my: 0.6, borderTop: '1px solid rgba(255,255,255,0.2)' }} />
            )}
          {g.items.map((item) => {
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
          </Box>
        ))}
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
            <MonitorPill />
            <NotificationBell />
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

      <FaultToast />
    </Box>
  );
}
