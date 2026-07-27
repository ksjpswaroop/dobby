import type { NavigateFunction } from 'react-router-dom';
import api from '../api/client';
import { pinsApi } from '../features/pins/api';
import { ALL_ITEMS } from './nav';
import {
  IconBolt, IconPlus, IconLayers, IconWizard, IconCpu,
  IconRefresh, IconTrash, IconSun, IconMoon, IconMonitor, IconDoc, IconPin,
} from './icons';

export type CommandKind = 'action' | 'navigate' | 'model' | 'result';

export interface Command {
  id: string;
  label: string;
  hint?: string;          // right-aligned context (category, subtitle)
  group: string;          // section header in the palette
  icon: (p: { size?: number }) => JSX.Element;
  keywords?: string;      // extra search text
  kind: CommandKind;
  run: () => void | Promise<void>;
}

export interface CommandContext {
  navigate: NavigateFunction;
  toast: (msg: string, tone?: 'success' | 'error' | 'info') => void;
  setTheme: (t: 'light' | 'dark' | 'system') => void;
  projectId: string;
  close: () => void;
}

/** Actions the Command Center can *perform*, not just navigate to. */
export function buildCommands(ctx: CommandContext): Command[] {
  const { navigate, toast, setTheme, projectId, close } = ctx;
  const go = (route: string) => () => {
    navigate(route);
    close();
  };

  const actions: Command[] = [
    {
      id: 'act.generate.yolo',
      label: 'Generate documents (YOLO)',
      hint: 'One-shot, all 7 artifacts',
      group: 'Actions',
      icon: IconBolt,
      keywords: 'create generate run yolo documents',
      kind: 'action',
      run: go('/yolo'),
    },
    {
      id: 'act.generate.wizard',
      label: 'Start the guided Wizard',
      hint: 'Step-by-step, verified',
      group: 'Actions',
      icon: IconWizard,
      keywords: 'create generate wizard guided step',
      kind: 'action',
      run: go('/wizard'),
    },
    {
      id: 'act.generate.bulk',
      label: 'Bulk generate from many ideas',
      hint: 'Parallel',
      group: 'Actions',
      icon: IconLayers,
      keywords: 'create generate bulk many batch',
      kind: 'action',
      run: go('/bulk'),
    },
    {
      id: 'act.project.new',
      label: 'New project',
      group: 'Actions',
      icon: IconPlus,
      keywords: 'create add project workspace',
      kind: 'action',
      run: go('/projects'),
    },
    {
      id: 'act.feature.new',
      label: 'Add a feature to the backlog',
      group: 'Actions',
      icon: IconPlus,
      keywords: 'create add feature backlog idea',
      kind: 'action',
      run: go('/backlog'),
    },
    {
      id: 'act.docs.open',
      label: 'Browse generated documents',
      group: 'Actions',
      icon: IconDoc,
      keywords: 'documents read open library',
      kind: 'action',
      run: go('/documents'),
    },
    {
      id: 'act.runs.clear',
      label: 'Clear run history',
      hint: 'Logs & Traces',
      group: 'Actions',
      icon: IconTrash,
      keywords: 'clear delete runs logs traces history',
      kind: 'action',
      run: async () => {
        try {
          const { deleted } = await api.clearRuns(projectId);
          toast(`Cleared ${deleted} run${deleted === 1 ? '' : 's'}`, 'success');
        } catch {
          toast('Failed to clear runs', 'error');
        }
        close();
      },
    },
    {
      id: 'act.reload',
      label: 'Reload the app',
      group: 'Actions',
      icon: IconRefresh,
      keywords: 'reload refresh restart',
      kind: 'action',
      run: () => window.location.reload(),
    },
  ];

  const themes: Command[] = (
    [
      ['light', 'Light', IconSun],
      ['dark', 'Dark', IconMoon],
      ['system', 'System', IconMonitor],
    ] as const
  ).map(([value, label, icon]) => ({
    id: `act.theme.${value}`,
    label: `Switch theme: ${label}`,
    group: 'Actions',
    icon,
    keywords: `theme appearance ${label} dark light mode`,
    kind: 'action' as const,
    run: () => {
      setTheme(value);
      toast(`Theme: ${label}`, 'success');
      close();
    },
  }));

  const navItems: Command[] = ALL_ITEMS.map((i) => ({
    id: `nav${i.route}`,
    label: i.label,
    hint: i.status === 'planned' ? 'soon' : undefined,
    group: 'Go to',
    icon: i.icon,
    keywords: i.blurb || '',
    kind: 'navigate' as const,
    run: go(i.route),
  }));

  return [...actions, ...themes, ...navItems];
}

/** Model-switch commands, loaded lazily (needs a backend round-trip). */
export async function buildModelCommands(ctx: CommandContext): Promise<Command[]> {
  try {
    const models = await api.listModels();
    return models.map((m) => ({
      id: `model.${m.name}`,
      label: `Use model: ${m.name}`,
      hint: m.active ? 'active' : m.parameter_size || '',
      group: 'Models',
      icon: IconCpu,
      keywords: `model switch ${m.name} ${m.family ?? ''}`,
      kind: 'model' as const,
      run: async () => {
        try {
          await api.updateSettings({ model: m.name });
          ctx.toast(`Active model: ${m.name}`, 'success');
        } catch {
          ctx.toast('Failed to switch model', 'error');
        }
        ctx.close();
      },
    }));
  } catch {
    return []; // Ollama offline — the palette still works without model commands
  }
}

/** Pinned items, surfaced at the top of the palette as their own group. */
export async function buildPinCommands(ctx: CommandContext): Promise<Command[]> {
  try {
    const { pins } = await pinsApi.list(ctx.projectId);
    return pins.map((p) => ({
      id: `pin.${p.id}`,
      label: p.title,
      hint: p.entity_type,
      group: 'Pinned',
      icon: IconPin,
      keywords: `pinned favorite ${p.entity_type} ${p.title}`,
      kind: 'navigate' as const,
      run: () => {
        ctx.navigate(p.route);
        ctx.close();
      },
    }));
  } catch {
    return [];
  }
}
