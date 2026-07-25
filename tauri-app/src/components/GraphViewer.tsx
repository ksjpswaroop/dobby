import { useEffect, useRef, useState, useCallback } from 'react';
import mermaid from 'mermaid';
import { useTheme } from '../lib/theme';
import { IconZoomIn, IconZoomOut, IconMaximize } from '../lib/icons';
import { Spinner } from './ui';

interface GraphViewerProps {
  mermaidSyntax: string;
}

export default function GraphViewer({ mermaidSyntax }: GraphViewerProps) {
  const { resolved } = useTheme();
  const containerRef = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);

  const render = useCallback(async () => {
    if (!containerRef.current) return;
    try {
      setLoading(true);
      setError(null);
      mermaid.initialize({
        startOnLoad: false,
        theme: resolved === 'dark' ? 'dark' : 'base',
        themeVariables: {
          fontFamily: 'Inter, system-ui, sans-serif',
          primaryColor: '#6366f1',
          primaryTextColor: '#ffffff',
          primaryBorderColor: '#4f46e5',
          lineColor: resolved === 'dark' ? '#71717a' : '#9ca3af',
          background: 'transparent',
        },
        flowchart: { useMaxWidth: false, htmlLabels: true, curve: 'basis', padding: 16 },
      });
      const { svg } = await mermaid.render(`graph-${Date.now()}`, mermaidSyntax || 'graph TD; A[No nodes yet]');
      containerRef.current.innerHTML = svg;
      const el = containerRef.current.querySelector('svg');
      if (el) {
        el.style.maxWidth = 'none';
        el.style.height = 'auto';
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to render graph');
    } finally {
      setLoading(false);
    }
  }, [mermaidSyntax, resolved]);

  useEffect(() => {
    render();
    setScale(1);
    setOffset({ x: 0, y: 0 });
  }, [render]);

  // Apply transform whenever scale/offset change (reads fresh values — no stale bug)
  useEffect(() => {
    const el = containerRef.current?.querySelector('svg');
    if (el) {
      el.style.transform = `translate(${offset.x}px, ${offset.y}px) scale(${scale})`;
      el.style.transformOrigin = 'center center';
      el.style.transition = drag.current ? 'none' : 'transform 0.12s ease-out';
    }
  }, [scale, offset]);

  const zoomIn = () => setScale((s) => Math.min(s + 0.2, 3));
  const zoomOut = () => setScale((s) => Math.max(s - 0.2, 0.4));
  const reset = () => {
    setScale(1);
    setOffset({ x: 0, y: 0 });
  };

  const onMouseDown = (e: React.MouseEvent) => {
    drag.current = { x: e.clientX, y: e.clientY, ox: offset.x, oy: offset.y };
  };
  const onMouseMove = (e: React.MouseEvent) => {
    if (!drag.current) return;
    setOffset({
      x: drag.current.ox + (e.clientX - drag.current.x),
      y: drag.current.oy + (e.clientY - drag.current.y),
    });
  };
  const endDrag = () => {
    drag.current = null;
  };

  return (
    <div className="relative overflow-hidden rounded-2xl border border-line bg-surface">
      <div className="absolute right-3 top-3 z-10 flex flex-col gap-1 rounded-xl border border-line bg-surface/90 p-1 shadow-soft backdrop-blur">
        <button className="rounded-lg p-1.5 text-ink-muted hover:bg-surface2 hover:text-ink" onClick={zoomIn} title="Zoom in">
          <IconZoomIn size={16} />
        </button>
        <button className="rounded-lg p-1.5 text-ink-muted hover:bg-surface2 hover:text-ink" onClick={zoomOut} title="Zoom out">
          <IconZoomOut size={16} />
        </button>
        <button className="rounded-lg p-1.5 text-ink-muted hover:bg-surface2 hover:text-ink" onClick={reset} title="Reset view">
          <IconMaximize size={16} />
        </button>
      </div>

      <div
        ref={containerRef}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={endDrag}
        onMouseLeave={endDrag}
        className="flex h-[560px] w-full items-center justify-center overflow-hidden [&_svg]:cursor-grab active:[&_svg]:cursor-grabbing"
      />

      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-surface/60">
          <Spinner size={26} className="text-brand" />
        </div>
      )}
      {error && (
        <div className="absolute inset-0 flex items-center justify-center p-6 text-center">
          <p className="text-sm text-danger">{error}</p>
        </div>
      )}
    </div>
  );
}
