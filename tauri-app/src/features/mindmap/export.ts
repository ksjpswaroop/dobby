import { mindmapApi } from './api';

/** Trigger a browser download for generated content. */
export function download(filename: string, content: BlobPart, mime: string) {
  const url = URL.createObjectURL(new Blob([content], { type: mime }));
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function safeName(title: string): string {
  return (title || 'mindmap').replace(/[^\w.-]+/g, '_').slice(0, 60);
}

/**
 * Export the *rendered* canvas.
 *
 * PNG/SVG are produced in the browser rather than server-side, because the
 * visual only exists here — the backend stores structure, not pixels. Styles
 * are inlined so the exported file stands alone (per the mindmap-skill
 * export reference: fonts and computed colours must be embedded, or the file
 * renders unstyled elsewhere).
 */
function canvasSvg(): SVGSVGElement | null {
  const viewport = document.querySelector('.react-flow__viewport');
  const original = document.querySelector('.react-flow__renderer svg, .react-flow svg');
  if (!viewport || !original) return null;

  const bounds = (viewport as HTMLElement).getBoundingClientRect();
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  svg.setAttribute('width', String(Math.ceil(bounds.width)));
  svg.setAttribute('height', String(Math.ceil(bounds.height)));

  // React Flow draws nodes as HTML, so wrap them in foreignObject to keep them.
  const fo = document.createElementNS('http://www.w3.org/2000/svg', 'foreignObject');
  fo.setAttribute('width', '100%');
  fo.setAttribute('height', '100%');
  const clone = viewport.cloneNode(true) as HTMLElement;
  clone.style.transform = 'none';
  const wrapper = document.createElement('div');
  wrapper.setAttribute('xmlns', 'http://www.w3.org/1999/xhtml');
  wrapper.style.fontFamily =
    'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif';
  wrapper.style.background = getComputedStyle(document.body).backgroundColor;
  wrapper.appendChild(clone);
  fo.appendChild(wrapper);
  svg.appendChild(fo);
  return svg;
}

export async function exportSvg(title: string) {
  const svg = canvasSvg();
  if (!svg) throw new Error('Canvas not ready');
  const text = new XMLSerializer().serializeToString(svg);
  download(`${safeName(title)}.svg`, text, 'image/svg+xml');
}

export async function exportPng(title: string) {
  const svg = canvasSvg();
  if (!svg) throw new Error('Canvas not ready');
  const text = new XMLSerializer().serializeToString(svg);
  const blob = new Blob([text], { type: 'image/svg+xml;charset=utf-8' });
  const url = URL.createObjectURL(blob);

  await new Promise<void>((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const scale = 2; // retina-quality output
      const canvas = document.createElement('canvas');
      canvas.width = img.width * scale;
      canvas.height = img.height * scale;
      const ctx = canvas.getContext('2d');
      if (!ctx) return reject(new Error('Canvas unsupported'));
      ctx.fillStyle = getComputedStyle(document.body).backgroundColor;
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.scale(scale, scale);
      ctx.drawImage(img, 0, 0);
      canvas.toBlob((b) => {
        if (b) download(`${safeName(title)}.png`, b, 'image/png');
        URL.revokeObjectURL(url);
        resolve();
      }, 'image/png');
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('Could not rasterize the canvas'));
    };
    img.src = url;
  });
}

const EXT: Record<string, string> = { markdown: 'md', outline: 'md', mermaid: 'mmd' };

export async function exportStructured(
  mapId: string,
  title: string,
  format: 'json' | 'markdown' | 'mermaid' | 'outline'
) {
  if (format === 'json') {
    const data = await mindmapApi.exportJson(mapId);
    download(`${safeName(title)}.json`, JSON.stringify(data, null, 2), 'application/json');
    return;
  }
  const text = await mindmapApi.exportText(mapId, format);
  download(`${safeName(title)}.${EXT[format] ?? 'txt'}`, text, 'text/plain');
}
