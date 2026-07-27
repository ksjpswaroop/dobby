import {
  IconDashboard, IconFolder, IconDoc, IconBacklog, IconGraph, IconMindmap,
  IconWizard, IconBolt, IconLayers, IconPrototype, IconVideo,
  IconAudio, IconYouTube, IconNotes,
  IconCommand, IconSkill, IconFlow,
  IconTerminal, IconLogs, IconControl, IconSearch, IconSettings,
  IconMarket, IconSparkles, IconResearch, IconServer, IconBulb,
} from './icons';

export type NavStatus = 'live' | 'planned';

/** A sub-surface, shown as an in-page tab under its primary destination. */
export interface SubItem {
  label: string;
  route: string;
  icon: (p: { size?: number }) => JSX.Element;
  status: NavStatus;
  phase?: string;
  blurb?: string;
}

/** A primary sidebar destination — a verb. Kept deliberately few. */
export interface NavSection {
  label: string;          // the verb
  route: string;          // its default landing route
  icon: (p: { size?: number }) => JSX.Element;
  hint: string;           // one-line description
  items: SubItem[];       // in-page tabs
}

/**
 * A handful of verbs, not fifteen links. Each primary destination owns a small
 * set of in-page tabs (OpenWorker's "app-in-app" pattern), so the sidebar stays
 * calm.
 *
 * Order is the workflow: understand the space (Ideate), find out what is true
 * about it (Research), then build (Create). Research sits before Create because
 * its output — findings promoted into the backlog — is Create's input.
 */
export const NAV_SECTIONS: NavSection[] = [
  {
    label: 'Ideate',
    route: '/',
    icon: IconSparkles,
    hint: 'Capture ideas, prioritize, and see the big picture',
    items: [
      { label: 'Overview', route: '/', icon: IconDashboard, status: 'live' },
      { label: 'Ideas', route: '/ideas', icon: IconBulb, status: 'live' },
      { label: 'Projects', route: '/projects', icon: IconFolder, status: 'live' },
      { label: 'Backlog', route: '/backlog', icon: IconBacklog, status: 'live' },
      { label: 'Graph', route: '/graph', icon: IconGraph, status: 'live' },
      { label: 'Mind Map', route: '/mindmap', icon: IconMindmap, status: 'live' },
    ],
  },
  {
    label: 'Research',
    route: '/research',
    icon: IconResearch,
    hint: 'Find out what is true before you build it',
    items: [
      { label: 'Briefs', route: '/research', icon: IconResearch, status: 'live' },
    ],
  },
  {
    label: 'Create',
    route: '/create',
    icon: IconWizard,
    hint: 'Generate documents, prototypes, and media',
    items: [
      { label: 'Wizard', route: '/wizard', icon: IconWizard, status: 'live' },
      { label: 'YOLO', route: '/yolo', icon: IconBolt, status: 'live' },
      { label: 'Bulk', route: '/bulk', icon: IconLayers, status: 'live' },
      { label: 'Documents', route: '/documents', icon: IconDoc, status: 'live' },
      { label: 'Prototypes', route: '/prototypes', icon: IconPrototype, status: 'planned', phase: 'P4',
        blurb: 'Generate runnable app prototypes from a spec, preview and test them in-app.' },
      { label: 'Video', route: '/video', icon: IconVideo, status: 'planned', phase: 'P4',
        blurb: 'Generate short videos and animated explainers from your documents.' },
      { label: 'Transcribe', route: '/transcribe', icon: IconAudio, status: 'live' },
      { label: 'YouTube', route: '/youtube', icon: IconYouTube, status: 'planned', phase: 'P2',
        blurb: 'Extract a transcript + audio from YouTube, then build structured notes.' },
      { label: 'Notes', route: '/notes', icon: IconNotes, status: 'planned', phase: 'P2',
        blurb: 'An AI notes builder that turns any source into clean, structured notes.' },
    ],
  },
  {
    label: 'Automate',
    route: '/automate',
    icon: IconFlow,
    hint: 'Build skills and flows that do the work for you',
    // Live tabs lead. A section whose first tab is a "coming soon" card reads
    // as an empty section, however much works further along the strip.
    items: [
      { label: 'Inbox', route: '/inbox', icon: IconControl, status: 'live' },
      { label: 'Connections', route: '/connections', icon: IconServer, status: 'live' },
      { label: 'Automations', route: '/automations', icon: IconFlow, status: 'live' },
      { label: 'Commands', route: '/command', icon: IconCommand, status: 'live' },
      { label: 'Skills', route: '/skills', icon: IconSkill, status: 'planned', phase: 'P3',
        blurb: 'Author reusable AI skills (prompt + tools + schema) you can run and publish.' },
      { label: 'Flows', route: '/flows', icon: IconFlow, status: 'planned', phase: 'P3',
        blurb: 'Compose multi-step automations visually — chain skills, tools, and conditions.' },
      { label: 'Marketplace', route: '/marketplace', icon: IconMarket, status: 'planned', phase: 'P5',
        blurb: 'Install skills, flows, and apps locally — and publish your own.' },
    ],
  },
  {
    label: 'Develop',
    route: '/develop',
    icon: IconTerminal,
    hint: 'Terminal, traces, and search across everything',
    items: [
      { label: 'Logs & Traces', route: '/logs', icon: IconLogs, status: 'live' },
      { label: 'Search', route: '/search', icon: IconSearch, status: 'live' },
    ],
  },
  {
    label: 'Settings',
    route: '/settings',
    icon: IconSettings,
    hint: 'Models, connections, and how Dobby behaves',
    items: [
      { label: 'General', route: '/settings', icon: IconSettings, status: 'live' },
      { label: 'Control', route: '/control', icon: IconControl, status: 'planned', phase: 'P3',
        blurb: 'Govern agents, permissions, models, and resource limits in one place.' },
    ],
  },
];

/** Flattened list of every sub-surface (used by the ⌘K palette and route lookup). */
export const ALL_ITEMS: SubItem[] = NAV_SECTIONS.flatMap((s) => s.items);

export function findNavItem(route: string): SubItem | undefined {
  return ALL_ITEMS.find((i) => i.route === route);
}

/** The section that owns a route (for highlighting + rendering its tabs). */
export function sectionForRoute(route: string): NavSection | undefined {
  return (
    NAV_SECTIONS.find((s) => s.items.some((i) => i.route === route)) ??
    NAV_SECTIONS.find((s) => s.route === route)
  );
}

export function categoryOf(route: string): string {
  return sectionForRoute(route)?.label ?? '';
}
