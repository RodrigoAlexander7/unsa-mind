/** Parser SSE incremental (para fetch + ReadableStream; EventSource no soporta POST). */

export interface SseMessage {
	event: string;
	data: string;
}

export class SseParser {
	private buffer = '';
	private event = '';
	private data: string[] = [];

	/** Alimenta un fragmento de texto y devuelve los eventos completos. */
	push(chunk: string): SseMessage[] {
		this.buffer += chunk;
		const out: SseMessage[] = [];
		let idx: number;
		while ((idx = this.buffer.search(/\r\n|\n|\r/)) !== -1) {
			const nl = this.buffer.slice(idx).match(/^(\r\n|\n|\r)/)![0];
			// Un "\r" final puede ser la mitad de "\r\n": esperar más datos.
			if (nl === '\r' && idx + 1 === this.buffer.length) break;
			const line = this.buffer.slice(0, idx);
			this.buffer = this.buffer.slice(idx + nl.length);
			const msg = this.line(line);
			if (msg) out.push(msg);
		}
		return out;
	}

	/** Vacía lo pendiente al terminar el stream. */
	flush(): SseMessage[] {
		const out: SseMessage[] = [];
		if (this.buffer) {
			const msg = this.line(this.buffer.replace(/\r$/, ''));
			this.buffer = '';
			if (msg) out.push(msg);
		}
		const last = this.dispatch();
		if (last) out.push(last);
		return out;
	}

	private line(line: string): SseMessage | null {
		if (line === '') return this.dispatch();
		if (line.startsWith(':')) return null; // comentario / keep-alive
		const c = line.indexOf(':');
		const field = c === -1 ? line : line.slice(0, c);
		let value = c === -1 ? '' : line.slice(c + 1);
		if (value.startsWith(' ')) value = value.slice(1);
		if (field === 'event') this.event = value;
		else if (field === 'data') this.data.push(value);
		return null;
	}

	private dispatch(): SseMessage | null {
		if (this.data.length === 0) {
			this.event = '';
			return null;
		}
		const msg = { event: this.event || 'message', data: this.data.join('\n') };
		this.event = '';
		this.data = [];
		return msg;
	}
}

/** Convierte un ReadableStream de bytes en un iterable asíncrono de eventos SSE. */
export async function* readSse(body: ReadableStream<Uint8Array>): AsyncGenerator<SseMessage> {
	const reader = body.getReader();
	const decoder = new TextDecoder();
	const parser = new SseParser();
	try {
		while (true) {
			const { done, value } = await reader.read();
			if (done) break;
			yield* parser.push(decoder.decode(value, { stream: true }));
		}
		yield* parser.push(decoder.decode());
		yield* parser.flush();
	} finally {
		reader.releaseLock();
	}
}
