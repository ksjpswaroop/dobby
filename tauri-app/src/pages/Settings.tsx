import { useEffect, useState } from 'react';
import api, { AppSettings, ModelInfo, SystemInfo } from '../api/client';
import { Card, Button, PageHeader, Badge, Spinner, LoadingState, ErrorState } from '../components/ui';
import { useTheme, type Theme } from '../lib/theme';
import { useToast } from '../lib/toast';
import {
  IconServer,
  IconCpu,
  IconDownload,
  IconTrash,
  IconRefresh,
  IconCheck,
  IconSun,
  IconMoon,
  IconMonitor,
  IconResearch,
} from '../lib/icons';

/** Search backends for the Research stage. `remote` = the query leaves the machine. */
const SEARCH_PROVIDERS: { id: string; label: string; blurb: string; remote: boolean }[] = [
  { id: 'none', label: 'Off', remote: false,
    blurb: 'Model knowledge only. No network calls. Unsourced claims are flagged.' },
  { id: 'wigolo', label: 'wigolo (recommended)', remote: false,
    blurb: 'Real multi-engine web search from a local daemon. No API key, nothing leaves your machine.' },
  { id: 'searxng', label: 'SearXNG', remote: false,
    blurb: 'Your own instance — stays on your machine or network.' },
  { id: 'tavily', label: 'Tavily', remote: true,
    blurb: 'Hosted search built for AI agents. Needs an API key.' },
  { id: 'brave', label: 'Brave Search', remote: true,
    blurb: 'Independent index. Needs an API key.' },
];

function formatBytes(bytes?: number): string {
  if (!bytes) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let n = bytes;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n.toFixed(n >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

function Section({
  icon,
  title,
  description,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <Card className="p-5">
      <div className="mb-4 flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand/10 text-brand">
          {icon}
        </span>
        <div>
          <h2 className="font-semibold">{title}</h2>
          {description && <p className="text-sm text-ink-muted">{description}</p>}
        </div>
      </div>
      {children}
    </Card>
  );
}

export default function Settings() {
  const { theme, setTheme } = useTheme();
  const { toast } = useToast();

  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [host, setHost] = useState('');
  const [savingHost, setSavingHost] = useState(false);
  const [threshold, setThreshold] = useState(85);
  const [searchProvider, setSearchProvider] = useState('none');
  const [searxngUrl, setSearxngUrl] = useState('');
  const [wigoloUrl, setWigoloUrl] = useState('http://127.0.0.1:3333');
  const [symbolicaUrl, setSymbolicaUrl] = useState('');

  const [pullName, setPullName] = useState('');
  const [pulling, setPulling] = useState(false);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [busyModel, setBusyModel] = useState<string | null>(null);

  const loadAll = async () => {
    try {
      setLoading(true);
      setError(null);
      const [s, sys] = await Promise.all([api.getSettings(), api.getSystemInfo()]);
      setSettings(s);
      setSystem(sys);
      setHost(s.ollama_host);
      setThreshold(s.verification_threshold);
      setSearchProvider(s.search_provider || 'none');
      setSearxngUrl(s.searxng_url || '');
      setWigoloUrl(s.wigolo_url || 'http://127.0.0.1:3333');
      setSymbolicaUrl(s.symbolica_url || '');
      loadModels();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load settings');
    } finally {
      setLoading(false);
    }
  };

  const loadModels = async () => {
    try {
      setModelsLoading(true);
      setModelsError(null);
      setModels(await api.listModels());
    } catch (err) {
      setModelsError(err instanceof Error ? err.message : 'Cannot reach Ollama');
    } finally {
      setModelsLoading(false);
    }
  };

  useEffect(() => {
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const saveHost = async () => {
    try {
      setSavingHost(true);
      const s = await api.updateSettings({ ollama_host: host.trim() });
      setSettings(s);
      toast('Ollama host updated', 'success');
      await Promise.all([loadModels(), api.getSystemInfo().then(setSystem)]);
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Failed to update host', 'error');
    } finally {
      setSavingHost(false);
    }
  };

  const saveThreshold = async (value: number) => {
    setThreshold(value);
    try {
      const s = await api.updateSettings({ verification_threshold: value });
      setSettings(s);
    } catch {
      /* silent — non-critical */
    }
  };

  const saveSearch = async (patch: Parameters<typeof api.updateSettings>[0]) => {
    if (patch.search_provider) setSearchProvider(patch.search_provider);
    if (patch.searxng_url !== undefined) setSearxngUrl(patch.searxng_url);
    if (patch.wigolo_url !== undefined) setWigoloUrl(patch.wigolo_url);
    if (patch.symbolica_url !== undefined) setSymbolicaUrl(patch.symbolica_url);
    try {
      setSettings(await api.updateSettings(patch));
      toast('Search settings saved', 'success');
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Failed to save', 'error');
    }
  };

  const setActive = async (name: string) => {
    try {
      setBusyModel(name);
      const s = await api.updateSettings({ model: name });
      setSettings(s);
      setModels((prev) => prev.map((m) => ({ ...m, active: m.name === name })));
      setSystem((prev) => (prev ? { ...prev, active_model: name } : prev));
      toast(`Active model set to ${name}`, 'success');
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Failed to set model', 'error');
    } finally {
      setBusyModel(null);
    }
  };

  const pull = async () => {
    const name = pullName.trim();
    if (!name) return;
    try {
      setPulling(true);
      await api.pullModel(name);
      toast(`Pulled ${name}`, 'success');
      setPullName('');
      loadModels();
    } catch (err) {
      toast(err instanceof Error ? err.message : `Failed to pull ${name}`, 'error');
    } finally {
      setPulling(false);
    }
  };

  const remove = async (name: string) => {
    if (!window.confirm(`Remove model "${name}" from Ollama? This deletes the local download.`)) return;
    try {
      setBusyModel(name);
      await api.deleteModel(name);
      toast(`Removed ${name}`, 'success');
      loadModels();
    } catch (err) {
      toast(err instanceof Error ? err.message : `Failed to remove ${name}`, 'error');
    } finally {
      setBusyModel(null);
    }
  };

  if (loading) return <LoadingState label="Loading settings…" />;
  if (error) return <ErrorState message={error} onRetry={loadAll} />;

  const themeOptions: { value: Theme; icon: typeof IconSun; label: string }[] = [
    { value: 'light', icon: IconSun, label: 'Light' },
    { value: 'system', icon: IconMonitor, label: 'System' },
    { value: 'dark', icon: IconMoon, label: 'Dark' },
  ];

  return (
    <div className="space-y-5">
      <PageHeader title="Settings" subtitle="Manage models, connection, and appearance." />

      {/* System / versions */}
      <Section icon={<IconServer size={18} />} title="System" description="Versions and connectivity.">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="App" value={`v${system?.app_version ?? '—'}`} />
          <Stat label="Python" value={system?.python_version ?? '—'} />
          <Stat
            label="Ollama"
            value={system?.ollama_reachable ? system?.ollama_version ?? 'connected' : 'offline'}
            tone={system?.ollama_reachable ? 'success' : 'danger'}
          />
          <Stat label="Platform" value={system?.platform ?? '—'} />
        </div>
      </Section>

      {/* Connection */}
      <Section
        icon={<IconServer size={18} />}
        title="Ollama connection"
        description="Where Dobby sends generation requests."
      >
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-[240px] flex-1">
            <label className="label">Host URL</label>
            <input
              className="input"
              value={host}
              onChange={(e) => setHost(e.target.value)}
              placeholder="http://localhost:11434"
            />
          </div>
          <Button
            variant="primary"
            loading={savingHost}
            onClick={saveHost}
            disabled={host.trim() === settings?.ollama_host}
          >
            Save
          </Button>
        </div>
      </Section>

      {/* Models */}
      <Section
        icon={<IconCpu size={18} />}
        title="Models"
        description="Choose the active model, pull new ones, or remove downloads."
      >
        {/* Pull */}
        <div className="mb-4 flex flex-wrap items-end gap-2">
          <div className="min-w-[240px] flex-1">
            <label className="label">Pull a model</label>
            <input
              className="input"
              value={pullName}
              onChange={(e) => setPullName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && pull()}
              placeholder="e.g., llama3.2, mistral, qwen2.5:7b"
            />
          </div>
          <Button variant="secondary" icon={<IconDownload size={16} />} loading={pulling} onClick={pull}>
            {pulling ? 'Pulling…' : 'Pull'}
          </Button>
          <Button
            variant="ghost"
            icon={<IconRefresh size={16} />}
            onClick={loadModels}
            loading={modelsLoading}
            aria-label="Refresh models"
          />
        </div>

        {/* List */}
        {modelsError ? (
          <div className="rounded-xl border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">
            {modelsError}
          </div>
        ) : modelsLoading ? (
          <div className="flex items-center gap-2 py-6 text-sm text-ink-muted">
            <Spinner size={16} /> Loading models…
          </div>
        ) : models.length === 0 ? (
          <p className="py-6 text-center text-sm text-ink-muted">
            No models installed. Pull one above (e.g., <span className="font-mono">llama3.2</span>).
          </p>
        ) : (
          <div className="space-y-2">
            {models.map((m) => (
              <div
                key={m.name}
                className="flex items-center justify-between gap-3 rounded-xl border border-line bg-surface2/50 px-4 py-3"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="truncate font-mono text-sm font-medium">{m.name}</span>
                    {m.active && <Badge tone="success">active</Badge>}
                  </div>
                  <p className="mt-0.5 text-xs text-ink-muted">
                    {[m.parameter_size, m.family, formatBytes(m.size)].filter(Boolean).join(' · ')}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  {m.active ? (
                    <span className="flex items-center gap-1 px-2 text-sm text-success">
                      <IconCheck size={16} /> In use
                    </span>
                  ) : (
                    <Button
                      variant="secondary"
                      onClick={() => setActive(m.name)}
                      loading={busyModel === m.name}
                    >
                      Set active
                    </Button>
                  )}
                  <button
                    onClick={() => remove(m.name)}
                    disabled={busyModel === m.name}
                    className="rounded-lg p-2 text-ink-muted transition-colors hover:bg-danger/10 hover:text-danger disabled:opacity-50"
                    aria-label={`Remove ${m.name}`}
                    title="Remove"
                  >
                    <IconTrash size={16} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* Generation */}
      <Section
        icon={<IconCheck size={18} />}
        title="Verification"
        description="Minimum score an artifact must reach to pass."
      >
        <div className="flex items-center gap-4">
          <input
            type="range"
            min={0}
            max={100}
            value={threshold}
            onChange={(e) => saveThreshold(Number(e.target.value))}
            className="h-1.5 flex-1 cursor-pointer appearance-none rounded-full bg-surface2 accent-brand"
          />
          <span className="w-12 text-right text-lg font-semibold text-brand">{threshold}</span>
        </div>
      </Section>

      {/* Research search */}
      <Section
        icon={<IconResearch size={18} />}
        title="Research search"
        description="Where the Research stage looks things up. Off by default — Dobby makes no network calls beyond your local model unless you turn this on."
      >
        <div className="space-y-3">
          <div className="grid gap-2 sm:grid-cols-2">
            {SEARCH_PROVIDERS.map((p) => (
              <button
                key={p.id}
                onClick={() => saveSearch({ search_provider: p.id })}
                aria-pressed={searchProvider === p.id}
                className={
                  'rounded-xl border px-3 py-2.5 text-left transition-colors ' +
                  (searchProvider === p.id
                    ? 'border-brand bg-brand/5'
                    : 'border-line hover:border-brand/50')
                }
              >
                <span className="flex items-center gap-1.5 text-sm font-medium text-ink">
                  {p.label}
                  {p.remote && (
                    <span className="rounded px-1 py-px text-[10px] uppercase tracking-wide text-warning ring-1 ring-warning/40">
                      leaves device
                    </span>
                  )}
                </span>
                <span className="mt-0.5 block text-[11px] text-ink-muted">{p.blurb}</span>
              </button>
            ))}
          </div>

          {searchProvider === 'wigolo' && (
            <div className="rounded-xl border border-line bg-surface2/40 px-3 py-2.5">
              <p className="text-[12px] text-ink">
                wigolo is a separate local daemon. Install and start it once:
              </p>
              <pre className="mt-1.5 overflow-x-auto rounded-lg bg-surface px-2.5 py-1.5 font-mono text-[11px] text-ink-muted">
npx wigolo init{'\n'}wigolo serve
              </pre>
              <label className="mt-2 block">
                <span className="mb-1 block text-[11px] font-medium text-ink-muted">
                  Daemon URL
                </span>
                <input
                  className="input w-full"
                  placeholder="http://127.0.0.1:3333"
                  defaultValue={wigoloUrl}
                  onBlur={(e) => saveSearch({ wigolo_url: e.target.value.trim() })}
                />
              </label>
              <p className="mt-1.5 text-[11px] text-ink-muted">
                wigolo is AGPL-3.0 and runs as its own process — Dobby calls it over
                REST and ships none of its code.
              </p>
            </div>
          )}
          {searchProvider === 'searxng' && (
            <label className="block">
              <span className="mb-1 block text-[12px] font-medium text-ink">SearXNG URL</span>
              <input
                className="input w-full"
                placeholder="http://localhost:8888"
                defaultValue={searxngUrl}
                onBlur={(e) => saveSearch({ searxng_url: e.target.value.trim() })}
              />
            </label>
          )}
          {(searchProvider === 'tavily' || searchProvider === 'brave') && (
            <label className="block">
              <span className="mb-1 block text-[12px] font-medium text-ink">
                {searchProvider === 'tavily' ? 'Tavily' : 'Brave Search'} API key
              </span>
              <input
                type="password"
                className="input w-full"
                placeholder="Paste your key"
                onBlur={(e) => {
                  const v = e.target.value.trim();
                  if (v) {
                    saveSearch(
                      searchProvider === 'tavily'
                        ? { tavily_api_key: v }
                        : { brave_api_key: v }
                    );
                    e.target.value = '';
                  }
                }}
              />
              <span className="mt-1 block text-[11px] text-ink-muted">
                Stored locally in ~/.dobby/settings.json. Search queries are sent to
                this provider.
              </span>
            </label>
          )}
        </div>
      </Section>

      {/* Reasoning */}
      <Section
        icon={<IconCheck size={18} />}
        title="Reasoning"
        description="Dobby machine-checks research findings for contradictions using a built-in classical logic prover. Symbolica adds first-order logic and proof objects."
      >
        <div className="space-y-3">
          <div className="rounded-xl border border-line bg-surface2/40 px-3 py-2.5 text-[12px] text-ink-muted">
            <span className="font-medium text-ink">Always on:</span> a complete
            decision procedure for propositional logic runs locally with no
            configuration. Contradictions between research tracks are found and
            reported whether or not anything below is set.
          </div>
          <label className="block">
            <span className="mb-1 block text-[12px] font-medium text-ink">
              Symbolica URL <span className="text-ink-muted">(optional)</span>
            </span>
            <input
              className="input w-full"
              placeholder="https://your-symbolica-host"
              defaultValue={symbolicaUrl}
              onBlur={(e) => saveSearch({ symbolica_url: e.target.value.trim() })}
            />
          </label>
          {symbolicaUrl && (
            <label className="block">
              <span className="mb-1 block text-[12px] font-medium text-ink">
                Symbolica API key
              </span>
              <input
                type="password"
                className="input w-full"
                placeholder="Paste your key"
                onBlur={(e) => {
                  const v = e.target.value.trim();
                  if (v) {
                    saveSearch({ symbolica_api_key: v });
                    e.target.value = '';
                  }
                }}
              />
            </label>
          )}
          <p className="text-[11px] text-ink-muted">
            When unreachable, reasoning falls back to the local prover rather than
            failing — the engine that answered is always named in the result.
          </p>
        </div>
      </Section>

      {/* Appearance */}
      <Section icon={<IconMonitor size={18} />} title="Appearance" description="Theme for the app.">
        <div className="flex gap-2">
          {themeOptions.map((o) => (
            <button
              key={o.value}
              onClick={() => setTheme(o.value)}
              className={
                'flex flex-1 items-center justify-center gap-2 rounded-xl border px-4 py-3 text-sm font-medium transition-colors ' +
                (theme === o.value
                  ? 'border-brand bg-brand/10 text-brand'
                  : 'border-line text-ink-muted hover:bg-surface2 hover:text-ink')
              }
            >
              <o.icon size={16} />
              {o.label}
            </button>
          ))}
        </div>
      </Section>
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: 'success' | 'danger';
}) {
  return (
    <div className="rounded-xl bg-surface2/50 px-3.5 py-3">
      <p className="text-xs text-ink-muted">{label}</p>
      <p
        className={
          'mt-0.5 truncate text-sm font-medium ' +
          (tone === 'success' ? 'text-success' : tone === 'danger' ? 'text-danger' : 'text-ink')
        }
        title={value}
      >
        {value}
      </p>
    </div>
  );
}
