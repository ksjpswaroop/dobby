import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';

const STORAGE_KEY = 'dobby-active-project';
const DEFAULT_PROJECT_ID = 'default-project';

interface ProjectContextValue {
  projectId: string;
  setProjectId: (id: string) => void;
}

const ProjectContext = createContext<ProjectContextValue | null>(null);

export function ProjectProvider({ children }: { children: ReactNode }) {
  const [projectId, setProjectIdState] = useState<string>(
    () => localStorage.getItem(STORAGE_KEY) || DEFAULT_PROJECT_ID
  );

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, projectId);
  }, [projectId]);

  return (
    <ProjectContext.Provider value={{ projectId, setProjectId: setProjectIdState }}>
      {children}
    </ProjectContext.Provider>
  );
}

export function useProject(): ProjectContextValue {
  const ctx = useContext(ProjectContext);
  if (!ctx) throw new Error('useProject must be used within ProjectProvider');
  return ctx;
}
