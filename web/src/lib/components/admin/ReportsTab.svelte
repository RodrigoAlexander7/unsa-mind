<script lang="ts">
	import { admin, type Report } from '$lib/api';
	import { formatDateTime } from '$lib/markdown';

	let { token, onerror }: { token: string; onerror: (e: unknown) => void } = $props();
	const api = $derived(admin(token));

	let reports = $state<Report[]>([]);
	let loaded = $state(false);

	$effect(() => {
		api
			.reports(20)
			.then((r) => {
				reports = r;
				loaded = true;
			})
			.catch(onerror);
	});

	/** El esquema exacto del informe lo define el backend: se aceptan alias comunes. */
	function pick(r: Report, keys: string[]): string {
		for (const k of keys) {
			const v = r[k];
			if (typeof v === 'number') return String(v);
			if (Array.isArray(v)) return String(v.length);
			if (v && typeof v === 'object') return String(Object.keys(v).length);
		}
		return '0';
	}
	const when = (r: Report) =>
		formatDateTime(String(r.started_at ?? r.run_at ?? r.created_at ?? r.timestamp ?? r.finished_at ?? ''));
</script>

<section class="card sans overflow-x-auto !p-0" aria-labelledby="h-rep">
	<h2 id="h-rep" class="p-3 text-lg font-bold">Últimas ejecuciones</h2>
	<table class="w-full text-left text-sm">
		<thead class="bg-[var(--surface-2)]">
			<tr>
				<th scope="col" class="p-2">Fecha</th>
				<th scope="col" class="p-2">Nuevos</th>
				<th scope="col" class="p-2">Cambiados</th>
				<th scope="col" class="p-2">Sin cambios</th>
				<th scope="col" class="p-2">Errores</th>
			</tr>
		</thead>
		<tbody>
			{#each reports as r, i (i)}
				<tr class="border-t border-[var(--border)]">
					<td class="p-2">{when(r)}</td>
					<td class="p-2">{pick(r, ['new', 'new_count', 'added', 'created'])}</td>
					<td class="p-2">{pick(r, ['changed', 'changed_count', 'updated'])}</td>
					<td class="p-2">{pick(r, ['unchanged', 'unchanged_count', 'skipped'])}</td>
					<td class="p-2" class:text-[var(--danger)]={pick(r, ['errors', 'error_count', 'failed']) !== '0'}>
						{pick(r, ['errors', 'error_count', 'failed'])}
					</td>
				</tr>
			{:else}
				<tr><td colspan="5" class="p-3 text-[var(--muted)]">{loaded ? 'Sin informes.' : 'Cargando…'}</td></tr>
			{/each}
		</tbody>
	</table>
</section>
