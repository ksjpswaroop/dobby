import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import FeatureList from '../components/FeatureList';
import { Modal } from '../components/Modal';
import { Button, PageHeader } from '../components/ui';
import { IconPlus } from '../lib/icons';
import { useToast } from '../lib/toast';
import { useProject } from '../lib/project';
import { FeatureBacklogItem } from '../api/client';
import api from '../api/client';

const CATEGORIES = [
  { value: 'core', label: 'Core' },
  { value: 'nice_to_have', label: 'Nice to have' },
  { value: 'stretch', label: 'Stretch' },
];

function Slider({
  label,
  value,
  onChange,
  hint,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  hint: string;
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-sm font-medium">{label}</span>
        <span className="text-sm font-semibold text-brand">{value}</span>
      </div>
      <input
        type="range"
        min={1}
        max={10}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-surface2 accent-brand"
      />
      <p className="mt-1 text-xs text-ink-muted">{hint}</p>
    </div>
  );
}

export default function BacklogPage() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const { projectId } = useProject();
  const [showAdd, setShowAdd] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [category, setCategory] = useState('core');
  const [impact, setImpact] = useState(7);
  const [effort, setEffort] = useState(4);
  const [risk, setRisk] = useState(3);
  const [saving, setSaving] = useState(false);

  const paretoPreview = (impact * 0.6 - effort * 0.3 - risk * 0.1).toFixed(2);

  const reset = () => {
    setTitle('');
    setDescription('');
    setCategory('core');
    setImpact(7);
    setEffort(4);
    setRisk(3);
  };

  const handleFeatureSelect = (feature: FeatureBacklogItem) => {
    navigate(`/wizard?feature=${encodeURIComponent(feature.title)}`);
  };

  const handleAdd = async () => {
    if (!title.trim() || !description.trim()) {
      toast('Please enter a title and description', 'error');
      return;
    }
    try {
      setSaving(true);
      await api.createFeature({
        title: title.trim(),
        description: description.trim(),
        category,
        impactScore: impact,
        effortScore: effort,
        riskScore: risk,
      }, projectId);
      toast('Feature added to backlog', 'success');
      setShowAdd(false);
      reset();
      setReloadKey((k) => k + 1);
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Failed to add feature', 'error');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Backlog"
        subtitle="Ranked by Pareto score — (impact × 0.6) − (effort × 0.3) − (risk × 0.1)."
        actions={
          <Button variant="primary" icon={<IconPlus size={16} />} onClick={() => setShowAdd(true)}>
            Add feature
          </Button>
        }
      />

      <FeatureList projectId={projectId} reloadKey={reloadKey} onFeatureSelect={handleFeatureSelect} />

      <Modal
        open={showAdd}
        onClose={() => setShowAdd(false)}
        title="Add feature"
        footer={
          <>
            <Button variant="ghost" onClick={() => setShowAdd(false)}>
              Cancel
            </Button>
            <Button variant="primary" loading={saving} onClick={handleAdd}>
              Add feature
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <div>
            <label className="label">Title</label>
            <input
              className="input"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g., Smart action-item detection"
            />
          </div>
          <div>
            <label className="label">Description</label>
            <textarea
              className="input"
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Describe the feature…"
            />
          </div>
          <div>
            <label className="label">Category</label>
            <select className="input" value={category} onChange={(e) => setCategory(e.target.value)}>
              {CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Slider label="Impact" value={impact} onChange={setImpact} hint="User/business value" />
            <Slider label="Effort" value={effort} onChange={setEffort} hint="Build cost" />
            <Slider label="Risk" value={risk} onChange={setRisk} hint="Uncertainty" />
          </div>

          <div className="flex items-center justify-between rounded-xl bg-surface2 px-4 py-3">
            <span className="text-sm text-ink-muted">Pareto score</span>
            <span className="text-lg font-semibold text-brand">{paretoPreview}</span>
          </div>
        </div>
      </Modal>
    </div>
  );
}
