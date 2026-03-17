import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union

import yaml

from app.credential_store import CredentialStore

logger = logging.getLogger(__name__)

_CONFIG_SEARCH_PATHS = [
    Path("config.yaml"),
    Path(__file__).resolve().parent.parent / "config.yaml",
]


@dataclass
class VSphereConfig:
    server: str
    user: str
    password: str
    allow_unverified_ssl: bool = True


@dataclass
class DashboardConfig:
    port: int = 8585
    cache_ttl_seconds: int = 60
    connect_url_scheme: str = "https"


@dataclass
class CloneDefaults:
    template_folder: str = "CTERA/DevProd/QA/Portal_Templates"
    reference_vm_path: str = "Technical Teams/Engineering/AsafN/Thanks_Niv-O_8.2"
    target_folder: str = "Technical Teams/Engineering/Portal Sandbox/AsafN"


@dataclass
class JenkinsConfig:
    url: str = "https://jenkins.ctera.dev"
    user: str = ""
    token: str = ""
    jobs: List[str] = field(default_factory=lambda: ["build_and_deploy_private_portal"])


@dataclass
class AppConfig:
    vsphere: VSphereConfig
    folders: List[str] = field(default_factory=list)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
    clone: CloneDefaults = field(default_factory=CloneDefaults)
    jenkins: JenkinsConfig = field(default_factory=JenkinsConfig)


def load_config(
    path: Union[str, Path, None] = None,
    store: Optional[CredentialStore] = None,
) -> AppConfig:
    if path is not None:
        config_path = Path(path)
    else:
        config_path = _resolve_config_path()

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    if store is None:
        store = CredentialStore()

    vs = raw.get("vsphere", {})
    dash = raw.get("dashboard", {})
    clone_raw = raw.get("clone", {})
    jenkins_raw = raw.get("jenkins", {})

    # -- vSphere credentials -----------------------------------------------
    yaml_user = vs.get("user", "")
    yaml_pass = vs.get("password", "")

    saved_vs = store.load_credentials()
    if saved_vs:
        vs_user, vs_pass = saved_vs
    else:
        vs_user, vs_pass = yaml_user, yaml_pass

    if yaml_pass:
        _migrate_vsphere_secrets(store, yaml_user, yaml_pass, config_path, raw)

    # -- Jenkins credentials -----------------------------------------------
    default_jobs = ["build_and_deploy_private_portal"]
    jenkins_cfg = JenkinsConfig(
        url=jenkins_raw.get("url", "https://jenkins.ctera.dev"),
        user="",
        token="",
        jobs=jenkins_raw.get("jobs", default_jobs),
    )

    saved_jk = store.load_jenkins()
    if saved_jk:
        jenkins_cfg.user, jenkins_cfg.token = saved_jk

    yaml_jk_user = jenkins_raw.get("user", "")
    yaml_jk_token = jenkins_raw.get("token", "")
    if yaml_jk_token:
        _migrate_jenkins_secrets(
            store, yaml_jk_user, yaml_jk_token, config_path, raw,
        )
        if not saved_jk:
            jenkins_cfg.user = yaml_jk_user
            jenkins_cfg.token = yaml_jk_token

    if not jenkins_cfg.user or not jenkins_cfg.token:
        _load_jenkins_dotfile(jenkins_cfg, store)

    return AppConfig(
        vsphere=VSphereConfig(
            server=vs["server"],
            user=vs_user,
            password=vs_pass,
            allow_unverified_ssl=vs.get("allow_unverified_ssl", True),
        ),
        folders=raw.get("folders", []),
        dashboard=DashboardConfig(
            port=dash.get("port", 8585),
            cache_ttl_seconds=dash.get("cache_ttl_seconds", 60),
            connect_url_scheme=dash.get("connect_url_scheme", "https"),
        ),
        clone=CloneDefaults(
            template_folder=clone_raw.get("template_folder", "CTERA/DevProd/QA/Portal_Templates"),
            reference_vm_path=clone_raw.get("reference_vm_path", "Technical Teams/Engineering/AsafN/Thanks_Niv-O_8.2"),
            target_folder=clone_raw.get("target_folder", "Technical Teams/Engineering/Portal Sandbox/AsafN"),
        ),
        jenkins=jenkins_cfg,
    )


def _migrate_vsphere_secrets(
    store: CredentialStore,
    user: str,
    password: str,
    config_path: Path,
    raw: dict,
) -> None:
    """Move plaintext vSphere password into the encrypted store and scrub
    it from config.yaml so it never sits on disk unprotected."""
    store.save_credentials(user, password)
    logger.info("Migrated vSphere credentials to encrypted store")
    raw.setdefault("vsphere", {})["password"] = ""
    _rewrite_config(config_path, raw)


def _migrate_jenkins_secrets(
    store: CredentialStore,
    user: str,
    token: str,
    config_path: Path,
    raw: dict,
) -> None:
    store.save_jenkins(user, token)
    logger.info("Migrated Jenkins credentials to encrypted store")
    jk = raw.setdefault("jenkins", {})
    jk["user"] = ""
    jk["token"] = ""
    _rewrite_config(config_path, raw)


def _rewrite_config(config_path: Path, raw: dict) -> None:
    try:
        with open(config_path, "w") as f:
            yaml.safe_dump(raw, f, default_flow_style=False, sort_keys=False)
        logger.info("Scrubbed plaintext secrets from %s", config_path)
    except OSError:
        logger.warning("Could not rewrite %s – remove secrets manually", config_path)


def _load_jenkins_dotfile(cfg: JenkinsConfig, store: CredentialStore) -> None:
    dotfile = Path.home() / ".jenkins-config"
    if not dotfile.exists():
        return
    user = ""
    token = ""
    for line in dotfile.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        key = key.strip()
        if key == "JENKINS_URL" and value:
            cfg.url = value
        elif key == "JENKINS_USER" and value:
            user = value
        elif key == "JENKINS_TOKEN" and value:
            token = value

    if user and token:
        store.save_jenkins(user, token)
        cfg.user = user
        cfg.token = token
        logger.info("Migrated Jenkins credentials from ~/.jenkins-config to encrypted store")


def _resolve_config_path() -> Path:
    env = os.environ.get("VSPHERE_DASH_CONFIG")
    if env:
        return Path(env)
    for p in _CONFIG_SEARCH_PATHS:
        if p.exists():
            return p
    raise FileNotFoundError(
        "config.yaml not found. Copy config.yaml.example to config.yaml and fill in your credentials."
    )
