<script lang="ts">
	import { admin, type Stats } from '$lib/api';

	let { token, onerror }: { token: string; onerror: (e: unknown) => void } = $props();
	const api = $derived(admin(token));

	let stats = $state<Stats | null>(null);

	$effect(() => {
		api.stats().then((s) => (stats = s)).catch(onerror);
	});

	const label = (k: string) => k.replace(/_/g, ' ');
	const isObj = (v: unknown): v is Record<string, unknown> =>
		!!v && typeof v === 'object' && !Array.isArray(v);
	const show = (v: unknown) => (typeof v === 'object' ? JSON.stringify(v) : String(v));
</script>

<section class="sans space-y-4" aria-labelledby="h-st">
	<h2 id="h-st" class="text-lg font-bold">Estadísticas</h2>
	{#if !stats}
		<p class="text-[var(--muted)]">Cargando…</p>
	{:else}
		<div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
			{#each Object.entries(stats) as [k, v] (k)}
				<div class="card">
					<h3 class="label capitalize">{label(k)}</h3>
					{#if isObj(v)}
						<dl class="space-y-1 text-sm">
							{#each Object.entries(v) as [k2, v2] (k2)}
								<div class="flex justify-between gap-2">
									<dt class="capitalize text-[var(--muted)]">{label(k2)}</dt>
									<dd class="font-semibold [overflow-wrap:anywhere]">{show(v2)}</dd>
								</div>
							{/each}
						</dl>
					{:else}
						<p class="text-2xl font-bold [overflow-wrap:anywhere]">{show(v)}</p>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</section>
