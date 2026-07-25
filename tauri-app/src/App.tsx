import { Routes, Route, Navigate } from 'react-router-dom';
import AppShell from './components/AppShell';
import Dashboard from './pages/Dashboard';
import Projects from './pages/Projects';
import Documents from './pages/Documents';
import Wizard from './pages/Wizard';
import Yolo from './pages/Yolo';
import GraphPage from './pages/GraphPage';
import BacklogPage from './pages/BacklogPage';
import Bulk from './pages/Bulk';
import Settings from './pages/Settings';
import Planned from './pages/Planned';

// Planned surfaces (on the roadmap) render a consistent "coming soon" placeholder.
const PLANNED_ROUTES = [
  '/mindmap', '/prototypes', '/video', '/transcribe', '/youtube', '/notes',
  '/command', '/skills', '/flows', '/terminal', '/logs', '/control',
  '/search', '/marketplace',
];

function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/projects" element={<Projects />} />
        <Route path="/documents" element={<Documents />} />
        <Route path="/backlog" element={<BacklogPage />} />
        <Route path="/wizard" element={<Wizard />} />
        <Route path="/yolo" element={<Yolo />} />
        <Route path="/bulk" element={<Bulk />} />
        <Route path="/graph" element={<GraphPage />} />
        <Route path="/settings" element={<Settings />} />
        {/* Section landings redirect to their first tab. */}
        <Route path="/create" element={<Navigate to="/wizard" replace />} />
        <Route path="/automate" element={<Navigate to="/skills" replace />} />
        <Route path="/develop" element={<Navigate to="/terminal" replace />} />
        {PLANNED_ROUTES.map((r) => (
          <Route key={r} path={r} element={<Planned />} />
        ))}
      </Routes>
    </AppShell>
  );
}

export default App;
