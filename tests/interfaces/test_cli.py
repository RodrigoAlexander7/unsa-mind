import pytest

from unsa_mind.config.settings import Settings
from unsa_mind.interfaces.cli import main

Q = "¿Cómo solicito la reserva de matrícula?"


@pytest.fixture
def run(container, capsys):
    seen = []

    def factory(settings: Settings):
        seen.append(settings)
        return container

    def _run(*argv):
        code = main(list(argv), container_factory=factory)
        out = capsys.readouterr()
        return code, out.out, out.err

    _run.settings = seen
    return _run


def test_ask_prints_answer_and_citations(run):
    code, out, _ = run("ask", Q)
    assert code == 0 and "Fuentes:" in out and "https://unsa.test/reg" in out and "Reserva" in out


def test_ask_abstains(run):
    code, out, _ = run("ask", "dame una receta de pastel")
    assert code == 0 and "Fuentes:" not in out


def test_llm_override_and_agy_alias(run):
    run("ask", "--llm", "agy", "--model", "m1", Q)
    assert run.settings[-1].llm_provider == "agy" and run.settings[-1].llm_model == "m1"
    run("--llm", "gemini", "status")
    assert run.settings[-1].llm_provider == "gemini"
    code, out, _ = run("agy", Q)
    assert run.settings[-1].llm_provider == "agy" and code == 0 and "Fuentes:" in out


def test_chat_repl(run, monkeypatch):
    lines = iter([Q, "/fuentes", "", "/salir"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(lines))
    code, out, _ = run("chat")
    assert code == 0 and "reg" in out and "Fuentes:" in out


def test_chat_eof_exits_cleanly(run, monkeypatch):
    def eof(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    assert run("agy")[0] == 0


def test_sources_lifecycle(run):
    code, out, _ = run("sources", "list")
    assert code == 0 and "reg" in out
    assert run("sources", "add", "avisos", "https://unsa.test/a", "--authority", "low")[0] == 0
    assert run("sources", "add", "avisos", "https://unsa.test/a")[0] == 1
    run("sources", "disable", "avisos")
    assert "off" in run("sources", "list")[1]
    run("sources", "enable", "avisos")
    assert run("sources", "remove", "avisos")[0] == 0
    code, _, err = run("sources", "remove", "avisos")
    assert code == 1 and "no existe" in err


def test_ingest(run):
    code, out, _ = run("ingest", "--force", "--source", "reg")
    assert code == 0 and "reg" in out and "sin cambios=1" in out


def test_schedule_show_and_set(run, container):
    code, out, _ = run("schedule", "show")
    assert code == 0 and "cada 60 min" in out
    code, out, _ = run("schedule", "set", "--cron", "0 3 * * *")
    assert code == 0 and "cron '0 3 * * *'" in out and "próximo disparo" in out
    assert container.scheduler.applied[-1].cron == "0 3 * * *"
    run("schedule", "set", "--interval-minutes", "30", "--disable")
    s = container.scheduler.applied[-1]
    assert (s.enabled, s.interval_minutes, s.cron) == (False, 30, None)
    assert "desactivado" in run("schedule", "show")[1]
    assert run("schedule", "set", "--cron", "nope")[0] == 2
    assert run("schedule", "set", "--interval-minutes", "0")[0] == 2
    assert run("schedule", "set")[0] == 2


def test_status(run):
    code, out, _ = run("status")
    assert code == 0 and "Chunks:" in out and "Fuentes:    1" in out


def test_usage_errors(run):
    assert run()[0] == 2
    assert run("ask", "--llm", "nope", "x")[0] == 2


def test_error_exit_code(container, capsys):
    def boom(settings):
        raise RuntimeError("sin agy")

    assert main(["ask", "x"], container_factory=boom) == 1
    assert "sin agy" in capsys.readouterr().err
