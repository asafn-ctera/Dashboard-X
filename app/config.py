import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union

import yaml

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


def load_config(path: Union[str, Path, None] = None) -> AppConfig:
    if path is not None:
        config_path = Path(path)
    else:
        config_path = _resolve_config_path()

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    vs = raw.get("vsphere", {})
    dash = raw.get("dashboard", {})

    clone_raw = raw.get("clone", {})
    jenkins_raw = raw.get("jenkins", {})

    default_jobs = ["build_and_deploy_private_portal"]
    jenkins_cfg = JenkinsConfig(
        url=jenkins_raw.get("url", "https://jenkins.ctera.dev"),
        user=jenkins_raw.get("user", ""),
        token=jenkins_raw.get("token", ""),
        jobs=jenkins_raw.get("jobs", default_jobs),
    )
    if not jenkins_cfg.user or not jenkins_cfg.token:
        _load_jenkins_dotfile(jenkins_cfg)

    return AppConfig(
        vsphere=VSphereConfig(
            server=vs["server"],
            user=vs.get("user", ""),
            password=vs.get("password", ""),
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


def _load_jenkins_dotfile(cfg: JenkinsConfig) -> None:
    dotfile = Path.home() / ".jenkins-config"
    if not dotfile.exists():
        return
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
            cfg.user = value
        elif key == "JENKINS_TOKEN" and value:
            cfg.token = value


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
