import { marked } from 'marked';
import DOMPurify from 'dompurify';

const escapeHtml = (s: string) =>
	s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

let hooked = false;

/** Markdown -> HTML sanitizado. En SSR (sin DOM) devuelve texto escapado. */
export function renderMarkdown(src: string): string {
	if (typeof window === 'undefined') return `<p>${escapeHtml(src)}</p>`;
	if (!hooked) {
		DOMPurify.addHook('afterSanitizeAttributes', (node) => {
			if (node.tagName === 'A') {
				node.setAttribute('target', '_blank');
				node.setAttribute('rel', 'noopener noreferrer');
			}
		});
		hooked = true;
	}
	const html = marked.parse(src, { async: false, gfm: true, breaks: true }) as string;
	return DOMPurify.sanitize(html, { USE_PROFILES: { html: true } });
}

export function formatDate(iso: string | null | undefined): string {
	if (!iso) return '';
	const d = new Date(iso);
	if (isNaN(d.getTime())) return iso;
	const p = (n: number) => String(n).padStart(2, '0');
	return `${p(d.getDate())}/${p(d.getMonth() + 1)}/${d.getFullYear()}`;
}

export function formatDateTime(iso: string | null | undefined): string {
	if (!iso) return '—';
	const d = new Date(iso);
	if (isNaN(d.getTime())) return iso;
	const p = (n: number) => String(n).padStart(2, '0');
	return `${formatDate(iso)} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
