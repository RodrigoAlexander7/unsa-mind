<script lang="ts">
	import Chat from '$lib/components/Chat.svelte';
</script>

<svelte:head>
	<title>Asistente virtual · UNSA</title>
	<meta name="description" content="Asistente informativo de la Universidad Nacional de San Agustín de Arequipa." />
	<link rel="icon" href="/favicon.svg" />
</svelte:head>

<div class="flex h-dvh flex-col">
	<header class="sans border-b-4 px-4 py-3 text-white sm:px-6" style="background: #7a1f2b; border-color: #b8892b">
		<div class="mx-auto flex max-w-3xl items-baseline justify-between gap-3">
			<h1 class="text-lg font-bold">
				Asistente virtual <span style="color: #e3c277">UNSA</span>
			</h1>
			<span class="hidden text-sm opacity-90 sm:inline">Universidad Nacional de San Agustín de Arequipa</span>
		</div>
	</header>
	<main class="min-h-0 flex-1">
		<Chat />
	</main>
</div>
