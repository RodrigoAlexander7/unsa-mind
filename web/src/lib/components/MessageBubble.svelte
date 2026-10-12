<script lang="ts">
	import type { ChatMessage } from '$lib/chat.svelte';
	import { formatDate, renderMarkdown } from '$lib/markdown';
	import Citations from './Citations.svelte';

	let {
		message,
		isLast,
		onrate,
		onretry
	}: {
		message: ChatMessage;
		isLast: boolean;
		onrate: (id: string, v: 'up' | 'down') => void;
		onretry: () => void;
	} = $props();

	const html = $derived(message.role === 'assistant' ? renderMarkdown(message.content) : '');
</script>

{#if message.role === 'user'}
	<div class="flex justify-end">
		<div
			class="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-sm px-4 py-2 text-white [overflow-wrap:anywhere]"
			style="background: var(--user-bg)"
		>
			<span class="sr-only-live">Usted: </span>{message.content}
		</div>
	</div>
{:else}
	<article class="flex" aria-label="Respuesta del asistente" aria-busy={message.streaming}>
		<div class="card max-w-[95%] min-w-0 rounded-bl-sm">
			{#if message.abstained && !message.streaming}
				<p class="sans mb-2 rounded-md border border-[var(--accent)] px-3 py-2 text-sm">
					No cuento con información suficiente para responder con certeza. Le recomendamos consultar
					directamente en Secretaría.
				</p>
			{/if}
			{#if message.content}
				<div class="md [overflow-wrap:anywhere]">{@html html}</div>
			{:else if message.streaming}
				<p class="sans text-[var(--muted)]">Consultando información…</p>
			{/if}
			{#if message.streaming && message.content}<span class="sans text-xs text-[var(--muted)]">▍</span>{/if}

			{#if message.error}
				<div role="alert" class="sans mt-2 text-sm text-[var(--danger)]">
					{message.error}
					{#if isLast}
						<button class="btn ml-2" onclick={onretry}>Reintentar</button>
					{/if}
				</div>
			{/if}

			{#if !message.streaming && !message.error}
				<Citations citations={message.citations} />
				<div class="sans mt-3 flex flex-wrap items-center gap-2 text-xs text-[var(--muted)]">
					{#if message.dataAsOf}
						<span>Información actualizada al {formatDate(message.dataAsOf)}</span>
					{/if}
					<span class="ml-auto flex gap-1" role="group" aria-label="¿Fue útil esta respuesta?">
						<button
							class="btn !min-h-9 !px-2"
							aria-label="Respuesta útil"
							aria-pressed={message.feedback === 'up'}
							disabled={!!message.feedback}
							onclick={() => onrate(message.id, 'up')}>👍</button
						>
						<button
							class="btn !min-h-9 !px-2"
							aria-label="Respuesta no útil"
							aria-pressed={message.feedback === 'down'}
							disabled={!!message.feedback}
							onclick={() => onrate(message.id, 'down')}>👎</button
						>
					</span>
				</div>
			{/if}
		</div>
	</article>
{/if}
