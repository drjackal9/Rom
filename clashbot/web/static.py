import hashlib
from pathlib import Path

from . import http

ROOT = Path(__file__).parent / "static"
STATIC_MAX_AGE = 31536000
KINDS = {".js": http.SCRIPT, ".css": http.CSS, ".svg": "image/svg+xml", ".json": http.JSON,
         ".woff2": http.FONT}
SKIP = ("VERSIONS", "package.json", "README.md", "DEPS.json", "OWNERS.json", "OFL.txt")
BOOT = "app/boot.js"
FOUND = {}


def manifest():
    if not FOUND:
        files = {}
        for path in sorted(ROOT.rglob("*")):
            if path.is_file() and path.name not in SKIP and not path.name.startswith("LICENSE"):
                files[path.relative_to(ROOT).as_posix()] = path.read_bytes()
        digest = hashlib.sha256()
        for name, body in files.items():
            digest.update(name.encode())
            digest.update(body)
        FOUND.update({"hash": digest.hexdigest()[:12], "files": files})
    return FOUND


def app_modules():
    return sorted(name for name in manifest()["files"]
                  if name.endswith(".js") and name != BOOT
                  and (name.startswith("app/") or name.endswith(".module.js")))


def url_for(name):
    return f"/static/{manifest()['hash']}/{name}"


def read(name):
    if not name or name.startswith("/") or ".." in name.split("/"):
        return None
    return manifest()["files"].get(name)


def kind_of(name):
    return KINDS.get(Path(name).suffix, http.TEXT)
