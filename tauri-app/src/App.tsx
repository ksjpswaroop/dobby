import { Routes, Route, Navigate } from 'react-router-dom';
import AppShell from './components/AppShell';
import Dashboard from './pages/Dashboard';
import Projects from './pages/Projects';
import Documents from './pages/Documents';
import DocumentEditor from './pages/DocumentEditor';
import Research from './pages/Research';
import Copilot from './pages/Copilot';
import ModelUsage from './pages/ModelUsage';
import Automations from './pages/Automations';
import Inbox from './pages/Inbox';
import Ideas from './pages/Ideas';
import Transcribe from './pages/Transcribe';
import Connections from './pages/Connections';
import Wizard from './pages/Wizard';
import Yolo from './pages/Yolo';
import GraphPage from './pages/GraphPage';
import BacklogPage from './pages/BacklogPage';
import BoardPage from './pages/Board';
import Bulk from './pages/Bulk';
import Settings from './pages/Settings';
import Planned from './pages/Planned';
import Logs from './pages/Logs';
import Activity from './pages/Activity';
import Search from './pages/Search';
import CommandCenter from './pages/CommandCenter';
import MindMapPage from './pages/MindMapPage';

// Planned surfaces (on the roadmap) render a consistent "coming soon" placeholder.
const PLANNED_ROUTES = [
  '/prototypes', '/video', '/youtube', '/notes',
  '/skills', '/flows', '/control',
  '/marketplace',
];

function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/projects" element={<Projects />} />
        <Route path="/documents" element={<Documents />} />
        <Route path="/documents/:nodeId" element={<DocumentEditor />} />
        <Route path="/research" element={<Research />} />
        <Route path="/copilot" element={<Copilot />} />
        <Route path="/usage" element={<ModelUsage />} />
        <Route path="/automations" element={<Automations />} />
        <Route path="/inbox" element={<Inbox />} />
        <Route path="/ideas" element={<Ideas />} />
        <Route path="/transcribe" element={<Transcribe />} />
        {/* The terminal is a bottom dock now (⌃`), not a page. */}
        <Route path="/terminal" element={<Navigate to="/logs" replace />} />
        <Route path="/connections" element={<Connections />} />
        <Route path="/backlog" element={<BacklogPage />} />
        <Route path="/board" element={<BoardPage />} />
        <Route path="/wizard" element={<Wizard />} />
        <Route path="/yolo" element={<Yolo />} />
        <Route path="/bulk" element={<Bulk />} />
        <Route path="/graph" element={<GraphPage />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/logs" element={<Logs />} />
        <Route path="/activity" element={<Activity />} />
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
