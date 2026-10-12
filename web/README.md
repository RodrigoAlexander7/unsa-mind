# Frontend del asistente virtual UNSA

SvelteKit (Svelte 5, TypeScript, Tailwind v4, adapter-node).

## Uso

```bash
pnpm install
pnpm dev        # http://localhost:5173, proxy /api -> http://localhost:8000
pnpm check      # svelte-check
pnpm test       # vitest (parser SSE)
pnpm build && node build
```

## Configuración

- `PUBLIC_API_URL` (ver `.env.example`): URL base del backend FastAPI en producción
  (por defecto `http://localhost:8000`). En `pnpm dev` se ignora y se usa el proxy de Vite
  (`API_PROXY_TARGET` cambia el destino) para evitar CORS.
- En producción el backend debe permitir CORS desde el origen del frontend.

## Rutas

- `/` chat; `/embed` chat mínimo para `<iframe>`; `/admin` panel (token Bearer en `sessionStorage`).

```html
<iframe src="https://asistente.example/embed" title="Asistente UNSA" style="width:100%;height:600px;border:0"></iframe>
```

## Estructura

`src/lib/api.ts` capa tipada · `src/lib/sse.ts` parser SSE · `src/lib/chat.svelte.ts` estado del chat ·
`src/lib/components/` componentes · `Dockerfile` multi-stage.
