import { createTheme } from '@mui/material/styles';

export const tokens = {
  navbarBg: '#034e63',
  navbarColor: '#ffffff',
  navbarHoverBg: '#b2bac2',
  navbarHoverColor: '#034e63',
  primaryButtonBg: '#61ce70',
  secondaryButtonBorder: '#61ce70',
  actionPrimaryBg: '#ffdd64',
  actionIconColor: '#0088d1',
  containerBg: '#f8f9fc',
  headerBg: '#ffffff',
  cardShadow: 'rgba(151, 151, 154, 0.2) 0px 7px 25px 0px',
  statTitleGrey: '#595959',
  statLabelGrey: '#646464',
  statValueGrey: '#444444',
  iconBadgeBg: '#e9eff7',
  dividerGrey: '#dbdbdb',
  linkBlue: '#4baeea',
  cardGroupedBg: '#f8f8f8',
  statusHealthy: '#61ce70',
  statusDegraded: '#ffdd64',
  statusFault: '#d32f2f',
  fontMono: "'JetBrains Mono', 'Roboto Mono', ui-monospace, monospace",
};

export const theme = createTheme({
  palette: {
    mode: 'light',
    primary: { main: tokens.navbarBg, contrastText: '#ffffff' },
    secondary: { main: tokens.primaryButtonBg },
    success: { main: tokens.statusHealthy },
    warning: { main: tokens.statusDegraded },
    error: { main: tokens.statusFault },
    background: {
      default: tokens.containerBg,
      paper: tokens.headerBg,
    },
    text: {
      primary: '#222933',
      secondary: tokens.statLabelGrey,
    },
  },
  typography: {
    fontFamily: "'Inter', sans-serif",
    fontSize: 12,
    h1: { fontSize: 20, fontWeight: 600 },
    h2: { fontSize: 18, fontWeight: 500 },
    h6: { fontSize: 14, fontWeight: 600, color: tokens.statTitleGrey },
    body2: { fontSize: 12 },
    caption: { fontSize: 11 },
  },
  shape: { borderRadius: 10 },
  components: {
    MuiButton: {
      styleOverrides: {
        root: { textTransform: 'none', fontWeight: 500, borderRadius: 8 },
        containedPrimary: {
          backgroundColor: tokens.primaryButtonBg,
          borderColor: tokens.primaryButtonBg,
          color: '#ffffff',
          '&:hover': { backgroundColor: '#4fb75f' },
        },
        outlinedPrimary: {
          backgroundColor: '#ffffff',
          borderColor: tokens.secondaryButtonBorder,
          color: tokens.navbarBg,
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          boxShadow: tokens.cardShadow,
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: { fontWeight: 500 },
      },
    },
  },
});
