import asyncio
import io
import logging
import time

import httpx
import pytest

from clashbot import __main__ as cli

TOKEN = "7777777:AAconsole-token-di-prova"
OWNER = "424242"
URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
ALERTS = "clashbot: exited\nbackup: nessun dump"


class FakeStore:
    def __init__(self, **secrets):
        self.secrets = secrets

    async def get_secret(self, kind):
        return self.secrets.get(kind)


class Telegram:
    def __init__(self, status=200, body=None, text=None, error=None):
        self.status = status
        self.body = {"ok": True, "result": {"message_id": 1}} if body is None else body
        self.text = text
        self.error = error
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error(f"errore verso {request.url}", request=request)
        if self.text is not None:
            return httpx.Response(self.status, text=self.text)
        return httpx.Response(self.status, json=self.body)


def run_main(monkeypatch, argv, store, telegram):
    real_notify = cli.notify

    async def fake_with_store(fn, database=None):
        return await fn(store)

    monkeypatch.setattr(cli, "with_store", fake_with_store)
    monkeypatch.setattr(cli, "notify", lambda s, text: real_notify(s, text, transport=httpx.MockTransport(telegram)))
    return cli.main(argv)


def full_store():
    return FakeStore(console_token=TOKEN, owner_id=OWNER)


def fails(monkeypatch, argv, store, telegram):
    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch, argv, store, telegram)
    assert exc.value.code not in (None, 0)
    return str(exc.value.code)


def test_notify_manda_un_solo_messaggio_al_proprietario_e_esce_0(monkeypatch, capsys):
    telegram = Telegram()
    assert run_main(monkeypatch, ["notify", ALERTS], full_store(), telegram) is None
    assert len(telegram.requests) == 1
    request = telegram.requests[0]
    assert request.method == "POST"
    assert str(request.url) == URL
    assert request.extensions["timeout"] == {"connect": 15, "read": 15, "write": 15, "pool": 15}
    assert httpx.Response(200, content=request.content).json() == {"chat_id": OWNER, "text": ALERTS}
    assert TOKEN not in capsys.readouterr().out


def test_notify_legge_il_testo_da_stdin_con_il_trattino(monkeypatch):
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO("riga uno\nriga due\n"))
    telegram = Telegram()
    run_main(monkeypatch, ["notify", "-"], full_store(), telegram)
    assert httpx.Response(200, content=telegram.requests[0].content).json()["text"] == "riga uno\nriga due"


def test_notify_tiene_il_messaggio_nel_limite_di_telegram(monkeypatch):
    telegram = Telegram()
    run_main(monkeypatch, ["notify", "x" * 5000], full_store(), telegram)
    assert httpx.Response(200, content=telegram.requests[0].content).json()["text"] == "x" * 4096


@pytest.mark.parametrize("argv", [["notify"], ["notify", "   "], ["notify", "-"]])
def test_notify_senza_testo_si_ferma_prima_del_database(monkeypatch, argv):
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO("\n"))

    def vietato(*args, **kwargs):
        raise AssertionError("database aperto")

    monkeypatch.setattr(cli, "with_store", vietato)
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code not in (None, 0) and "notify" in str(exc.value.code)


def test_notify_senza_console_token_non_chiama_telegram(monkeypatch):
    telegram = Telegram()
    message = fails(monkeypatch, ["notify", ALERTS], FakeStore(owner_id=OWNER), telegram)
    assert "console_token" in message
    assert telegram.requests == []


def test_notify_senza_owner_id_non_chiama_telegram(monkeypatch):
    telegram = Telegram()
    message = fails(monkeypatch, ["notify", ALERTS], FakeStore(console_token=TOKEN), telegram)
    assert "owner_id" in message
    assert telegram.requests == []


@pytest.mark.parametrize("telegram, expected", [
    (Telegram(403, {"ok": False, "error_code": 403, "description": f"Forbidden: bot was blocked {TOKEN}"}), "403"),
    (Telegram(200, {"ok": False, "description": "Bad Request: chat not found"}), "chat not found"),
    (Telegram(502, text=f"<html>bad gateway {TOKEN}</html>"), "502"),
    (Telegram(error=httpx.ConnectError), "ConnectError"),
    (Telegram(error=httpx.ReadTimeout), "ReadTimeout"),
])
def test_notify_con_errore_di_telegram_esce_diverso_da_0(monkeypatch, telegram, expected):
    message = fails(monkeypatch, ["notify", ALERTS], full_store(), telegram)
    assert len(telegram.requests) == 1
    assert expected in message
    assert TOKEN not in message


@pytest.mark.parametrize("store, telegram", [
    (full_store(), Telegram()),
    (FakeStore(owner_id=OWNER), Telegram()),
    (FakeStore(console_token=TOKEN), Telegram()),
    (full_store(), Telegram(401, {"ok": False, "description": f"Unauthorized {TOKEN}"})),
    (full_store(), Telegram(500, text=TOKEN)),
    (full_store(), Telegram(error=httpx.ConnectError)),
    (full_store(), Telegram(error=httpx.ReadTimeout)),
])
def test_nessuna_uscita_contiene_il_token(monkeypatch, capsys, caplog, store, telegram):
    caplog.set_level(logging.DEBUG)
    try:
        run_main(monkeypatch, ["notify", ALERTS], store, telegram)
        exit_text = ""
    except SystemExit as exc:
        exit_text = str(exc.code)
    captured = capsys.readouterr()
    assert logging.getLogger("httpx").getEffectiveLevel() > logging.INFO
    for text in (captured.out, captured.err, caplog.text, exit_text):
        assert TOKEN not in text
        assert TOKEN.split(":", 1)[1] not in text
        assert OWNER not in text


def test_notify_ha_un_limite_totale_anche_se_telegram_risponde_piano(monkeypatch):
    requests = []

    async def lento(request):
        requests.append(request)
        await asyncio.sleep(5)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(cli, "NOTIFY_TIMEOUT", 0.2)
    started = time.monotonic()
    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch, ["notify", ALERTS], full_store(), lento)
    assert time.monotonic() - started < 3
    assert len(requests) == 1
    assert str(exc.value.code) == "avviso non inviato: TimeoutError"
    assert exc.value.__cause__ is None and exc.value.__suppress_context__


def test_notify_non_incatena_eccezioni_con_l_indirizzo(monkeypatch):
    telegram = Telegram(error=httpx.ConnectError)
    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch, ["notify", ALERTS], full_store(), telegram)
    assert exc.value.__cause__ is None and exc.value.__suppress_context__
