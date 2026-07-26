import { Component, type ErrorInfo, type ReactNode } from 'react';
import { Button } from '../../../components/ui';
import { IconAlert, IconRefresh } from '../../../lib/icons';

interface Props {
  children: ReactNode;
  onReset?: () => void;
}

interface State {
  error: Error | null;
}

/**
 * Keeps a canvas crash contained.
 *
 * React Flow renders arbitrary user data; a single bad node shouldn't take the
 * whole page down with it. Recovery re-fetches the tree rather than reloading
 * the app, so nothing else in the workspace is lost.
 */
export class MindMapErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Mind map crashed:', error, info.componentStack);
  }

  private reset = () => {
    this.setState({ error: null });
    this.props.onReset?.();
  };

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <div className="card m-4 p-8 text-center" role="alert">
        <div className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-2xl bg-danger/10 text-danger">
          <IconAlert size={22} />
        </div>
        <h3 className="text-base font-medium text-ink">Something went wrong with the mind map</h3>
        <p className="mx-auto mt-1 max-w-md text-sm text-ink-muted">
          Your map is safe — it's stored locally. Reloading fetches it again.
        </p>
        <p className="mx-auto mt-2 max-w-md font-mono text-[11px] text-ink-muted">
          {this.state.error.message}
        </p>
        <Button variant="secondary" className="mt-5" icon={<IconRefresh size={16} />}
                onClick={this.reset}>
          Reload the map
        </Button>
      </div>
    );
  }
}
