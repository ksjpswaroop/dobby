import { useLocation, useNavigate } from 'react-router-dom';
import { Card, Button, PageHeader, Badge } from '../components/ui';
import { findNavItem } from '../lib/nav';
import { IconSparkles, IconArrowLeft } from '../lib/icons';

const PHASE_LABEL: Record<string, string> = {
  P1: 'Phase 1 · Foundations (Mo 1–2)',
  P2: 'Phase 2 · Studio & Capture (Mo 3–4)',
  P3: 'Phase 3 · Automation (Mo 5–6)',
  P4: 'Phase 4 · Build & Generate (Mo 7–8)',
  P5: 'Phase 5 · Local Marketplace (Mo 9–10)',
  P6: 'Phase 6 · Publish & Cloud (Mo 11–12)',
};

export default function Planned() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const item = findNavItem(pathname);
  const Icon = item?.icon;

  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader title={item?.label ?? 'Coming soon'} subtitle="On the Dobby roadmap" />
      <Card className="p-8 text-center">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-brand/10 text-brand">
          {Icon ? <Icon size={26} /> : <IconSparkles size={26} />}
        </div>
        <div className="mb-3 flex items-center justify-center gap-2">
          <Badge tone="brand">Planned</Badge>
          {item?.phase && <Badge tone="accent">{PHASE_LABEL[item.phase] ?? item.phase}</Badge>}
        </div>
        <p className="mx-auto max-w-md text-sm text-ink-muted">
          {item?.blurb ??
            'This capability is part of Dobby’s expansion into a local-first AI workbench.'}
        </p>
        <p className="mx-auto mt-4 max-w-md text-xs text-ink-muted">
          It’s specced and scheduled in the expansion plan — see the roadmap, feature specs, and
          architecture documents for the full design.
        </p>
        <div className="mt-6 flex justify-center gap-2">
          <Button variant="secondary" icon={<IconArrowLeft size={16} />} onClick={() => navigate('/')}>
            Back to Dashboard
          </Button>
        </div>
      </Card>
    </div>
  );
}
