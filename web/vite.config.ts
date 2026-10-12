import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vitest/config';

const target = process.env.API_PROXY_TARGET ?? 'http://localhost:8000';

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],
	server: { proxy: { '/api': { target, changeOrigin: true } } },
	test: { include: ['src/**/*.test.ts'] }
});
