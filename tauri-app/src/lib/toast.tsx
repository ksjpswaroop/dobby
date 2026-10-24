import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from 'react';
import { cn } from './cn';
import { IconCheck, IconAlert, IconX } from './icons';

type ToastTone = 'success' | 'error' | 'info';
interface ToastItem {
  id: number;
  message: string;
  tone: ToastTone;
}

interface ToastContextValue {
  toast: (message: string, tone?: ToastTone) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);
let counter = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const remove = useCallback((id: number) => {
    setItems((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback(
    (message: string, tone: ToastTone = 'info') => {
      const id = ++counter;
      setItems((prev) => [...prev, { id, message, tone }]);
      window.setTimeout(() => remove(id), 4000);
    },
    [remove]
  );

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="pointer-events-none fixed bottom-5 right-5 z-[100] flex w-80 max-w-[calc(100vw-2.5rem)] flex-col gap-2">
        {items.map((t) => (
          <div
            key={t.id}
            className="pointer-events-auto flex animate-scale-in items-start gap-3 rounded-xl border border-line bg-surface p-3.5 shadow-pop"
          >
            <span
              className={cn(
                'mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full',
                t.tone === 'success' && 'bg-success/10 text-success',
                t.tone === 'error' && 'bg-danger/10 text-danger',
                t.tone === 'info' && 'bg-brand/10 text-brand'
              )}
            >
              {t.tone === 'error' ? <IconAlert size={15} /> : <IconCheck size={15} />}
            </span>
            <p className="flex-1 text-sm text-ink">{t.message}</p>
            <button
              onClick={() => remove(t.id)}
              className="text-ink-muted transition-colors hover:text-ink"
              aria-label="Dismiss"
            >
              <IconX size={15} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within ToastProvider');
  return ctx;
}
