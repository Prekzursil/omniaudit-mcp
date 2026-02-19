from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet


@dataclass(slots=True)
class EnvelopeEncryption:
    master_key_file: Path

    def __post_init__(self) -> None:
        self.master_key_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.master_key_file.exists():
            self.master_key_file.write_bytes(Fernet.generate_key())

    def _master_cipher(self) -> Fernet:
        return Fernet(self.master_key_file.read_bytes())

    def encrypt_secret(self, value: str) -> str:
        data_key = Fernet.generate_key()
        payload_cipher = Fernet(data_key)
        ciphertext = payload_cipher.encrypt(value.encode("utf-8"))
        encrypted_data_key = self._master_cipher().encrypt(data_key)
        packed = {
            "encrypted_data_key": base64.urlsafe_b64encode(encrypted_data_key).decode("ascii"),
            "ciphertext": base64.urlsafe_b64encode(ciphertext).decode("ascii"),
        }
        return base64.urlsafe_b64encode(
            json.dumps(packed, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).decode("ascii")

    def decrypt_secret(self, token: str) -> str:
        decoded = json.loads(base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8"))
        encrypted_data_key = base64.urlsafe_b64decode(decoded["encrypted_data_key"].encode("ascii"))
        ciphertext = base64.urlsafe_b64decode(decoded["ciphertext"].encode("ascii"))
        data_key = self._master_cipher().decrypt(encrypted_data_key)
        return Fernet(data_key).decrypt(ciphertext).decode("utf-8")
