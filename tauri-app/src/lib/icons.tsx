import type { SVGProps } from 'react';

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function Icon({ size = 18, children, ...props }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {children}
    </svg>
  );
}

export const IconDashboard = (p: IconProps) => (
  <Icon {...p}>
    <rect x="3" y="3" width="7" height="9" rx="1.5" />
    <rect x="14" y="3" width="7" height="5" rx="1.5" />
    <rect x="14" y="12" width="7" height="9" rx="1.5" />
    <rect x="3" y="16" width="7" height="5" rx="1.5" />
  </Icon>
);

export const IconBacklog = (p: IconProps) => (
  <Icon {...p}>
    <path d="M8 6h13M8 12h13M8 18h13" />
    <circle cx="3.5" cy="6" r="1.2" />
    <circle cx="3.5" cy="12" r="1.2" />
    <circle cx="3.5" cy="18" r="1.2" />
  </Icon>
);

export const IconWizard = (p: IconProps) => (
  <Icon {...p}>
    <path d="M15 4V2M15 10V8M12.5 6h-2M19.5 6h-2" />
    <path d="m3 21 9-9M14 6l4 4" />
    <path d="M18 14v4M20 16h-4" />
  </Icon>
);

export const IconBolt = (p: IconProps) => (
  <Icon {...p}>
    <path d="M13 2 4.5 13.5H11l-1 8.5 8.5-11.5H12l1-8.5Z" />
  </Icon>
);

export const IconGraph = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="6" cy="6" r="2.5" />
    <circle cx="18" cy="8" r="2.5" />
    <circle cx="12" cy="18" r="2.5" />
    <path d="M8 7.5 15.5 8M7.5 8 11 15.5M16.5 10 13 15.5" />
  </Icon>
);

export const IconSettings = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z" />
  </Icon>
);

export const IconSun = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
  </Icon>
);

export const IconMoon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />
  </Icon>
);

export const IconMonitor = (p: IconProps) => (
  <Icon {...p}>
    <rect x="2" y="4" width="20" height="13" rx="2" />
    <path d="M8 21h8M12 17v4" />
  </Icon>
);

export const IconPlus = (p: IconProps) => (
  <Icon {...p}>
    <path d="M12 5v14M5 12h14" />
  </Icon>
);

export const IconCheck = (p: IconProps) => (
  <Icon {...p}>
    <path d="M20 6 9 17l-5-5" />
  </Icon>
);

export const IconX = (p: IconProps) => (
  <Icon {...p}>
    <path d="M18 6 6 18M6 6l12 12" />
  </Icon>
);

export const IconRefresh = (p: IconProps) => (
  <Icon {...p}>
    <path d="M21 12a9 9 0 1 1-2.64-6.36M21 3v5h-5" />
  </Icon>
);

export const IconDownload = (p: IconProps) => (
  <Icon {...p}>
    <path d="M12 3v12M7 10l5 5 5-5M5 21h14" />
  </Icon>
);

export const IconTrash = (p: IconProps) => (
  <Icon {...p}>
    <path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6" />
  </Icon>
);

export const IconChevronRight = (p: IconProps) => (
  <Icon {...p}>
    <path d="m9 18 6-6-6-6" />
  </Icon>
);

export const IconArrowLeft = (p: IconProps) => (
  <Icon {...p}>
    <path d="M19 12H5M12 19l-7-7 7-7" />
  </Icon>
);

export const IconAlert = (p: IconProps) => (
  <Icon {...p}>
    <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" />
    <path d="M12 9v4M12 17h.01" />
  </Icon>
);

export const IconZoomIn = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="11" cy="11" r="7" />
    <path d="m21 21-4.3-4.3M11 8v6M8 11h6" />
  </Icon>
);

export const IconZoomOut = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="11" cy="11" r="7" />
    <path d="m21 21-4.3-4.3M8 11h6" />
  </Icon>
);

export const IconMaximize = (p: IconProps) => (
  <Icon {...p}>
    <path d="M8 3H5a2 2 0 0 0-2 2v3M21 8V5a2 2 0 0 0-2-2h-3M16 21h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3" />
  </Icon>
);

export const IconServer = (p: IconProps) => (
  <Icon {...p}>
    <rect x="3" y="4" width="18" height="7" rx="2" />
    <rect x="3" y="13" width="18" height="7" rx="2" />
    <path d="M7 7.5h.01M7 16.5h.01" />
  </Icon>
);

export const IconCpu = (p: IconProps) => (
  <Icon {...p}>
    <rect x="6" y="6" width="12" height="12" rx="2" />
    <path d="M9 2v2M15 2v2M9 20v2M15 20v2M2 9h2M2 15h2M20 9h2M20 15h2" />
    <rect x="9.5" y="9.5" width="5" height="5" rx="1" />
  </Icon>
);

export const IconSparkles = (p: IconProps) => (
  <Icon {...p}>
    <path d="M12 3l1.8 4.2L18 9l-4.2 1.8L12 15l-1.8-4.2L6 9l4.2-1.8L12 3Z" />
    <path d="M19 14l.9 2.1L22 17l-2.1.9L19 20l-.9-2.1L16 17l2.1-.9L19 14Z" />
  </Icon>
);

export const IconFolder = (p: IconProps) => (
  <Icon {...p}>
    <path d="M3 7a2 2 0 0 1 2-2h4l2 2.5h8a2 2 0 0 1 2 2V18a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" />
  </Icon>
);

export const IconLayers = (p: IconProps) => (
  <Icon {...p}>
    <path d="M12 2 2 7l10 5 10-5-10-5Z" />
    <path d="m2 12 10 5 10-5M2 17l10 5 10-5" />
  </Icon>
);

export const IconDoc = (p: IconProps) => (
  <Icon {...p}>
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
    <path d="M14 3v5h5M9 13h6M9 17h6" />
  </Icon>
);

export const IconTerminal = (p: IconProps) => (
  <Icon {...p}>
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <path d="m7 9 3 3-3 3M13 15h4" />
  </Icon>
);
export const IconSearch = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="11" cy="11" r="7" />
    <path d="m21 21-4.3-4.3" />
  </Icon>
);
export const IconCommand = (p: IconProps) => (
  <Icon {...p}>
    <path d="M15 6a3 3 0 1 1 3 3h-3V6ZM9 6a3 3 0 1 0-3 3h3V6ZM15 18a3 3 0 1 0 3-3h-3v3ZM9 18a3 3 0 1 1-3-3h3v3Z" />
    <rect x="9" y="9" width="6" height="6" rx="1" />
  </Icon>
);
export const IconSkill = (p: IconProps) => (
  <Icon {...p}>
    <path d="M12 2 9.5 7 4 8l4 4-1 6 5-3 5 3-1-6 4-4-5.5-1L12 2Z" />
  </Icon>
);
export const IconFlow = (p: IconProps) => (
  <Icon {...p}>
    <rect x="3" y="4" width="6" height="4" rx="1" />
    <rect x="15" y="8" width="6" height="4" rx="1" />
    <rect x="9" y="16" width="6" height="4" rx="1" />
    <path d="M6 8v3a2 2 0 0 0 2 2h4M18 12v1a2 2 0 0 1-2 2h-4" />
  </Icon>
);
export const IconLogs = (p: IconProps) => (
  <Icon {...p}>
    <path d="M4 6h10M4 12h16M4 18h7" />
    <circle cx="18" cy="6" r="1.4" />
    <circle cx="15" cy="18" r="1.4" />
  </Icon>
);
export const IconControl = (p: IconProps) => (
  <Icon {...p}>
    <path d="M4 6h10M18 6h2M4 12h2M10 12h10M4 18h8M16 18h4" />
    <circle cx="16" cy="6" r="2" />
    <circle cx="8" cy="12" r="2" />
    <circle cx="14" cy="18" r="2" />
  </Icon>
);
export const IconPrototype = (p: IconProps) => (
  <Icon {...p}>
    <rect x="4" y="3" width="16" height="18" rx="2" />
    <path d="M4 8h16M9 3v5" />
  </Icon>
);
export const IconVideo = (p: IconProps) => (
  <Icon {...p}>
    <rect x="3" y="6" width="13" height="12" rx="2" />
    <path d="m16 10 5-3v10l-5-3v-4Z" />
  </Icon>
);
export const IconAudio = (p: IconProps) => (
  <Icon {...p}>
    <rect x="9" y="2" width="6" height="12" rx="3" />
    <path d="M5 11a7 7 0 0 0 14 0M12 18v3M8 21h8" />
  </Icon>
);
export const IconYouTube = (p: IconProps) => (
  <Icon {...p}>
    <rect x="2.5" y="6" width="19" height="12" rx="3.5" />
    <path d="m10 9.5 5 2.5-5 2.5v-5Z" />
  </Icon>
);
export const IconNotes = (p: IconProps) => (
  <Icon {...p}>
    <path d="M5 3h14a1 1 0 0 1 1 1v13l-4 4H5a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z" />
    <path d="M8 8h8M8 12h6M16 21v-4h4" />
  </Icon>
);
export const IconMarket = (p: IconProps) => (
  <Icon {...p}>
    <path d="M4 8h16l-1 3H5L4 8ZM4 8l1-3h14l1 3M6 11v8h12v-8M9 11v8M15 11v8" />
  </Icon>
);
export const IconMindmap = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="5" cy="12" r="2.5" />
    <circle cx="18" cy="6" r="2.5" />
    <circle cx="18" cy="18" r="2.5" />
    <path d="M7.3 11 15.7 7M7.3 13l8.4 4" />
  </Icon>
);
/** A magnifier over a document — investigation, not the app-wide Search. */
export const IconResearch = (p: IconProps) => (
  <Icon {...p}>
    <path d="M14.5 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-8.5" />
    <circle cx="16.5" cy="6.5" r="3.5" />
    <path d="M19.2 9.2 22 12M8 14h5M8 17.5h7" />
  </Icon>
);
export const IconBulb = (p: IconProps) => (
  <Icon {...p}>
    <path d="M9 18h6M10 21h4" />
    <path d="M12 3a6 6 0 0 0-3.5 10.9c.6.44 1 1.16 1 1.94V16h5v-.16c0-.78.4-1.5 1-1.94A6 6 0 0 0 12 3Z" />
  </Icon>
);
export const IconPin = (p: IconProps) => (
  <Icon {...p}>
    <path d="M12 17v5" />
    <path d="M9 3h6l-.7 5.2a2 2 0 0 0 .6 1.7l1.9 1.8a1 1 0 0 1-.7 1.7H7.9a1 1 0 0 1-.7-1.7l1.9-1.8a2 2 0 0 0 .6-1.7L9 3Z" />
  </Icon>
);
/** Scales — a fork with two weighted sides, i.e. a decision. */
export const IconScale = (p: IconProps) => (
  <Icon {...p}>
    <path d="M12 4v16M7 20h10M4 8h16M4 8l-2.5 5a3 3 0 0 0 5 0L4 8ZM20 8l-2.5 5a3 3 0 0 0 5 0L20 8Z" />
  </Icon>
);
/** A clock with a trailing sweep — recent activity, not a literal deadline. */
export const IconActivity = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7v5l3.5 2" />
  </Icon>
);
