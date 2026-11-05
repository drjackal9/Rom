import hashlib

from clashbot.web import http, static


def test_the_manifest_hashes_every_file_and_ignores_the_hash_in_the_url():
    found = static.manifest()
    assert len(found["hash"]) == 12 and "vendor/htm-preact-standalone.module.js" in found["files"]
    assert static.url_for("app/main.js") == f"/static/{found['hash']}/app/main.js"
    assert static.read("vendor/htm-preact-standalone.module.js") == found["files"][
        "vendor/htm-preact-standalone.module.js"]


def test_paths_that_escape_or_are_unknown_are_refused():
    assert static.read("../app.py") is None
    assert static.read("/etc/passwd") is None
    assert static.read("vendor/nope.js") is None


def test_the_vendored_library_matches_its_recorded_hash():
    rows = [line.split("\t")
            for line in (static.ROOT / "vendor" / "VERSIONS").read_text().splitlines() if line]
    assert rows, "VERSIONS vuoto"
    for name, package, digest, licence, url in rows:
        assert name.startswith(("vendor/", "fonts/")), name
        assert hashlib.sha256((static.ROOT / name).read_bytes()).hexdigest() == digest
        assert package.split("@")[0] in ("htm", "preact", "barlow", "barlow-semi-condensed")
        assert licence in ("MIT", "Apache-2.0", "OFL-1.1")
        assert url.startswith("https://")


def test_the_bundle_exports_what_the_app_needs():
    body = static.read("vendor/htm-preact-standalone.module.js").decode()
    clause = body.rsplit("export{", 1)[1].split("}")[0]
    names = {part.split(" as ")[-1].strip() for part in clause.split(",")}
    assert {"h", "html", "render", "Component", "useState", "useEffect", "useRef", "useMemo",
            "useCallback", "useContext"} <= names


def test_neither_the_manifest_nor_the_hash_carry_the_bookkeeping_files():
    found = static.manifest()
    assert "vendor/VERSIONS" not in found["files"] and "package.json" not in found["files"]
    assert "vendor/LICENSE-htm" not in found["files"]
    assert static.read("vendor/VERSIONS") is None
    assert not [name for name in found["files"] if name.rsplit("/", 1)[-1] in static.SKIP]
    assert static.read("README.md") is None and static.read("app/DEPS.json") is None


def test_kinds():
    assert static.kind_of("app/main.js") == http.SCRIPT
    assert static.kind_of("x.svg") == "image/svg+xml"
    assert static.kind_of("x.css") == "text/css; charset=utf-8"
    assert static.kind_of("x.txt") == http.TEXT


def test_every_module_of_the_app_is_named_up_front():
    names = static.app_modules()
    assert names == sorted(names) and len(names) == len(set(names))
    assert "app/main.js" in names and "app/ui.js" in names
    assert "vendor/htm-preact-standalone.module.js" in names
    assert all(name.endswith(".js") for name in names)
    assert {name for name in static.manifest()["files"]
            if name.endswith(".js")} == set(names) | {static.BOOT}


def test_the_boot_script_is_served_but_is_not_a_module():
    assert static.BOOT in static.manifest()["files"]
    assert static.BOOT not in static.app_modules()
    assert b"import " not in static.read(static.BOOT)


def test_the_manifest_only_carries_what_the_browser_loads():
    loaded = (".js", ".css", ".woff2", ".svg")
    found = static.manifest()
    assert found["files"]
    assert not [name for name in found["files"] if not name.endswith(loaded)]
    for name in found["files"]:
        assert static.kind_of(name) != http.TEXT, name
