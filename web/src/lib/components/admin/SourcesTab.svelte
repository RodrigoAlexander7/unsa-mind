<script lang="ts">
	import { admin, type Source, type SourceInput } from '$lib/api';
	import { formatDateTime } from '$lib/markdown';

	let { token, onerror }: { token: string; onerror: (e: unknown) => void } = $props();
	const api = $derived(admin(token));

	const empty = (): SourceInput => ({
		name: '',
		url: '',
		kind: 'web',
		authority: 5,
		metadata: {},
		follow_links: false,
		link_pattern: null,
		max_pages: 1,
		interval_minutes: null,
		enabled: true
	});

	let sources = $state<Source[]>([]);
	let loaded = $state(false);
	let form = $state<SourceInput | null>(null);
	let editingId = $state<string | null>(null);
	let metaText = $state('{}');
	let formError = $state('');

	async function load() {
		try {
			sources = await api.listSources();
			loaded = true;
		} catch (e) {
			onerror(e);
		}
	}
	$effect(() => {
		load();
	});

	function edit(s: Source | null) {
		formError = '';
		editingId = s?.id ?? null;
		form = s ? { ...s } : empty();
		metaText = JSON.stringify(form.metadata ?? {}, null, 2);
	}

	async function save() {
		if (!form) return;
		try {
			form.metadata = JSON.parse(metaText || '{}');
		} catch {
			formError = 'Los metadatos deben ser JSON válido.';
			return;
		}
		const body: SourceInput = {
			...form,
			authority: Number(form.authority),
			max_pages: Number(form.max_pages),
			interval_minutes: form.interval_minutes ? Number(form.interval_minutes) : null,
			link_pattern: form.link_pattern || null
		};
		try {
			if (editingId) await api.updateSource(editingId, body);
			else await api.createSource(body);
			form = null;
			await load();
		} catch (e) {
			formError = e instanceof Error ? e.message : 'Error al guardar.';
		}
	}

	async function remove(s: Source) {
		if (!confirm(`¿Eliminar la fuente "${s.name}"?`)) return;
		try {
			await api.deleteSource(s.id);
			await load();
		} catch (e) {
			onerror(e);
		}
	}

	async function toggle(s: Source) {
		try {
			const { id, last_run_at, ...rest } = s;
			void last_run_at;
			await api.updateSource(id, { ...rest, enabled: !s.enabled });
			await load();
		} catch (e) {
			onerror(e);
		}
	}
</script>

<section class="sans space-y-4" aria-labelledby="h-src">
	<div class="flex items-center justify-between">
		<h2 id="h-src" class="text-lg font-bold">Fuentes</h2>
		<button class="btn btn-primary" onclick={() => edit(null)}>Nueva fuente</button>
	</div>

	{#if form}
		<form
			class="card grid gap-3 sm:grid-cols-2"
			onsubmit={(e) => {
				e.preventDefault();
				save();
			}}
		>
			<div><label class="label" for="s-name">Nombre</label><input id="s-name" class="field" required bind:value={form.name} /></div>
			<div><label class="label" for="s-url">URL</label><input id="s-url" class="field" type="url" required bind:value={form.url} /></div>
			<div><label class="label" for="s-kind">Tipo</label><input id="s-kind" class="field" bind:value={form.kind} /></div>
			<div>
				<label class="label" for="s-auth">Autoridad</label>
				<input id="s-auth" class="field" type="number" min="0" bind:value={form.authority} />
			</div>
			<div>
				<label class="label" for="s-int">Intervalo propio (min, vacío = global)</label>
				<input id="s-int" class="field" type="number" min="1" bind:value={form.interval_minutes} />
			</div>
			<div><label class="label" for="s-max">Máx. páginas</label><input id="s-max" class="field" type="number" min="1" bind:value={form.max_pages} /></div>
			<div>
				<label class="label" for="s-pat">Patrón de enlaces (regex)</label>
				<input id="s-pat" class="field" bind:value={form.link_pattern} />
			</div>
			<div class="flex items-end gap-4">
				<label class="flex items-center gap-2"><input type="checkbox" class="size-5" bind:checked={form.follow_links} /> Seguir enlaces</label>
				<label class="flex items-center gap-2"><input type="checkbox" class="size-5" bind:checked={form.enabled} /> Habilitada</label>
			</div>
			<div class="sm:col-span-2">
				<label class="label" for="s-meta">Metadatos (JSON)</label>
				<textarea id="s-meta" class="field font-mono" rows="3" bind:value={metaText}></textarea>
			</div>
			{#if formError}<p role="alert" class="text-[var(--danger)] sm:col-span-2">{formError}</p>{/if}
			<div class="flex gap-2 sm:col-span-2">
				<button class="btn btn-primary" type="submit">Guardar</button>
				<button class="btn" type="button" onclick={() => (form = null)}>Cancelar</button>
			</div>
		</form>
	{/if}

	<div class="card overflow-x-auto !p-0">
		<table class="w-full text-left text-sm">
			<caption class="sr-only-live">Fuentes de información</caption>
			<thead class="bg-[var(--surface-2)]">
				<tr>
					<th scope="col" class="p-2">Nombre</th>
					<th scope="col" class="p-2">Autoridad</th>
					<th scope="col" class="p-2">Intervalo</th>
					<th scope="col" class="p-2">Habilitada</th>
					<th scope="col" class="p-2">Última ejecución</th>
					<th scope="col" class="p-2">Acciones</th>
				</tr>
			</thead>
			<tbody>
				{#each sources as s (s.id)}
					<tr class="border-t border-[var(--border)]">
						<td class="p-2">
							<div class="font-semibold">{s.name}</div>
							<div class="text-xs text-[var(--muted)] [overflow-wrap:anywhere]">{s.url}</div>
						</td>
						<td class="p-2">{s.authority}</td>
						<td class="p-2">{s.interval_minutes ? `${s.interval_minutes} min` : 'global'}</td>
						<td class="p-2">
							<input type="checkbox" class="size-5" checked={s.enabled} onchange={() => toggle(s)} aria-label={`Habilitar ${s.name}`} />
						</td>
						<td class="p-2">{formatDateTime(s.last_run_at)}</td>
						<td class="p-2 whitespace-nowrap">
							<button class="btn" onclick={() => edit(s)}>Editar</button>
							<button class="btn btn-danger" onclick={() => remove(s)}>Eliminar</button>
						</td>
					</tr>
				{:else}
					<tr><td colspan="6" class="p-3 text-[var(--muted)]">{loaded ? 'Sin fuentes.' : 'Cargando…'}</td></tr>
				{/each}
			</tbody>
		</table>
	</div>
</section>
