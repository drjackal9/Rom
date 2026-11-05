import asyncio
from urllib.parse import urlencode

from clashbot.crypto import Vault
from clashbot.web import app as web_app, auth
from tests.test_web_status import ITALIAN, FakeStore, request

CONSOLE = "7:console"
OWNER = 555


class PanelStore(FakeStore):
    def __init__(self, tmp_path, notes=None, owner=OWNER):
        super().__init__(notes)
        self.vault = Vault(tmp_path)
        self.kv = {}
        self.secrets = {"console_token": CONSOLE, "owner_id": str(owner)}

    async def get_secret(self, kind):
        return self.secrets.get(kind)

    async def kv_set(self, key, body, ref=None, ttl=None):
        self.kv[key] = body

    async def kv_get(self, key):
        return self.kv.get(key)

    async def kv_del(self, key):
        self.kv.pop(key, None)


def serve(store, path, method="GET", cookie=None, body=None):
    headers = bytes(ITALIAN)
    if cookie:
        headers += f"Cookie: sid={cookie}\r\n".encode()
    raw = None
    if body is not None:
        raw = urlencode(body).encode()
        headers += b"Content-Type: application/x-www-form-urlencoded\r\n"
    req = request(path, method, headers=headers)
    if raw is not None:
        req.body = raw
    return asyncio.run(web_app.Site(store).router(req))


def solo_bandi(store):
    return all(key.startswith("ban") for key in store.kv)


def test_the_panel_the_login_and_the_logout_are_not_on_the_domain(tmp_path):
    for path in ("/panel", "/panel/usage.json", "/panel/string", "/auth?id=555&hash=pinco"):
        assert serve(PanelStore(tmp_path), path).status == 403, path
    for path in ("/panel", "/panel/string"):
        assert serve(PanelStore(tmp_path), path, "POST", body={"csrf": "pinco"}).status == 403, path
    store = PanelStore(tmp_path)
    assert serve(store, "/logout", "POST", body={"csrf": "pinco"}).status == 404
    assert solo_bandi(store)


def test_a_session_cookie_is_never_read_and_never_written(tmp_path):
    store = PanelStore(tmp_path)
    for path in ("/", "/status", "/panel"):
        res = serve(store, path, cookie="unasessione")
        assert "Set-Cookie" not in res.headers, path
    assert solo_bandi(store)


def test_the_site_keeps_only_the_signature_of_the_mini_app():
    for name in ("init_data", "user_id", "user_name", "start_param", "check_string"):
        assert hasattr(auth, name), name
    for name in ("login_data", "login_id", "new_sid", "cookie", "dead_cookie", "csrf"):
        assert not hasattr(auth, name), name
    for name in ("SESSION_TTL", "LOGIN_MAX_AGE", "COOKIE_FLAGS", "SID_BYTES", "CSRF_LEN"):
        assert not hasattr(auth, name), name


def test_the_numbers_of_the_platform_are_not_downloadable_from_the_domain(tmp_path):
    store = PanelStore(tmp_path)
    store.notes["usage"] = {"v": 1, "bots": 2, "clans": 3, "links": 7}
    res = serve(store, "/panel/usage.json")
    assert res.status == 403
    testo = res.body.decode()
    for name in ("bots", "clans", "links"):
        assert name not in testo, name
