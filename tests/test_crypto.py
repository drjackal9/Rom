from clashbot.crypto import Vault


def test_vault_roundtrip_and_key_persistence(tmp_path):
    vault = Vault(tmp_path)
    blob = vault.encrypt_json({"chat_id": -100123, "tag": "#ABC"}, "clan:clan-abc123")
    assert vault.decrypt_json(blob, "clan:clan-abc123") == {"chat_id": -100123, "tag": "#ABC"}
    again = Vault(tmp_path)
    assert again.key_id == vault.key_id
    assert again.decrypt_json(blob, "clan:clan-abc123")["tag"] == "#ABC"
    assert vault.blind("chat", -100123) == again.blind("chat", -100123)
    assert vault.blind("chat", -100123) != vault.blind("chat", -100124)
    assert Vault.alias("clan").startswith("clan-") and len(Vault.alias("sec")) == 10


def test_wrong_aad_fails(tmp_path):
    vault = Vault(tmp_path)
    blob = vault.encrypt("segreto", "secret:sec-1")
    try:
        vault.decrypt(blob, "secret:sec-2")
    except Exception:
        return
    raise AssertionError("aad diverso deve fallire")
