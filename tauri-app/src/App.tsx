import { Routes, Route, Navigate } from 'react-router-dom';
import AppShell from './components/AppShell';
import Dashboard from './pages/Dashboard';
import Projects from './pages/Projects';
import Documents from './pages/Documents';
import Research from './pages/Research';
import Automations from './pages/Automations';
import Inbox from './pages/Inbox';
import Wizard from './pages/Wizard';
import Yolo from './pages/Yolo';
import GraphPage from './pages/GraphPage';
import BacklogPage from './pages/BacklogPage';
import Bulk from './pages/Bulk';
import Settings from './pages/Settings';
import Planned from './pages/Planned';
import Logs from './pages/Logs';
import Search from './pages/Search';
import CommandCenter from './pages/CommandCenter';
import MindMapPage from './pages/MindMapPage';

// Planned surfaces (on the roadmap) render a consistent "coming soon" placeholder.
const PLANNED_ROUTES = [
  '/prototypes', '/video', '/transcribe', '/youtube', '/notes',
  '/skills', '/flows', '/terminal', '/control',
  '/marketplace',
];

function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/projects" element={<Projects />} />
        <Route path="/documents" element={<Documents />} />
        <Route path="/research" element={<Research />} />
        <Route path="/automations" element={<Automations />} />
        <Route path="/inbox" element={<Inbox />} />
        <Route path="/backlog" element={<BacklogPage />} />
        <Route path="/wizard" element={<Wizard />} />
        <Route path="/yolo" element={<Yolo />} />
        <Route path="/bulk" element={<Bulk />} />
        <Route path="/graph" element={<GraphPage />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/logs" element={<Logs />} />
        <Route path="/search" element={<Search />} />
        <Route path="/mindmap" element={<MindMapPage />} />
        {/* The Command Center *is* the ⌘K palette; this route just opens it. */}
        <Route path="/command" element={<CommandCenter />} />
        {/* Section landings redirect to their first *working* tab. Sending a
            sidebar click to a planned route made two of the five verbs open on
            a "coming soon" card while live tabs sat one along from it. */}
        <Route path="/create" element={<Navigate to="/wizard" replace />} />
        <Route path="/automate" element={<Navigate to="/automations" replace />} />
        <Route path="/develop" element={<Navigate to="/logs" replace />} />
        {PLANNED_ROUTES.map((r) => (
          <Route key={r} path={r} element={<Planned />} />
        ))}
        {/* Anything else would otherwise render the shell around an empty page. */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  );
}

export default App;
