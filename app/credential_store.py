import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_VSPHERE = "vsphere"
_JENKINS = "jenkins"


class CredentialStore:
    """Encrypt and store secrets for multiple services on the local machine.

    All credentials live in a single Fernet-encrypted JSON blob at
    ``~/.dashboard-x/credentials.enc``.  The encryption key is stored
    beside it in ``secret.key`` (both chmod 600).

    Internal format::

        {
            "vsphere":  {"username": "...", "password": "..."},
            "jenkins":  {"user": "...", "token": "..."}
        }
    """

    def __init__(self) -> None:
        base_dir = os.environ.get("VSPHERE_DASH_DATA_DIR")
        if base_dir:
            self._base = Path(base_dir)
        else:
            self._base = Path.home() / ".dashboard-x"
        self._key_file = self._base / "secret.key"
        self._cred_file = self._base / "credentials.enc"

    # -- whole-store I/O ---------------------------------------------------

    def _load_store(self) -> Dict[str, Any]:
        if not self._cred_file.exists() or not self._key_file.exists():
            return {}
        try:
            fernet = Fernet(self._load_or_create_key())
            raw = fernet.decrypt(self._cred_file.read_bytes())
            data = json.loads(raw.decode("utf-8"))
        except (InvalidToken, json.JSONDecodeError):
            logger.warning("Credential store corrupted – starting fresh")
            return {}

        # Backward compat: old format was a flat {"username": ..., "password": ...}
        if _VSPHERE not in data and _JENKINS not in data and "username" in data:
            data = {_VSPHERE: data}
        return data

    def _save_store(self, data: Dict[str, Any]) -> None:
        self._base.mkdir(parents=True, exist_ok=True)
        key = self._load_or_create_key()
        payload = json.dumps(data).encode("utf-8")
        self._cred_file.write_bytes(Fernet(key).encrypt(payload))
        self._set_owner_only(self._cred_file)

    # -- vSphere credentials -----------------------------------------------

    def has_credentials(self) -> bool:
        return self.load_credentials() is not None

    def load_credentials(self) -> Optional[Tuple[str, str]]:
        entry = self._load_store().get(_VSPHERE, {})
        username = str(entry.get("username", "")).strip()
        password = str(entry.get("password", "")).strip()
        if not username or not password:
            return None
        return username, password

    def save_credentials(self, username: str, password: str) -> None:
        data = self._load_store()
        data[_VSPHERE] = {
            "username": username.strip(),
            "password": password.strip(),
        }
        self._save_store(data)

    # -- Jenkins credentials -----------------------------------------------

    def load_jenkins(self) -> Optional[Tuple[str, str]]:
        entry = self._load_store().get(_JENKINS, {})
        user = str(entry.get("user", "")).strip()
        token = str(entry.get("token", "")).strip()
        if not user or not token:
            return None
        return user, token

    def save_jenkins(self, user: str, token: str) -> None:
        data = self._load_store()
        data[_JENKINS] = {"user": user.strip(), "token": token.strip()}
        self._save_store(data)

    # -- key management ----------------------------------------------------

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
            pass
