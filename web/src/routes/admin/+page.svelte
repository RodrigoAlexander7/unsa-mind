<script lang="ts">
	import { onMount } from 'svelte';
	import { ApiError, admin } from '$lib/api';
	import ScheduleTab from '$lib/components/admin/ScheduleTab.svelte';
	import SourcesTab from '$lib/components/admin/SourcesTab.svelte';
	import ReportsTab from '$lib/components/admin/ReportsTab.svelte';
	import StatsTab from '$lib/components/admin/StatsTab.svelte';

	const KEY = 'unsa_admin_token';
	const TABS = [
		{ id: 'schedule', label: 'Programación' },
		{ id: 'sources', label: 'Fuentes' },
		{ id: 'reports', label: 'Informes' },
		{ id: 'stats', label: 'Estadísticas' }
	] as const;

	let token = $state('');
	let draft = $state('');
	let tab = $state<(typeof TABS)[number]['id']>('schedule');
	let error = $state('');
	let checking = $state(false);

	onMount(() => {
		try {
			token = sessionStorage.getItem(KEY) ?? '';
		} catch {
			/* sin sessionStorage */
		}
	});

	function logout() {
		token = '';
		try {
			sessionStorage.removeItem(KEY);
		} catch {
			/* ignorar */
		}
	}

	function fail(e: unknown) {
		if (e instanceof ApiError && e.status === 401) {
			logout();
			error = 'Token inválido o expirado.';
		} else error = e instanceof Error ? e.message : 'Error inesperado.';
	}

	async function login() {
		checking = true;
		error = '';
		try {
			await admin(draft.trim()).getSchedule(); // valida el token
			token = draft.trim();
			draft = '';
			try {
				sessionStorage.setItem(KEY, token);
			} catch {
				/* ignorar */
			}
		} catch (e) {
			fail(e);
		} finally {
			checking = false;
		}
	}

	function onTabKey(e: KeyboardEvent) {
		const i = TABS.findIndex((t) => t.id === tab);
		const d = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
		if (!d) return;
		tab = TABS[(i + d + TABS.length) % TABS.length].id;
		document.getElementById('tab-' + tab)?.focus();
	}
</script>

<svelte:head><title>Administración · Asistente UNSA</title></svelte:head>

<header class="sans border-b-4 px-4 py-3 text-white" style="background:#7a1f2b;border-color:#b8892b">
	<div class="mx-auto flex max-w-5xl items-center justify-between">
		<h1 class="text-lg font-bold">Administración · Asistente UNSA</h1>
		{#if token}<button class="btn !text-[var(--text)]" onclick={logout}>Salir</button>{/if}
	</div>
</header>

<main class="mx-auto max-w-5xl space-y-4 p-4">
	{#if error}<p role="alert" class="sans card text-[var(--danger)]">{error}</p>{/if}

	{#if !token}
		<form
			class="card sans mx-auto max-w-sm space-y-3"
			onsubmit={(e) => {
				e.preventDefault();
				login();
			}}
		>
			<label class="label" for="tok">Token de administrador</label>
			<input id="tok" class="field" type="password" autocomplete="off" required bind:value={draft} />
			<button class="btn btn-primary w-full" disabled={checking || !draft.trim()}>
				{checking ? 'Verificando…' : 'Ingresar'}
			</button>
		</form>
	{:else}
		<div role="tablist" aria-label="Secciones" class="sans flex flex-wrap gap-1 border-b border-[var(--border)]">
			{#each TABS as t (t.id)}
				<button
					role="tab"
					id={'tab-' + t.id}
					aria-selected={tab === t.id}
					aria-controls={'panel-' + t.id}
					tabindex={tab === t.id ? 0 : -1}
					class="rounded-t-lg px-4 py-2 font-semibold"
					style={tab === t.id ? 'background:var(--primary);color:var(--on-primary)' : ''}
					onclick={() => (tab = t.id)}
					onkeydown={onTabKey}>{t.label}</button
				>
			{/each}
		</div>
		<div role="tabpanel" id={'panel-' + tab} aria-labelledby={'tab-' + tab}>
			{#if tab === 'schedule'}<ScheduleTab {token} onerror={fail} />
			{:else if tab === 'sources'}<SourcesTab {token} onerror={fail} />
			{:else if tab === 'reports'}<ReportsTab {token} onerror={fail} />
			{:else}<StatsTab {token} onerror={fail} />{/if}
		</div>
	{/if}
</main>
