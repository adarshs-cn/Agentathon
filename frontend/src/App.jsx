import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ThemeProvider, CssBaseline } from '@mui/material';
import { theme } from './theme/muiTheme';
import AppLayout from './layout/AppLayout';
import Overview from './pages/Overview';
import Accounts from './pages/Accounts';
import BorrowerTrace from './pages/BorrowerTrace';
import Faults from './pages/Faults';
import Agents from './pages/Agents';
import Ownership from './pages/Ownership';
import Budgets from './pages/Budgets';
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
            <Route path="faults" element={<Faults />} />
            <Route path="agents" element={<Agents />} />
            <Route path="ownership" element={<Ownership />} />
            <Route path="budgets" element={<Budgets />} />
            <Route path="decisions" element={<Decisions />} />
          </Route>
        </Routes>
        </SimProvider>
      </BrowserRouter>
    </ThemeProvider>
  );
}
