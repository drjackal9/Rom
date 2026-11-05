import base64
import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_DIR = "/keys"
MASTER = "master.key"


class Vault:
    def __init__(self, key_dir=KEY_DIR, create=True):
        self.dir = Path(key_dir)
        self.key = self._load_or_create(create)
        self.key_id = hashlib.sha256(self.key).hexdigest()[:12]
        self.aead = AESGCM(self.key)

    def _load_or_create(self, create=True):
        path = self.dir / MASTER
        if path.exists():
            return base64.b64decode(path.read_text().strip())
        if not create:
            raise FileNotFoundError("chiave master non disponibile")
        key = AESGCM.generate_key(bit_length=256)
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(base64.b64encode(key).decode())
        os.chmod(tmp, 0o600)
        tmp.replace(path)
        return key

    def encrypt(self, plaintext, aad):
        if isinstance(plaintext, str):
            plaintext = plaintext.encode()
        nonce = os.urandom(12)
        return nonce + self.aead.encrypt(nonce, plaintext, aad.encode())

    def decrypt(self, blob, aad):
        blob = bytes(blob)
        return self.aead.decrypt(blob[:12], blob[12:], aad.encode())

    def encrypt_json(self, obj, aad):
        return self.encrypt(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), aad)

    def decrypt_json(self, blob, aad):
        return json.loads(self.decrypt(blob, aad).decode())

    def blind(self, label, value):
        return hmac.new(self.key, f"{label}:{value}".encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def alias(prefix):
        return f"{prefix}-{secrets.token_hex(3)}"
