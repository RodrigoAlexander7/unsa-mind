import { dev } from '$app/environment';
import { env } from '$env/dynamic/public';
import { readSse } from './sse';

export type Role = 'user' | 'assistant';
export interface HistoryItem {
	role: Role;
	content: string;
}
export interface Citation {
	title: string;
	section?: string | null;
	url?: string | null;
	updated_at?: string | null;
}
export interface FinalEvent {
	answer: string;
	citations: Citation[];
	abstained: boolean;
	intent: string;
	data_as_of: string | null;
}
export interface Health {
	status: string;
	llm: string;
	vector_chunks: number;
	next_update: string | null;
}
export interface Schedule {
	enabled: boolean;
	interval_minutes: number;
	cron: string | null;
	next_run: string | null;
}
export interface Source {
	id: string;
	name: string;
	url: string;
	kind: string;
	authority: number;
	metadata: Record<string, unknown>;
	follow_links: boolean;
	link_pattern: string | null;
	max_pages: number;
	interval_minutes: number | null;
	enabled: boolean;
	last_run_at: string | null;
}
export type SourceInput = Omit<Source, 'id' | 'last_run_at'> & { id?: string };
export type Report = Record<string, unknown>;
export type Stats = Record<string, unknown>;

/** En dev se usa el proxy de Vite (mismo origen); en prod PUBLIC_API_URL. */
export function apiBase(): string {
	if (dev) return '';
	return (env.PUBLIC_API_URL ?? 'http://localhost:8000').replace(/\/+$/, '');
}

export class ApiError extends Error {
	status: number;
	constructor(message: string, status = 0) {
		super(message);
		this.status = status;
	}
}

async function request<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
	const headers = new Headers(init.headers);
	if (init.body) headers.set('Content-Type', 'application/json');
	if (token) headers.set('Authorization', `Bearer ${token}`);
	let res: Response;
	try {
		res = await fetch(apiBase() + path, { ...init, headers });
	} catch {
		throw new ApiError('No se pudo conectar con el servidor.');
	}
	if (!res.ok) {
		let detail = res.statusText;
		try {
			const j = await res.json();
			detail = typeof j.detail === 'string' ? j.detail : (j.message ?? detail);
		} catch {
			/* sin cuerpo JSON */
		}
		throw new ApiError(detail || `Error ${res.status}`, res.status);
	}
	if (res.status === 204) return undefined as T;
	const text = await res.text();
	return (text ? JSON.parse(text) : undefined) as T;
}

const json = (b: unknown) => JSON.stringify(b);

export interface StreamHandlers {
	onToken: (text: string) => void;
	onFinal: (f: FinalEvent) => void;
}

/** Envía la pregunta y procesa el stream SSE. Lanza ApiError ante `error` o fallo de red. */
export async function streamChat(
	body: { message: string; history?: HistoryItem[]; filters?: Record<string, unknown> },
	h: StreamHandlers,
	signal?: AbortSignal
): Promise<void> {
	let res: Response;
	try {
		res = await fetch(apiBase() + '/api/chat', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
			body: json(body),
			signal
		});
	} catch (e) {
		if (signal?.aborted) throw e;
		throw new ApiError('No se pudo conectar con el servidor.');
	}
	if (!res.ok || !res.body) throw new ApiError(`El servidor respondió con error ${res.status}.`, res.status);
	let finished = false;
	for await (const m of readSse(res.body)) {
		let data: Record<string, unknown>;
		try {
			data = JSON.parse(m.data);
		} catch {
			continue;
		}
		if (m.event === 'token') h.onToken(String(data.text ?? ''));
		else if (m.event === 'final') {
			finished = true;
			h.onFinal(data as unknown as FinalEvent);
		} else if (m.event === 'error') throw new ApiError(String(data.message ?? 'Error del servidor.'));
	}
	if (!finished) throw new ApiError('La respuesta se interrumpió.');
}

export const sendFeedback = (b: { message_id?: string; value: 'up' | 'down'; comment?: string }) =>
	request<unknown>('/api/feedback', { method: 'POST', body: json(b) });
export const getHealth = () => request<Health>('/api/health');

export const admin = (token: string) => ({
	getSchedule: () => request<Schedule>('/api/admin/schedule', {}, token),
	putSchedule: (s: Omit<Schedule, 'next_run'>) =>
		request<Schedule>('/api/admin/schedule', { method: 'PUT', body: json(s) }, token),
	listSources: () => request<Source[]>('/api/admin/sources', {}, token),
	createSource: (s: SourceInput) =>
		request<Source>('/api/admin/sources', { method: 'POST', body: json(s) }, token),
	updateSource: (id: string, s: SourceInput) =>
		request<Source>(`/api/admin/sources/${encodeURIComponent(id)}`, { method: 'PUT', body: json(s) }, token),
	deleteSource: (id: string) =>
		request<void>(`/api/admin/sources/${encodeURIComponent(id)}`, { method: 'DELETE' }, token),
	update: (b: { force?: boolean; only?: string[] } = {}) =>
		request<unknown>('/api/admin/update', { method: 'POST', body: json(b) }, token),
	reports: (limit = 20) => request<Report[]>(`/api/admin/reports?limit=${limit}`, {}, token),
	stats: () => request<Stats>('/api/admin/stats', {}, token)
});
