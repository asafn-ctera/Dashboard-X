import json
import os
from pathlib import Path
from typing import Optional, Tuple

from cryptography.fernet import Fernet


class CredentialStore:
    """Store vSphere credentials encrypted on local machine."""

    def __init__(self) -> None:
        base_dir = os.environ.get("VSPHERE_DASH_DATA_DIR")
        if base_dir:
            self._base = Path(base_dir)
        else:
            self._base = Path.home() / ".dashboard-x"
        self._key_file = self._base / "secret.key"
        self._cred_file = self._base / "credentials.enc"

    def has_credentials(self) -> bool:
        return self._cred_file.exists() and self._key_file.exists()

    def load_credentials(self) -> Optional[Tuple[str, str]]:
        if not self.has_credentials():
            return None
        fernet = Fernet(self._load_or_create_key())
        raw = self._cred_file.read_bytes()
        data = json.loads(fernet.decrypt(raw).decode("utf-8"))
        username = str(data.get("username", "")).strip()
        password = str(data.get("password", "")).strip()
        if not username or not password:
            return None
        return username, password

    def save_credentials(self, username: str, password: str) -> None:
        self._base.mkdir(parents=True, exist_ok=True)
        key = self._load_or_create_key()
        payload = json.dumps(
            {"username": username.strip(), "password": password.strip()}
        ).encode("utf-8")
        token = Fernet(key).encrypt(payload)
        self._cred_file.write_bytes(token)
        self._set_owner_only(self._cred_file)

    def _load_or_create_key(self) -> bytes:
        self._base.mkdir(parents=True, exist_ok=True)
        if self._key_file.exists():
            return self._key_file.read_bytes()
        key = Fernet.generate_key()
        self._key_file.write_bytes(key)
        self._set_owner_only(self._key_file)
        return key

    @staticmethod
    def _set_owner_only(path: Path) -> None:
        try:
            path.chmod(0o600)
        except Exception:
            # Best-effort on systems that do not support chmod semantics.
            pass
