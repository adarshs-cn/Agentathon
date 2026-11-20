import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ThemeProvider, CssBaseline } from '@mui/material';
import { theme } from './theme/muiTheme';
import AppLayout from './layout/AppLayout';
import Overview from './pages/Overview';
import Accounts from './pages/Accounts';
import BorrowerTrace from './pages/BorrowerTrace';
import JourneyRuns from './pages/JourneyRuns';
import Decisions from './pages/Decisions';
import { SimProvider } from './context/SimContext';

export default function App() {
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <BrowserRouter>
        <SimProvider>
        <Routes>
          <Route path="/" element={<AppLayout />}>
            <Route index element={<Overview />} />
            <Route path="accounts" element={<Accounts />} />
            <Route path="trace" element={<BorrowerTrace />} />
            <Route path="runs" element={<JourneyRuns />} />
            <Route path="decisions" element={<Decisions />} />
          </Route>
        </Routes>
        </SimProvider>
      </BrowserRouter>
    </ThemeProvider>
  );
}
