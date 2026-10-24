import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api, { ProjectInfo } from '../api/client';
import { Button, PageHeader, Badge, LoadingState, ErrorState, EmptyState } from '../components/ui';
import { Modal } from '../components/Modal';
import { IconPlus, IconGraph, IconChevronRight, IconCheck } from '../lib/icons';
import { useToast } from '../lib/toast';
import { useProject } from '../lib/project';

export default function Projects() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const { projectId, setProjectId } = useProject();

  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showAdd, setShowAdd] = useState(false);
  const [name, setName] = useState('');
  const [idea, setIdea] = useState('');
  const [description, setDescription] = useState('');
  const [saving, setSaving] = useState(false);

  const load = async () => {
    try {
      setLoading(true);
      setError(null);
      setProjects(await api.listProjects());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load projects');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const openProject = (p: ProjectInfo) => {
    setProjectId(p.id);
    navigate('/documents');
  };

  const handleCreate = async () => {
    if (!name.trim() || !idea.trim()) {
      toast('Enter a name and a product idea', 'error');
      return;
    }
    try {
      setSaving(true);
      const created = await api.createProject(name.trim(), idea.trim(), description.trim());
      toast('Project created', 'success');
      setShowAdd(false);
      setName('');
      setIdea('');
      setDescription('');
      setProjectId(created.id);
      await load();
      navigate('/'); // land on the dashboard for the new project
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Failed to create project', 'error');
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <LoadingState label="Loading projects…" />;
  if (error) return <ErrorState message={error} onRetry={load} />;

  return (
    <div>
      <PageHeader
        title="Projects"
        subtitle="Pick a project to work in, or create a new one to start generating documents."
        actions={
          <Button variant="primary" icon={<IconPlus size={16} />} onClick={() => setShowAdd(true)}>
            New project
          </Button>
        }
      />

      {projects.length === 0 ? (
        <EmptyState
          icon={<IconGraph size={22} />}
          title="No projects yet"
          description="Create your first project, then generate a full set of engineering documents from an idea."
          action={
            <Button variant="primary" icon={<IconPlus size={16} />} onClick={() => setShowAdd(true)}>
              Create a project
            </Button>
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {projects.map((p) => {
            const active = p.id === projectId;
            return (
              <button
                key={p.id}
                onClick={() => openProject(p)}
                className={
                  'group flex flex-col rounded-2xl border bg-surface p-5 text-left transition-all hover:-translate-y-0.5 hover:shadow-card ' +
                  (active ? 'border-brand ring-2 ring-brand/30' : 'border-line hover:border-brand/40')
                }
              >
                <div className="flex items-start justify-between gap-2">
                  <h3 className="font-semibold text-ink">{p.name}</h3>
                  {active ? (
                    <Badge tone="brand">
                      <IconCheck size={12} /> Active
                    </Badge>
                  ) : (
                    <IconChevronRight
                      size={16}
                      className="text-ink-muted transition-transform group-hover:translate-x-0.5"
                    />
                  )}
                </div>
                {p.idea && <p className="mt-1 line-clamp-2 text-sm text-ink-muted">{p.idea}</p>}
                <div className="mt-3 flex items-center gap-2 text-xs text-ink-muted">
                  <Badge tone="neutral">{p.status}</Badge>
                  <span>Open documents →</span>
                </div>
              </button>
            );
          })}
        </div>
      )}

      <Modal
        open={showAdd}
        onClose={() => setShowAdd(false)}
        title="New project"
        footer={
          <>
            <Button variant="ghost" onClick={() => setShowAdd(false)}>
              Cancel
            </Button>
            <Button variant="primary" loading={saving} onClick={handleCreate}>
              Create project
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <div>
            <label className="label">Project name</label>
            <input
              className="input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Meeting Notes AI"
            />
          </div>
          <div>
            <label className="label">Product idea</label>
            <textarea
              className="input"
              rows={3}
              value={idea}
              onChange={(e) => setIdea(e.target.value)}
              placeholder="One line describing what you're building…"
            />
          </div>
          <div>
            <label className="label">Description (optional)</label>
            <textarea
              className="input"
              rows={2}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Any extra context…"
            />
          </div>
        </div>
      </Modal>
    </div>
  );
}
