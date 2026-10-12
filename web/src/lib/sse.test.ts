import { describe, expect, it } from 'vitest';
import { readSse, SseParser, type SseMessage } from './sse';

describe('SseParser', () => {
	it('parsea eventos completos', () => {
		const p = new SseParser();
		const r = p.push('event: token\ndata: {"text":"Hola"}\n\nevent: final\ndata: {"answer":"x"}\n\n');
		expect(r).toEqual([
			{ event: 'token', data: '{"text":"Hola"}' },
			{ event: 'final', data: '{"answer":"x"}' }
		]);
	});

	it('maneja fragmentos partidos en cualquier punto', () => {
		const p = new SseParser();
		const input = 'event: token\ndata: {"text":"á"}\n\n';
		const out: SseMessage[] = [];
		for (const ch of input) out.push(...p.push(ch));
		expect(out).toEqual([{ event: 'token', data: '{"text":"á"}' }]);
	});

	it('soporta CRLF, incluso partido entre chunks', () => {
		const p = new SseParser();
		expect(p.push('event: a\r')).toEqual([]);
		expect(p.push('\ndata: 1\r\n\r')).toEqual([]);
		expect(p.push('\n')).toEqual([{ event: 'a', data: '1' }]);
	});

	it('une varias líneas data, ignora comentarios y usa "message" por defecto', () => {
		const p = new SseParser();
		expect(p.push(': ping\ndata: a\ndata: b\n\n')).toEqual([{ event: 'message', data: 'a\nb' }]);
	});

	it('no emite eventos sin data y reinicia el nombre', () => {
		const p = new SseParser();
		expect(p.push('event: x\n\ndata: 1\n\n')).toEqual([{ event: 'message', data: '1' }]);
	});

	it('flush emite el último evento sin línea en blanco', () => {
		const p = new SseParser();
		expect(p.push('event: final\ndata: {}')).toEqual([]);
		expect(p.flush()).toEqual([{ event: 'final', data: '{}' }]);
	});
});

describe('readSse', () => {
	it('lee un ReadableStream con caracteres multibyte partidos', async () => {
		const bytes = new TextEncoder().encode('event: token\ndata: ñandú\n\n');
		const stream = new ReadableStream<Uint8Array>({
			start(c) {
				for (let i = 0; i < bytes.length; i += 3) c.enqueue(bytes.slice(i, i + 3));
				c.close();
			}
		});
		const got: SseMessage[] = [];
		for await (const m of readSse(stream)) got.push(m);
		expect(got).toEqual([{ event: 'token', data: 'ñandú' }]);
	});
});
