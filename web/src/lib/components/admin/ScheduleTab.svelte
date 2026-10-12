<script lang="ts">
	import { admin, type Schedule } from '$lib/api';
	import { formatDateTime } from '$lib/markdown';

	let { token, onerror }: { token: string; onerror: (e: unknown) => void } = $props();
	const api = $derived(admin(token));

	const PRESETS = [
		{ label: 'Cada 6 h', interval: 360, cron: null as string | null },
		{ label: 'Diario 03:00', interval: 1440, cron: '0 3 * * *' },
		{ label: 'Semanal (dom 03:00)', interval: 10080, cron: '0 3 * * 0' }
	];

	let sched = $state<Schedule | null>(null);
	let enabled = $state(true);
	let interval = $state(360);
	let cron = $state('');
	let useCron = $state(false);
	let msg = $state('');
	let busy = $state(false);

	function load(s: Schedule) {
		sched = s;
		enabled = s.enabled;
		interval = s.interval_minutes;
		cron = s.cron ?? '';
		useCron = !!s.cron;
	}

	$effect(() => {
		api.getSchedule().then(load).catch(onerror);
	});

	function preset(p: (typeof PRESETS)[number]) {
		interval = p.interval;
		cron = p.cron ?? '';
		useCron = !!p.cron;
	}

	async function save() {
		busy = true;
		msg = '';
		try {
			load(
				await api.putSchedule({
					enabled,
					interval_minutes: Number(interval),
					cron: useCron && cron.trim() ? cron.trim() : null
				})
			);
			msg = 'Programación guardada.';
		} catch (e) {
			onerror(e);
		} finally {
			busy = false;
		}
	}

	async function runNow() {
		if (!confirm('¿Ejecutar la actualización de fuentes ahora?')) return;
		busy = true;
		msg = '';
		try {
			await api.update({ force: false });
			msg = 'Actualización iniciada. Revise la pestaña Informes.';
		} catch (e) {
			onerror(e);
		} finally {
			busy = false;
		}
	}
</script>

<section class="card sans space-y-4" aria-labelledby="h-sched">
	<h2 id="h-sched" class="text-lg font-bold">Programación de actualizaciones</h2>
	{#if !sched}
		<p class="text-[var(--muted)]">Cargando…</p>
	{:else}
		<p>
			Próxima ejecución: <strong>{enabled ? formatDateTime(sched.next_run) : 'deshabilitada'}</strong>
		</p>
		<label class="flex items-center gap-2">
			<input type="checkbox" bind:checked={enabled} class="size-5" /> Actualización automática habilitada
		</label>
		<div class="flex flex-wrap gap-2" role="group" aria-label="Presets">
			{#each PRESETS as p (p.label)}
				<button class="btn" onclick={() => preset(p)}>{p.label}</button>
			{/each}
		</div>
		<fieldset class="space-y-3">
			<legend class="label">Modo</legend>
			<label class="flex items-center gap-2"
				><input type="radio" bind:group={useCron} value={false} /> Intervalo en minutos</label
			>
			<input class="field max-w-48" type="number" min="1" bind:value={interval} disabled={useCron} aria-label="Minutos" />
			<label class="flex items-center gap-2"
				><input type="radio" bind:group={useCron} value={true} /> Expresión cron</label
			>
			<input class="field max-w-64" bind:value={cron} disabled={!useCron} placeholder="0 3 * * *" aria-label="Cron" />
		</fieldset>
		<div class="flex flex-wrap gap-2">
			<button class="btn btn-primary" onclick={save} disabled={busy}>Guardar</button>
			<button class="btn" onclick={runNow} disabled={busy}>Actualizar ahora</button>
		</div>
		<p role="status" class="text-sm text-[var(--ok)]">{msg}</p>
	{/if}
</section>
