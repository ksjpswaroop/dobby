import type { ReactNode, ButtonHTMLAttributes } from 'react';
import { cn } from '../lib/cn';
import { IconAlert, IconRefresh } from '../lib/icons';

/* -------------------------------------------------------------------------- */
/* Card                                                                        */
/* -------------------------------------------------------------------------- */
export function Card({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return <div className={cn('card', className)}>{children}</div>;
}

export function CardBody({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return <div className={cn('p-5', className)}>{children}</div>;
}

/* -------------------------------------------------------------------------- */
/* Button                                                                      */
/* -------------------------------------------------------------------------- */
type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'success';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  loading?: boolean;
  icon?: ReactNode;
}

const variantClass: Record<Variant, string> = {
  primary: 'btn-primary',
  secondary: 'btn-secondary',
  ghost: 'btn-ghost',
  danger: 'btn-danger',
  success: 'btn-success',
};

export function Button({
  variant = 'secondary',
  loading,
  icon,
  className,
  children,
  disabled,
  ...props
}: ButtonProps) {
  return (
    <button
      className={cn(variantClass[variant], className)}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? <Spinner size={16} /> : icon}
      {children}
    </button>
  );
}

/* -------------------------------------------------------------------------- */
/* Badge                                                                       */
/* -------------------------------------------------------------------------- */
type Tone = 'neutral' | 'brand' | 'success' | 'warning' | 'danger' | 'accent';

const toneClass: Record<Tone, string> = {
  neutral: 'bg-surface2 text-ink-muted',
  brand: 'bg-brand/10 text-brand',
  success: 'bg-success/10 text-success',
  warning: 'bg-warning/15 text-warning',
  danger: 'bg-danger/10 text-danger',
  accent: 'bg-accent/10 text-accent',
};

export function Badge({
  tone = 'neutral',
  children,
  className,
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
}) {
  return <span className={cn('chip', toneClass[tone], className)}>{children}</span>;
}

/* -------------------------------------------------------------------------- */
/* Spinner                                                                     */
/* -------------------------------------------------------------------------- */
export function Spinner({ size = 20, className }: { size?: number; className?: string }) {
  return (
    <svg
      className={cn('animate-spin', className)}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" opacity="0.2" />
      <path
        d="M21 12a9 9 0 0 0-9-9"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-20 text-ink-muted">
      <Spinner size={28} className="text-brand" />
      <span className="text-sm">{label}</span>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Page header                                                                 */
/* -------------------------------------------------------------------------- */
export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-ink-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Empty / error states                                                        */
/* -------------------------------------------------------------------------- */
export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-line py-16 text-center">
      {icon && (
        <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-surface2 text-ink-muted">
          {icon}
        </div>
      )}
      <h3 className="text-base font-medium text-ink">{title}</h3>
      {description && <p className="mt-1 max-w-sm text-sm text-ink-muted">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-danger/30 bg-danger/5 py-14 text-center">
      <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-2xl bg-danger/10 text-danger">
        <IconAlert size={22} />
      </div>
      <p className="max-w-md text-sm text-ink">{message}</p>
      {onRetry && (
        <Button variant="secondary" className="mt-4" icon={<IconRefresh size={16} />} onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Score ring                                                                  */
/* -------------------------------------------------------------------------- */
export function ScoreRing({
  score,
  threshold = 85,
  size = 96,
}: {
  score: number;
  threshold?: number;
  size?: number;
}) {
  const r = size / 2 - 7;
  const c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(100, score));
  const passed = score >= threshold;
  const color = passed ? 'var(--success)' : score >= threshold * 0.7 ? 'var(--warning)' : 'var(--danger)';
  return (
    <div className="relative inline-flex" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgb(var(--line))" strokeWidth={7} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={`rgb(${color})`}
          strokeWidth={7}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c - (pct / 100) * c}
          style={{ transition: 'stroke-dashoffset 0.6s ease' }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-xl font-semibold text-ink">{Math.round(score)}</span>
        <span className="text-[10px] uppercase tracking-wide text-ink-muted">/ 100</span>
      </div>
    </div>
  );
}
