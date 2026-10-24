import { PageHeader } from '../components/ui';
import { MindMapWorkspace } from '../features/mindmap';
import { useProject } from '../lib/project';

export default function MindMapPage() {
  const { projectId } = useProject();
  return (
    <div>
      <PageHeader
        title="Mind Map"
        subtitle="Organize this project's ideas visually — drag to re-parent, collapse branches, edit inline."
      />
      <MindMapWorkspace projectId={projectId} />
    </div>
  );
}
