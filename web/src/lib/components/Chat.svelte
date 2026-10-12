<script lang="ts">
	import { tick } from 'svelte';
	import { ChatState } from '$lib/chat.svelte';
	import MessageBubble from './MessageBubble.svelte';

	let { compact = false }: { compact?: boolean } = $props();

	const chat = new ChatState();
	let input = $state('');
	let box: HTMLTextAreaElement;
	let scroller: HTMLDivElement;

	const FAQ = [
		{ label: 'Admisión', q: '¿Cuáles son los requisitos y el proceso de admisión a la UNSA?' },
		{ label: 'Posgrado', q: '¿Qué programas de posgrado ofrece la UNSA y cómo postular?' },
		{ label: 'Convenios', q: '¿Qué convenios vigentes tiene la UNSA?' },
		{ label: 'Trámites', q: '¿Cómo realizo trámites académicos y administrativos en la UNSA?' }
	];

	// Texto anunciado a lectores de pantalla: solo al finalizar cada respuesta.
	const announce = $derived.by(() => {
		const m = chat.messages.at(-1);
		if (!m || m.role !== 'assistant') return '';
		if (m.streaming) return 'Generando respuesta…';
		return m.error ?? 'Respuesta lista.';
	});

	async function submit(text = input) {
		if (!text.trim() || chat.busy) return;
		input = '';
		const p = chat.send(text);
		await scrollDown();
		await p;
		await scrollDown();
		box?.focus();
	}

	async function scrollDown() {
		await tick();
		scroller?.scrollTo({ top: scroller.scrollHeight });
	}

	$effect(() => {
		// sigue el streaming
		chat.messages.at(-1)?.content;
		scrollDown();
	});

	function onkey(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
			e.preventDefault();
			submit();
		}
	}
</script>

<div class="flex h-full min-h-0 flex-col">
	<div
		bind:this={scroller}
		class="min-h-0 flex-1 overflow-y-auto px-3 py-4 sm:px-6"
		role="log"
		aria-label="Conversación"
	>
		<div class="mx-auto flex max-w-3xl flex-col gap-4">
			{#if chat.messages.length === 0}
				<div class="card">
					<p class="font-semibold">Bienvenido/a al asistente virtual de la UNSA.</p>
					<p class="sans mt-1 text-sm text-[var(--muted)]">
						Consulte sobre admisión, posgrado, convenios y trámites. Elija una pregunta frecuente o
						escriba la suya.
					</p>
					<div class="sans mt-3 flex flex-wrap gap-2">
						{#each FAQ as f (f.label)}
							<button class="btn" onclick={() => submit(f.q)}>{f.label}</button>
						{/each}
					</div>
				</div>
			{/if}
			{#each chat.messages as m, i (m.id)}
				<MessageBubble
					message={m}
					isLast={i === chat.messages.length - 1}
					onrate={(id, v) => chat.rate(id, v)}
					onretry={() => chat.retry()}
				/>
			{/each}
		</div>
	</div>

	<div class="sr-only-live" aria-live="polite" role="status">{announce}</div>

	<form
		class="sans border-t border-[var(--border)] bg-[var(--surface)] px-3 py-3 sm:px-6"
		onsubmit={(e) => {
			e.preventDefault();
			submit();
		}}
	>
		<div class="mx-auto max-w-3xl">
			<div class="flex items-end gap-2">
				<label for="q" class="sr-only-live">Escriba su consulta</label>
				<textarea
					id="q"
					bind:this={box}
					bind:value={input}
					onkeydown={onkey}
					rows="1"
					maxlength="2000"
					placeholder="Escriba su consulta…"
					class="field max-h-40 resize-none"
				></textarea>
				{#if chat.busy}
					<button type="button" class="btn" onclick={() => chat.stop()}>Detener</button>
				{:else}
					<button type="submit" class="btn btn-primary" disabled={!input.trim()}>Enviar</button>
				{/if}
			</div>
			<div class="mt-2 flex items-center justify-between gap-2 text-xs text-[var(--muted)]">
				<p>Asistente informativo. Para trámites oficiales consulte en Secretaría.</p>
				{#if chat.messages.length && !compact}
					<button type="button" class="underline" onclick={() => chat.clear()}>Nueva conversación</button>
				{/if}
			</div>
		</div>
	</form>
</div>
