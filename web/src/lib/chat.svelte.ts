import { ApiError, sendFeedback, streamChat, type Citation, type HistoryItem } from './api';

export interface ChatMessage {
	id: string;
	role: 'user' | 'assistant';
	content: string;
	citations: Citation[];
	abstained: boolean;
	dataAsOf: string | null;
	streaming: boolean;
	error: string | null;
	feedback: 'up' | 'down' | null;
}

const MAX_TURNS = 6;
const uid = () => crypto.randomUUID();

/** Estado reactivo del chat (Svelte 5 runes). Historial solo en memoria de la sesión. */
export class ChatState {
	messages = $state<ChatMessage[]>([]);
	busy = $state(false);
	private controller: AbortController | null = null;

	/** Últimos 6 turnos (12 mensajes) completados, previos al mensaje en curso. */
	private history(upTo: number): HistoryItem[] {
		return this.messages
			.slice(0, upTo)
			.filter((m) => !m.error && m.content.trim())
			.map((m) => ({ role: m.role, content: m.content }))
			.slice(-MAX_TURNS * 2);
	}

	async send(text: string) {
		const message = text.trim();
		if (!message || this.busy) return;
		const history = this.history(this.messages.length);
		this.messages.push(this.blank('user', message));
		await this.ask(message, history);
	}

	/** Reintenta la última respuesta fallida o detenida. */
	async retry() {
		if (this.busy) return;
		const last = this.messages.at(-1);
		if (!last || last.role !== 'assistant') return;
		const q = this.messages.at(-2);
		if (!q || q.role !== 'user') return;
		const history = this.history(this.messages.length - 2);
		this.messages.pop();
		await this.ask(q.content, history);
	}

	stop() {
		this.controller?.abort();
	}

	clear() {
		this.stop();
		this.messages = [];
	}

	async rate(id: string, value: 'up' | 'down') {
		const m = this.messages.find((x) => x.id === id);
		if (!m || m.feedback) return;
		m.feedback = value;
		try {
			await sendFeedback({ message_id: id, value });
		} catch {
			m.feedback = null;
		}
	}

	private blank(role: 'user' | 'assistant', content = ''): ChatMessage {
		return {
			id: uid(),
			role,
			content,
			citations: [],
			abstained: false,
			dataAsOf: null,
			streaming: false,
			error: null,
			feedback: null
		};
	}

	private async ask(message: string, history: HistoryItem[]) {
		this.messages.push({ ...this.blank('assistant'), streaming: true });
		const reply = this.messages[this.messages.length - 1];
		this.busy = true;
		this.controller = new AbortController();
		try {
			await streamChat(
				{ message, history },
				{
					onToken: (t) => (reply.content += t),
					onFinal: (f) => {
						reply.content = f.answer || reply.content;
						reply.citations = f.citations ?? [];
						reply.abstained = !!f.abstained;
						reply.dataAsOf = f.data_as_of ?? null;
					}
				},
				this.controller.signal
			);
		} catch (e) {
			if (this.controller.signal.aborted) reply.error = 'Respuesta detenida.';
			else reply.error = e instanceof ApiError ? e.message : 'Ocurrió un error inesperado.';
		} finally {
			reply.streaming = false;
			this.busy = false;
			this.controller = null;
		}
	}
}
