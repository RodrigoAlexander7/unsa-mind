"""CLI de UNSA Mind (argparse, sin dependencias nuevas).

    unsa-mind ask "¿Cómo reservo matrícula?" --llm agy
    unsa-mind chat --llm agy          # REPL con streaming (/salir, /fuentes)
    unsa-mind agy "pregunta"          # alias: fuerza --llm agy (sin pregunta => REPL)
    unsa-mind sources list|add|remove|enable|disable
    unsa-mind ingest [--source ID] [--force]
    unsa-mind schedule show | set --interval-minutes N | --cron "0 3 * * *" | --enable/--disable
    unsa-mind status
    unsa-mind serve [--host H] [--port P]

`main(argv, container_factory=...)` permite inyectar el Container en pruebas.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Callable, Sequence

from unsa_mind.application.ports import ChatMessage
from unsa_mind.config.container import Container, bootstrap, build_container
from unsa_mind.config.settings import Settings, get_settings
from unsa_mind.domain.entities import Answer, Authority, DocKind, Schedule, Source, UpdateReport
from unsa_mind.interfaces.common import next_fire, validate_cron

ContainerFactory = Callable[[Settings], Container]
PROVIDERS = ["fake", "claude", "gemini", "openrouter", "agy"]
EXIT_OK, EXIT_ERROR, EXIT_USAGE = 0, 1, 2


def _default_factory(settings: Settings) -> Container:
    return build_container(settings)


# ---------------------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------------------
def _common() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--llm", choices=PROVIDERS, default=argparse.SUPPRESS,
                   help="proveedor LLM (sobreescribe UNSA_LLM_PROVIDER)")
    p.add_argument("--model", default=argparse.SUPPRESS,
                   help="modelo del proveedor (sobreescribe UNSA_LLM_MODEL)")
    return p


def build_parser() -> argparse.ArgumentParser:
    common = _common()
    parser = argparse.ArgumentParser(
        prog="unsa-mind", description="Asistente virtual de la UNSA", parents=[common]
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="comando")

    def add(name: str, help_: str) -> argparse.ArgumentParser:
        return sub.add_parser(name, help=help_, description=help_, parents=[common])

    sp = add("serve", "Levanta la API REST + A2A")
    sp.add_argument("--host")
    sp.add_argument("--port", type=int)

    sp = add("ask", "Hace una pregunta y muestra la respuesta con citas")
    sp.add_argument("question")

    add("chat", "Chat interactivo con historial y streaming")

    sp = add("agy", "Atajo: usa el proveedor agy (sin pregunta abre el chat)")
    sp.add_argument("question", nargs="?")

    sp = add("sources", "Administra el catálogo de fuentes")
    ssub = sp.add_subparsers(dest="action", required=True, metavar="acción")
    ssub.add_parser("list", help="lista las fuentes", parents=[common])
    sa = ssub.add_parser("add", help="añade una fuente", parents=[common])
    sa.add_argument("id")
    sa.add_argument("url")
    sa.add_argument("--name")
    sa.add_argument("--kind", choices=[k.value for k in DocKind], default="html")
    sa.add_argument("--authority", choices=[a.value for a in Authority], default="medium")
    sa.add_argument("--follow-links", action="store_true")
    sa.add_argument("--link-pattern")
    sa.add_argument("--max-pages", type=int, default=20)
    sa.add_argument("--interval-minutes", type=int)
    for act in ("remove", "enable", "disable"):
        ssub.add_parser(act, help=f"{act} una fuente", parents=[common]).add_argument("id")

    sp = add("ingest", "Ejecuta un ciclo de actualización")
    sp.add_argument("--source", action="append", dest="only", metavar="ID")
    sp.add_argument("--force", action="store_true")

    sp = add("schedule", "Muestra o modifica la frecuencia de actualización")
    csub = sp.add_subparsers(dest="action", required=True, metavar="acción")
    csub.add_parser("show", help="muestra el schedule", parents=[common])
    cs = csub.add_parser("set", help="modifica el schedule", parents=[common])
    cs.add_argument("--interval-minutes", type=int)
    cs.add_argument("--cron")
    grp = cs.add_mutually_exclusive_group()
    grp.add_argument("--enable", action="store_true")
    grp.add_argument("--disable", action="store_true")

    add("status", "Muestra el estado del sistema")
    return parser


# ---------------------------------------------------------------------------------------
# Presentación
# ---------------------------------------------------------------------------------------
def _fmt_answer_footer(a: Answer) -> str:
    lines: list[str] = []
    if a.citations:
        lines.append("\nFuentes:")
        for i, c in enumerate(a.citations, 1):
            when = f" (actualizado {c.updated_at:%d/%m/%Y})" if c.updated_at else ""
            sec = f" — {c.section}" if c.section else ""
            lines.append(f"  [{i}] {c.title}{sec}{when}\n      {c.url}")
    if a.data_as_of:
        lines.append(f"\nInformación vigente al {a.data_as_of:%d/%m/%Y}.")
    return "\n".join(lines)


def _print_report(r: UpdateReport) -> None:
    for s in r.sources:
        print(
            f"  {s.source_id}: páginas={s.pages_fetched} nuevos={s.documents_new} "
            f"cambiados={s.documents_changed} sin cambios={s.documents_unchanged} "
            f"chunks={s.chunks_indexed}"
        )
        for e in s.errors:
            print(f"    ! {e}", file=sys.stderr)
    if not r.sources:
        print("  (no había fuentes pendientes de actualizar)")


def _fmt_schedule(s: Schedule) -> str:
    estado = "activo" if s.enabled else "desactivado"
    regla = f"cron '{s.cron}'" if s.cron else f"cada {s.interval_minutes} min"
    nxt = next_fire(s)
    return f"{estado}, {regla}" + (f"; próximo disparo: {nxt}" if nxt else "")


# ---------------------------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------------------------
async def _cmd_ask(c: Container, question: str) -> int:
    answer = await c.ask.execute(question)
    print(answer.text + _fmt_answer_footer(answer))
    return EXIT_OK


async def _stream_answer(c: Container, question: str, history: list[ChatMessage]) -> Answer | None:
    final: Answer | None = None
    async for ev in c.ask.stream(question, history=history):
        if ev.kind == "token":
            print(ev.token, end="", flush=True)
        elif ev.kind == "final":
            final = ev.answer
    print()
    return final


async def _cmd_chat(c: Container, first_question: str | None = None) -> int:
    print(f"Asistente UNSA (LLM: {c.llm.name}). Escribe tu pregunta; /fuentes lista las fuentes, /salir termina.")
    history: list[ChatMessage] = []
    pending = first_question
    while True:
        if pending is not None:
            line, pending = pending, None
            print(f"> {line}")
        else:
            try:
                line = (await asyncio.to_thread(input, "> ")).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return EXIT_OK
        if not line:
            continue
        if line in ("/salir", "/exit", "/quit"):
            return EXIT_OK
        if line == "/fuentes":
            await _cmd_sources_list(c)
            continue
        try:
            answer = await _stream_answer(c, line, history)
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            continue
        if answer is not None:
            print(_fmt_answer_footer(answer).lstrip("\n"))
            history += [ChatMessage("user", line), ChatMessage("assistant", answer.text)]


async def _cmd_sources_list(c: Container) -> int:
    sources = await c.sources.list_sources()
    if not sources:
        print("No hay fuentes registradas.")
    for s in sources:
        mark = "on " if s.enabled else "off"
        print(f"[{mark}] {s.id:<20} {s.authority.value:<6} {s.url}")
    return EXIT_OK


async def _cmd_sources(c: Container, a: argparse.Namespace) -> int:
    if a.action == "list":
        return await _cmd_sources_list(c)
    if a.action == "add":
        if await c.sources.get_source(a.id):
            print(f"Error: ya existe la fuente '{a.id}'", file=sys.stderr)
            return EXIT_ERROR
        await c.sources.save_source(
            Source(
                id=a.id, name=a.name or a.id, url=a.url, kind=DocKind(a.kind),
                authority=Authority(a.authority), follow_links=a.follow_links,
                link_pattern=a.link_pattern, max_pages=a.max_pages,
                interval_minutes=a.interval_minutes,
            )
        )
        print(f"Fuente '{a.id}' añadida.")
        return EXIT_OK
    src = await c.sources.get_source(a.id)
    if not src:
        print(f"Error: no existe la fuente '{a.id}'", file=sys.stderr)
        return EXIT_ERROR
    if a.action == "remove":
        await c.sources.delete_source(a.id)
        print(f"Fuente '{a.id}' eliminada.")
    else:
        src.enabled = a.action == "enable"
        await c.sources.save_source(src)
        print(f"Fuente '{a.id}' {'habilitada' if src.enabled else 'deshabilitada'}.")
    return EXIT_OK


async def _cmd_ingest(c: Container, a: argparse.Namespace) -> int:
    print("Actualizando fuentes...")
    report = await c.update_cycle.execute(force=a.force, only=a.only)
    _print_report(report)
    print(f"Chunks activos: {await c.vector_store.count()}")
    return EXIT_OK if report.ok else EXIT_ERROR


async def _cmd_schedule(c: Container, a: argparse.Namespace) -> int:
    current = await c.settings_repo.get_schedule()
    if a.action == "show":
        print(_fmt_schedule(current))
        return EXIT_OK
    if a.interval_minutes is None and a.cron is None and not (a.enable or a.disable):
        print("Error: indica --interval-minutes, --cron, --enable o --disable", file=sys.stderr)
        return EXIT_USAGE
    interval = current.interval_minutes if a.interval_minutes is None else a.interval_minutes
    if interval < 1:
        print("Error: --interval-minutes debe ser >= 1", file=sys.stderr)
        return EXIT_USAGE
    cron = current.cron if a.cron is None else (a.cron.strip() or None)
    if a.interval_minutes is not None and a.cron is None:
        cron = None  # fijar un intervalo explícito anula el cron previo
    if cron:
        try:
            validate_cron(cron)
        except ValueError as exc:
            print(f"Error: cron inválido: {exc}", file=sys.stderr)
            return EXIT_USAGE
    enabled = True if a.enable else False if a.disable else current.enabled
    new = Schedule(enabled, interval, cron)
    await c.settings_repo.save_schedule(new)
    c.scheduler.apply(new)
    print("Schedule guardado: " + _fmt_schedule(new))
    print("(Si el servidor ya está en marcha, aplícalo en caliente con PUT /api/admin/schedule.)")
    return EXIT_OK


async def _cmd_status(c: Container) -> int:
    reports = await c.settings_repo.list_reports(1)
    sources = await c.sources.list_sources()
    docs = await c.documents.list_documents(active_only=True)
    print(f"LLM:        {c.llm.name}")
    print(f"Chunks:     {await c.vector_store.count()}")
    print(f"Documentos: {len(docs)}")
    print(f"Fuentes:    {len(sources)} ({sum(s.enabled for s in sources)} habilitadas)")
    print(f"Schedule:   {_fmt_schedule(await c.settings_repo.get_schedule())}")
    if reports:
        r = reports[0]
        print(f"Último ciclo: {r.started_at:%Y-%m-%d %H:%M} UTC, {'ok' if r.ok else 'con errores'}")
    else:
        print("Último ciclo: nunca")
    return EXIT_OK


# ---------------------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------------------
async def _run(c: Container, a: argparse.Namespace) -> int:
    await bootstrap(c)
    cmd = a.command
    if cmd == "ask":
        return await _cmd_ask(c, a.question)
    if cmd == "agy":
        return await (_cmd_ask(c, a.question) if a.question else _cmd_chat(c))
    if cmd == "chat":
        return await _cmd_chat(c)
    if cmd == "sources":
        return await _cmd_sources(c, a)
    if cmd == "ingest":
        return await _cmd_ingest(c, a)
    if cmd == "schedule":
        return await _cmd_schedule(c, a)
    if cmd == "status":
        return await _cmd_status(c)
    raise AssertionError(cmd)


def _override_settings(a: argparse.Namespace) -> Settings:
    settings = get_settings()
    update: dict[str, object] = {}
    if a.command == "agy":
        update["llm_provider"] = "agy"
    elif getattr(a, "llm", None):
        update["llm_provider"] = a.llm
    if getattr(a, "model", None):
        update["llm_model"] = a.model
    return settings.model_copy(update=update) if update else settings


def _show_progress() -> None:
    """Muestra en stderr el avance de la ingesta (archivo, OCR por página, embeddings)."""
    logger = logging.getLogger("unsa_mind")
    logger.setLevel(logging.INFO)
    if not any(getattr(h, "_unsa_progress", False) for h in logger.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("  · %(message)s"))
        handler._unsa_progress = True  # type: ignore[attr-defined]
        logger.addHandler(handler)


def main(argv: Sequence[str] | None = None, container_factory: ContainerFactory | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows: evita UnicodeEncodeError con tildes
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else EXIT_USAGE

    if args.command == "ingest":
        _show_progress()

    factory = container_factory or _default_factory
    try:
        container = factory(_override_settings(args))
        if args.command == "serve":
            import uvicorn

            from unsa_mind.interfaces.api.app import create_app

            s = container.settings
            uvicorn.run(create_app(container), host=args.host or s.host, port=args.port or s.port)
            return EXIT_OK
        return asyncio.run(_run(container, args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
