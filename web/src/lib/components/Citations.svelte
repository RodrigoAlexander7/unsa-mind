<script lang="ts">
	import type { Citation } from '$lib/api';
	import { formatDate } from '$lib/markdown';

	let { citations }: { citations: Citation[] } = $props();

	const safeUrl = (u?: string | null) => (u && /^https?:\/\//i.test(u) ? u : null);
</script>

{#if citations.length}
	<details class="sans mt-3 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] text-sm">
		<summary class="cursor-pointer px-3 py-2 font-semibold">
			Fuentes consultadas ({citations.length})
		</summary>
		<ol class="space-y-2 px-3 pb-3 pt-1">
			{#each citations as c, i (i)}
				<li class="list-decimal ml-4">
					{#if safeUrl(c.url)}
						<a
							href={safeUrl(c.url)}
							target="_blank"
							rel="noopener noreferrer"
							class="font-medium text-[var(--primary)] underline [overflow-wrap:anywhere]">{c.title}</a
						>
					{:else}
						<span class="font-medium">{c.title}</span>
					{/if}
					{#if c.section}<span class="text-[var(--muted)]"> · {c.section}</span>{/if}
					{#if c.updated_at}
						<div class="text-xs text-[var(--muted)]">Actualizado: {formatDate(c.updated_at)}</div>
					{/if}
				</li>
			{/each}
		</ol>
	</details>
{/if}
