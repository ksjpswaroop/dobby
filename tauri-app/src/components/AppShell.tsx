import { useEffect, useRef, useState, type ReactNode } from 'react';
import { NavLink, useNavigate, useLocation } from 'react-router-dom';
import { cn } from '../lib/cn';
import { useTheme, type Theme } from '../lib/theme';
import { useProject } from '../lib/project';
import { NAV_SECTIONS, sectionForRoute } from '../lib/nav';
import { CommandPalette } from './CommandPalette';
import { TerminalDock } from './TerminalDock';
import api, { type SystemInfo, type ProjectInfo } from '../api/client';
import {
  IconFolder,
  IconChevronRight,
  IconPlus,
  IconCheck,
  IconSearch,
  IconSun,
  IconMoon,
  IconMonitor,
  IconTerminal,
} from '../lib/icons';

/* -------------------------------------------------------------------------- */
/* Project switcher (topbar)                                                   */
/* -------------------------------------------------------------------------- */
function ProjectSwitcher() {
  const { projectId, setProjectId } = useProject();
  const navigate = useNavigate();
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const load = async () => {
    try {
      setProjects(await api.listProjects());
    } catch {
      /* backend may be offline; switcher still renders the id */
    }
  };

  useEffect(() => {
    load();
  }, [projectId]);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  const active = projects.find((p) => p.id === projectId);
  const label = active?.name || (projectId === 'default-project' ? 'My Workspace' : projectId);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 rounded-xl border border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink transition-colors hover:bg-surface2"
        title="Switch project"
      >
        <IconFolder size={15} className="text-brand" />
        <span className="max-w-[200px] truncate">{label}</span>
        <IconChevronRight size={14} className={cn('text-ink-muted transition-transform', open && 'rotate-90')} />
      </button>
      {open && (
        <div className="absolute left-0 top-full z-50 mt-1.5 w-64 animate-scale-in rounded-xl border border-line bg-surface p-1.5 shadow-pop">
          <div className="max-h-64 overflow-y-auto">
            {projects.length === 0 && (
              <div className="px-3 py-2 text-xs text-ink-muted">No projects found.</div>
            )}
            {projects.map((p) => (
              <button
                key={p.id}
                onClick={() => {
                  setProjectId(p.id);
                  setOpen(false);
                }}
                className={cn(
                  'flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm transition-colors',
                  p.id === projectId ? 'bg-brand/10 text-brand' : 'text-ink hover:bg-surface2'
                )}
              >
                <span className="flex-1 truncate">{p.name}</span>
                {p.id === projectId && <IconCheck size={14} />}
              </button>
            ))}
          </div>
          <div className="mt-1 border-t border-line pt-1">
            <button
              onClick={() => {
                setOpen(false);
                navigate('/projects');
              }}
              className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm text-ink-muted transition-colors hover:bg-surface2 hover:text-ink"
            >
              <IconPlus size={14} /> New / manage projects
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Theme toggle                                                                */
/* -------------------------------------------------------------------------- */
function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const options: { value: Theme; icon: typeof IconSun; label: string }[] = [
    { value: 'light', icon: IconSun, label: 'Light' },
    { value: 'system', icon: IconMonitor, label: 'System' },
    { value: 'dark', icon: IconMoon, label: 'Dark' },
  ];
  return (
    <div className="flex items-center gap-0.5 rounded-xl border border-line bg-surface p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => setTheme(o.value)}
          title={o.label}
          aria-label={o.label}
          className={cn(
            'flex h-7 w-7 items-center justify-center rounded-lg transition-colors',
            theme === o.value
              ? 'bg-brand/10 text-brand'
              : 'text-ink-muted hover:bg-surface2 hover:text-ink'
          )}
        >
          <o.icon size={15} />
        </button>
      ))}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Connection status pill (polls the backend)                                  */
/* -------------------------------------------------------------------------- */
function StatusPill() {
  const [info, setInfo] = useState<SystemInfo | null>(null);
  const [reachedBackend, setReachedBackend] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const data = await api.getSystemInfo();
        if (!cancelled) {
          setInfo(data);
          setReachedBackend(true);
        }
      } catch {
        if (!cancelled) setReachedBackend(false);
      }
    };
    poll();
    const id = window.setInterval(poll, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  const online = reachedBackend && info?.ollama_reachable;
  const dotColor = online ? 'bg-success' : reachedBackend === false ? 'bg-danger' : 'bg-warning';
  const label = !reachedBackend
    ? 'Backend offline'
    : info?.ollama_reachable
    ? info.active_model
    : 'Ollama offline';

  return (
    <NavLink
      to="/settings"
      className="flex items-center gap-2 rounded-xl border border-line bg-surface px-3 py-1.5 text-xs font-medium text-ink-muted transition-colors hover:bg-surface2 hover:text-ink"
      title="Ollama connection & model — open Settings"
    >
      <span className="relative flex h-2 w-2">
        {online && (
          <span className={cn('absolute inline-flex h-full w-full animate-ping rounded-full opacity-70', dotColor)} />
        )}
        <span className={cn('relative inline-flex h-2 w-2 rounded-full', dotColor)} />
      </span>
      <span className="max-w-[160px] truncate">{label}</span>
    </NavLink>
  );
}

/* -------------------------------------------------------------------------- */
/* Shell                                                                       */
/* -------------------------------------------------------------------------- */
/* -------------------------------------------------------------------------- */
/* Command Center trigger (topbar search) — opens the ⌘K palette               */
/* -------------------------------------------------------------------------- */
function CommandTrigger({ onOpen }: { onOpen: () => void }) {
  return (
    <button
      onClick={onOpen}
      className="flex items-center gap-2 rounded-xl border border-line bg-surface px-3 py-1.5 text-sm text-ink-muted transition-colors hover:bg-surface2 hover:text-ink"
      title="Search & commands (⌘K)"
    >
      <IconSearch size={15} />
      <span className="hidden sm:inline">Search…</span>
      <kbd className="ml-1 rounded-md border border-line bg-surface2 px-1.5 py-0.5 text-[10px] text-ink-muted">
        ⌘K
      </kbd>
    </button>
  );
}

/* -------------------------------------------------------------------------- */
/* Section tabs — the "app-in-app" strip under the header                      */
/* -------------------------------------------------------------------------- */
function SectionTabs() {
  const { pathname } = useLocation();
  const section = sectionForRoute(pathname);
  // A single-tab section is just a page; don't show a strip for it.
  if (!section || section.items.length < 2) return null;

  return (
    <div className="flex h-11 shrink-0 items-center gap-1 border-b border-line bg-surface/40 px-6">
      {section.items.map((i) => (
        <NavLink
          key={i.route}
          to={i.route}
          end={i.route === '/'}
          className={({ isActive }) =>
            cn(
              'flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[13px] font-medium transition-colors',
              isActive
                ? 'bg-brand/10 text-brand'
                : 'text-ink-muted hover:bg-surface2 hover:text-ink'
            )
          }
        >
          {i.label}
          {i.status === 'planned' && (
            <span className="rounded bg-surface2 px-1 py-px text-[9px] uppercase tracking-wide text-ink-muted">
              soon
            </span>
          )}
        </NavLink>
      ))}
    </div>
  );
}

export default function AppShell({ children }: { children: ReactNode }) {
  const version = '2.0';
  const { pathname } = useLocation();
  const [paletteOpen, setPaletteOpen] = useState(false);
  // The terminal is a dock, not a page: remembered across reloads so it is
  // where you left it.
  const [terminalOpen, setTerminalOpen] = useState(
    () => localStorage.getItem('dobby-terminal-open') === '1'
  );

  const toggleTerminal = () =>
    setTerminalOpen((v) => {
      localStorage.setItem('dobby-terminal-open', v ? '0' : '1');
      return !v;
    });

  // A sidebar verb is active when the current route is one of its sub-surfaces.
  const isSectionActive = (
    items: { route: string }[],
    sectionRoute: string
  ) => items.some((i) => i.route === pathname) || pathname === sectionRoute;

  // Global ⌘K / Ctrl-K to open the command center.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
      // Ctrl+` — what every editor uses for its integrated terminal.
      if ((e.metaKey || e.ctrlKey) && (e.key === '`' || e.key === '~')) {
        e.preventDefault();
        setTerminalOpen((v) => {
          localStorage.setItem('dobby-terminal-open', v ? '0' : '1');
          return !v;
        });
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <div className="flex h-screen overflow-hidden bg-bg text-ink">
      {/* Sidebar */}
      <aside className="flex w-60 shrink-0 flex-col border-r border-line bg-surface/60">
        <div className="flex h-14 items-center gap-2.5 px-5">
          <img src="/icon.svg" alt="" className="h-7 w-7 rounded-lg" />
          <span className="text-[15px] font-semibold tracking-tight">Dobby</span>
          <span className="ml-auto rounded-md bg-surface2 px-1.5 py-0.5 text-[10px] font-medium text-ink-muted">
            v{version}
          </span>
        </div>

        {/* Five verbs, not fifteen links. Sub-surfaces live in the tab strip. */}
        <nav className="flex flex-1 flex-col gap-0.5 overflow-y-auto p-3">
          {NAV_SECTIONS.map(({ label, route, icon: Icon, hint, items }) => (
            <NavLink
              key={label}
              to={route}
              end={route === '/'}
              title={hint}
              className={() =>
                cn('nav-link', isSectionActive(items, route) && 'nav-link-active')
              }
            >
              <Icon size={17} />
              <span className="flex-1">{label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-line p-3">
          <p className="px-2 text-[11px] leading-relaxed text-ink-muted">
            Local-first · runs on Ollama
          </p>
        </div>
      </aside>

      {/* Main column */}
      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-line bg-surface/60 px-6 backdrop-blur">
          <ProjectSwitcher />
          <div className="flex items-center gap-3">
            <CommandTrigger onOpen={() => setPaletteOpen(true)} />
            <button
              onClick={toggleTerminal}
              aria-pressed={terminalOpen}
              title="Terminal (⌃`)"
              aria-label="Toggle the terminal"
              className={
                'flex h-8 w-8 items-center justify-center rounded-xl transition-colors ' +
                (terminalOpen
                  ? 'bg-brand/10 text-brand'
                  : 'text-ink-muted hover:bg-surface2 hover:text-ink')
              }
            >
              <IconTerminal size={15} />
            </button>
            <StatusPill />
            <ThemeToggle />
          </div>
        </header>

        <SectionTabs />

        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-6xl animate-fade-in px-6 py-8">{children}</div>
        </main>

        <TerminalDock open={terminalOpen} onClose={toggleTerminal} />
      </div>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  );
}
