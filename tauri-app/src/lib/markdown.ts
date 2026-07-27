/**
 * A small Markdown renderer for the document preview.
 *
 * Hand-written rather than pulling in a library because the requirement here
 * is narrow (the subset our generators actually emit) and the security
 * property matters more than the feature set: **every character is HTML-
 * escaped before any formatting is applied**, so document content — which can
 * come from a local model, an imported file, or a fetched page — can never
 * inject markup. A library configured wrong fails open; this fails closed.
 *
 * Wiki links [[Title]] become anchors with a data attribute the editor binds
 * to for in-app navigation, never an href that could leave the app.
 */

export function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** Inline formatting, applied only to already-escaped text. */
function inline(escaped: string): string {
  return escaped
    // `code` first, so formatting inside it is not re-processed.
    .replace(/`([^`]+)`/g, '<code class="rounded bg-surface2 px-1 py-px text-[0.9em]">$1</code>')
    .replace(/\[\[([^\[\]]+)\]\]/g,
      '<a href="#" data-wikilink="$1" class="text-brand underline decoration-dotted">$1</a>')
    // [text](url) — only http(s) and mailto survive; anything else renders as
    // plain text rather than becoming a javascript: link.
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_m, text: string, url: string) => {
      const safe = /^(https?:|mailto:)/i.test(url);
      return safe
        ? `<a href="${url}" target="_blank" rel="noopener noreferrer" class="text-brand underline">${text}</a>`
        : `${text} (${url})`;
    })
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/~~([^~]+)~~/g, '<del>$1</del>');
}

export interface RenderedMarkdown {
  html: string;
  /** Mermaid sources, extracted so the caller can render them properly. */
  mermaid: string[];
}

export function renderMarkdown(source: string): RenderedMarkdown {
  const lines = (source || '').split('\n');
  const out: string[] = [];
  const mermaid: string[] = [];

  let inFence = false;
  let fenceLang = '';
  let fenceBuf: string[] = [];
  let listType: 'ul' | 'ol' | null = null;

  const closeList = () => {
    if (listType) {
      out.push(`</${listType}>`);
      listType = null;
    }
  };

  for (const raw of lines) {
    const fence = raw.match(/^\s*(?:```|~~~)\s*(\w+)?\s*$/);
    if (fence) {
      if (inFence) {
        const body = fenceBuf.join('\n');
        if (fenceLang === 'mermaid') {
          mermaid.push(body);
          out.push(
            `<div class="dobby-mermaid my-3 overflow-x-auto rounded-xl border border-line bg-surface2 p-3" data-mermaid-index="${mermaid.length - 1}"></div>`
          );
        } else {
          out.push(
            `<pre class="my-3 overflow-x-auto rounded-xl border border-line bg-surface2 p-3 text-[12px]"><code>${escapeHtml(body)}</code></pre>`
          );
        }
        inFence = false;
        fenceBuf = [];
        fenceLang = '';
      } else {
        closeList();
        inFence = true;
        fenceLang = (fence[1] || '').toLowerCase();
      }
      continue;
    }

    if (inFence) {
      fenceBuf.push(raw);
      continue;
    }

    const heading = raw.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      closeList();
      const level = heading[1].length;
      const size = ['text-xl', 'text-lg', 'text-base', 'text-sm', 'text-sm', 'text-sm'][level - 1];
      out.push(
        `<h${level} class="mt-4 mb-1.5 ${size} font-semibold text-ink">${inline(escapeHtml(heading[2]))}</h${level}>`
      );
      continue;
    }

    if (/^\s*(?:---|\*\*\*|___)\s*$/.test(raw)) {
      closeList();
      out.push('<hr class="my-4 border-line" />');
      continue;
    }

    const quote = raw.match(/^\s*>\s?(.*)$/);
    if (quote) {
      closeList();
      out.push(
        `<blockquote class="my-2 border-l-2 border-brand/40 pl-3 text-ink-muted">${inline(escapeHtml(quote[1]))}</blockquote>`
      );
      continue;
    }

    const ul = raw.match(/^\s*[-*+]\s+(.*)$/);
    const ol = raw.match(/^\s*\d+\.\s+(.*)$/);
    if (ul || ol) {
      const want = ul ? 'ul' : 'ol';
      if (listType !== want) {
        closeList();
        listType = want;
        out.push(
          `<${want} class="my-2 ml-5 space-y-0.5 ${want === 'ul' ? 'list-disc' : 'list-decimal'}">`
        );
      }
      out.push(`<li>${inline(escapeHtml((ul ? ul[1] : ol![1])))}</li>`);
      continue;
    }

    if (!raw.trim()) {
      closeList();
      continue;
    }

    closeList();
    out.push(`<p class="my-2 leading-relaxed">${inline(escapeHtml(raw))}</p>`);
  }

  // An unterminated fence still has to render, or the tail of the document
  // silently disappears from the preview.
  if (inFence && fenceBuf.length) {
    out.push(
      `<pre class="my-3 overflow-x-auto rounded-xl border border-line bg-surface2 p-3 text-[12px]"><code>${escapeHtml(fenceBuf.join('\n'))}</code></pre>`
    );
  }
  closeList();

  return { html: out.join('\n'), mermaid };
}
