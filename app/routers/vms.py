import json
import logging
import ssl
import urllib.request
import urllib.error
import urllib.parse
import base64
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

from app.credential_store import CredentialStore
from app.models import (
    AuthStatus,
    CloneRequest,
    CloneResponse,
    CreateEmptyVMRequest,
    DashboardStatus,
    FolderRequest,
    FolderVMs,
    JenkinsBuildInfo,
    JenkinsBuildRequest,
    JenkinsBuildResponse,
    JenkinsJobInfo,
    JenkinsJobRequest,
    JenkinsRebuildRequest,
    LoginRequest,
    LoginResponse,
    SnapshotRequest,
    SnapshotRestoreRequest,
    SnapshotResponse,
    TemplateInfo,
    VMActionRequest,
    VMActionResponse,
    VMInfo,
)
from app.vsphere_client import VSphereClient

logger = logging.getLogger(__name__)

_ssl_ctx: Optional[ssl.SSLContext] = None


def _get_ssl_ctx() -> ssl.SSLContext:
    global _ssl_ctx
    if _ssl_ctx is None:
        _ssl_ctx = ssl.create_default_context()
        _ssl_ctx.check_hostname = False
        _ssl_ctx.verify_mode = ssl.CERT_NONE
    return _ssl_ctx


def _jenkins_api(cfg: Any, endpoint: str, method: str = "GET") -> Any:
    url = f"{cfg.url.rstrip('/')}{endpoint}"
    credentials = base64.b64encode(f"{cfg.user}:{cfg.token}".encode()).decode()
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Basic {credentials}")
    resp = urllib.request.urlopen(req, context=_get_ssl_ctx(), timeout=15)
    if method == "GET":
        return json.loads(resp.read())
    return resp

router = APIRouter(prefix="/api", tags=["vms"])

_client: Optional[VSphereClient] = None
_store: Optional[CredentialStore] = None


def init_router(client: VSphereClient, store: CredentialStore) -> None:
    global _client, _store
    _client = client
    _store = store


@router.get("/auth/status", response_model=AuthStatus)
def auth_status() -> AuthStatus:
    assert _client is not None
    cfg = _client._config
    return AuthStatus(
        connected=_client.is_connected,
        server=cfg.vsphere.server,
        user=cfg.vsphere.user,
        has_saved_credentials=_store.has_credentials() if _store else False,
    )


@router.post("/auth/login", response_model=LoginResponse)
def login(req: LoginRequest) -> LoginResponse:
    assert _client is not None
    assert _store is not None
    username = req.username.strip()
    password = req.password.strip()
    if not username or not password:
        return LoginResponse(success=False, message="Username and password are required")

    _client._config.vsphere.user = username
    _client._config.vsphere.password = password
    try:
        _client.disconnect()
        _client.connect()
    except Exception as e:
        return LoginResponse(success=False, message=f"Login failed: {e}")

    _store.save_credentials(username, password)
    _client._cache_ts = 0
    return LoginResponse(success=True, message="Connected and credentials saved locally")


@router.get("/vms", response_model=List[VMInfo])
def list_vms(
    folder: Optional[str] = Query(None, description="Filter by folder path"),
    owner_email: Optional[str] = Query(None, description="Filter by owner email"),
    refresh: bool = Query(False, description="Force cache refresh"),
) -> List[VMInfo]:
    assert _client is not None
    try:
        vms = _client.get_all_vms(force_refresh=refresh)
    except Exception:
        return []
    if owner_email:
        vms = _client.filter_vms_by_owner_email(vms, owner_email)
    if folder:
        vms = [v for v in vms if v.folder == folder]
    return vms


@router.get("/folders", response_model=List[FolderVMs])
def list_folders(
    refresh: bool = Query(False, description="Force cache refresh"),
) -> List[FolderVMs]:
    assert _client is not None
    vms = _client.get_all_vms(force_refresh=refresh)
    folder_map: Dict[str, List[VMInfo]] = {}
    for vm in vms:
        folder_map.setdefault(vm.folder, []).append(vm)
    return [FolderVMs(folder=f, vms=v) for f, v in folder_map.items()]


@router.get("/status", response_model=DashboardStatus)
def status() -> DashboardStatus:
    assert _client is not None
    connected = _client.is_connected
    cfg = _client._config
    if connected:
        try:
            vms = _client.get_all_vms()
        except Exception:
            connected = False
            vms = []
    else:
        vms = []
    return DashboardStatus(
        connected=connected,
        server=cfg.vsphere.server,
        user=cfg.vsphere.user,
        folders=cfg.folders,
        vm_count=len(vms),
    )


@router.get("/config/folders")
def get_folders() -> Dict[str, Any]:
    assert _client is not None
    return {"folders": _client._config.folders}


@router.post("/config/folders")
def add_folder(req: FolderRequest) -> Dict[str, Any]:
    assert _client is not None
    folder = req.folder.strip().strip("/")
    if not folder:
        return {"success": False, "message": "Folder path is required"}
    if folder in _client._config.folders:
        return {"success": False, "message": "Folder already configured"}
    _client._config.folders.append(folder)
    _client._cache_ts = 0
    return {"success": True, "message": f"Folder added: {folder}"}


@router.delete("/config/folders")
def remove_folder(req: FolderRequest) -> Dict[str, Any]:
    assert _client is not None
    folder = req.folder.strip().strip("/")
    if folder in _client._config.folders:
        _client._config.folders.remove(folder)
        _client._cache_ts = 0
        return {"success": True, "message": f"Folder removed: {folder}"}
    return {"success": False, "message": "Folder not found in configuration"}


@router.get("/vsphere/browse")
def browse_vsphere_folders(
    path: str = Query("", description="Folder path to browse"),
) -> Dict[str, Any]:
    assert _client is not None
    try:
        items = _client.browse_folders(path)
        return {"success": True, "path": path, "items": items}
    except Exception as e:
        logger.exception("Browse folders failed")
        return {"success": False, "message": str(e), "items": []}


@router.get("/vsphere/search")
def search_vsphere_vms(
    query: str = Query(..., description="VM name search query"),
    limit: int = Query(50, description="Max results"),
) -> Dict[str, Any]:
    assert _client is not None
    if len(query) < 5:
        return {"success": False, "message": "Query too short (minimum 5 characters)", "results": []}
    try:
        results = _client.search_vms_global(query, limit=limit)
        return {"success": True, "results": results}
    except Exception as e:
        logger.exception("VM search failed")
        return {"success": False, "message": str(e), "results": []}


@router.get("/templates", response_model=List[TemplateInfo])
def list_templates(
    limit: int = Query(5, ge=1, le=50, description="Max templates to return"),
) -> List[TemplateInfo]:
    assert _client is not None
    try:
        return _client.list_templates(limit=limit)
    except Exception:
        return []


@router.post("/snapshot", response_model=SnapshotResponse)
def create_snapshot(req: SnapshotRequest) -> SnapshotResponse:
    assert _client is not None
    success, message, snap_name = _client.create_snapshot(req.vm_name, req.folder)
    return SnapshotResponse(success=success, message=message, snapshot_name=snap_name)


@router.get("/snapshots", response_model=List[str])
def list_snapshots(
    vm_name: str = Query(..., description="VM name"),
    folder: str = Query(..., description="VM folder path"),
) -> List[str]:
    assert _client is not None
    return _client.list_snapshots(vm_name, folder)


@router.post("/restore-snapshot", response_model=VMActionResponse)
def restore_snapshot(req: SnapshotRestoreRequest) -> VMActionResponse:
    assert _client is not None
    success, message = _client.restore_snapshot(
        req.vm_name,
        req.folder,
        snapshot_name=req.snapshot_name,
    )
    return VMActionResponse(success=success, message=message)


@router.post("/clone", response_model=CloneResponse)
def clone_vm(req: CloneRequest) -> CloneResponse:
    assert _client is not None
    success, message = _client.clone_vm(req.template_name, req.vm_name)
    return CloneResponse(success=success, message=message)


@router.post("/create-empty-vm", response_model=CloneResponse)
def create_empty_vm(req: CreateEmptyVMRequest) -> CloneResponse:
    assert _client is not None
    success, message = _client.create_empty_vm(
        req.vm_name,
        num_cpus=req.num_cpus,
        memory_gb=req.memory_gb,
        disk_gb=req.disk_gb,
    )
    return CloneResponse(success=success, message=message)


@router.post("/power-off", response_model=VMActionResponse)
def power_off(req: VMActionRequest) -> VMActionResponse:
    assert _client is not None
    success, message = _client.power_off(req.vm_name, req.folder)
    return VMActionResponse(success=success, message=message)


@router.post("/power-on", response_model=VMActionResponse)
def power_on(req: VMActionRequest) -> VMActionResponse:
    assert _client is not None
    success, message = _client.power_on(req.vm_name, req.folder)
    return VMActionResponse(success=success, message=message)


@router.post("/restart", response_model=VMActionResponse)
def restart(req: VMActionRequest) -> VMActionResponse:
    assert _client is not None
    success, message = _client.restart(req.vm_name, req.folder)
    return VMActionResponse(success=success, message=message)


@router.post("/delete", response_model=VMActionResponse)
def delete_vm(req: VMActionRequest) -> VMActionResponse:
    assert _client is not None
    success, message = _client.delete_vm(req.vm_name, req.folder)
    return VMActionResponse(success=success, message=message)


_JENKINS_JOB = "build_and_deploy_private_portal"


@router.get("/jenkins/saved-jobs")
def get_saved_jenkins_jobs() -> Dict[str, Any]:
    if _client is None:
        return {"jobs": []}
    return {"jobs": _client._config.jenkins.jobs}


@router.post("/jenkins/saved-jobs")
def add_saved_jenkins_job(req: JenkinsJobRequest) -> Dict[str, Any]:
    if _client is None:
        return {"success": False, "message": "Not initialized"}
    job_name = req.job_name.strip()
    if not job_name:
        return {"success": False, "message": "Job name is required"}
    if job_name not in _client._config.jenkins.jobs:
        _client._config.jenkins.jobs.append(job_name)
    return {"success": True, "message": f"Job added: {job_name}"}


@router.delete("/jenkins/saved-jobs")
def remove_saved_jenkins_job(req: JenkinsJobRequest) -> Dict[str, Any]:
    if _client is None:
        return {"success": False, "message": "Not initialized"}
    job_name = req.job_name.strip()
    if job_name in _client._config.jenkins.jobs:
        _client._config.jenkins.jobs.remove(job_name)
        return {"success": True, "message": f"Job removed: {job_name}"}
    return {"success": False, "message": "Job not found"}


@router.get("/jenkins/search-jobs", response_model=List[JenkinsJobInfo])
def search_jenkins_jobs(
    query: str = Query("", description="Filter jobs by name"),
) -> List[JenkinsJobInfo]:
    if _client is None:
        return []
    cfg = _client._config.jenkins
    if not cfg.user or not cfg.token:
        return []

    try:
        data = _jenkins_api(cfg, "/api/json?tree=jobs[name,url,color]")
    except Exception:
        logger.exception("Failed to fetch Jenkins jobs")
        return []

    jobs = data.get("jobs", [])
    q = query.strip().lower()
    results = []
    for j in jobs:
        name = j.get("name", "")
        if q and q not in name.lower():
            continue
        results.append(JenkinsJobInfo(
            name=name,
            url=j.get("url", ""),
            color=j.get("color", ""),
        ))
    results.sort(key=lambda j: j.name.lower())
    return results


def _normalize_identity(value: str) -> str:
    """Normalize Jenkins user identity for tolerant comparisons."""
    return (value or "").strip().lower()


def _identity_variants(value: str) -> set[str]:
    raw = _normalize_identity(value)
    if not raw:
        return set()
    variants = {raw}
    if "@" in raw:
        variants.add(raw.split("@", 1)[0])
    return variants


def _build_identity_set(cfg_user: str, me_data: Dict[str, Any]) -> set[str]:
    identities = set()
    identities.update(_identity_variants(cfg_user))
    identities.update(_identity_variants(me_data.get("id", "")))
    identities.update(_identity_variants(me_data.get("fullName", "")))
    identities.update(_identity_variants(me_data.get("displayName", "")))
    return {x for x in identities if x}


def _matches_identity(triggered_by: str, identities: set[str]) -> bool:
    candidate_variants = _identity_variants(triggered_by)
    if not candidate_variants:
        return False
    for candidate in candidate_variants:
        if candidate in identities:
            return True
    return False


@router.get("/jenkins/job/params")
def get_jenkins_job_params(
    job_name: str = Query(_JENKINS_JOB, description="Jenkins job name"),
) -> Dict[str, Any]:
    assert _client is not None
    cfg = _client._config.jenkins
    if not cfg.user or not cfg.token:
        return {"success": False, "message": "Jenkins credentials not configured", "parameters": []}

    safe_job = urllib.parse.quote(job_name, safe="")
    try:
        job_data = _jenkins_api(cfg, f"/job/{safe_job}/api/json")
    except urllib.error.HTTPError as e:
        return {"success": False, "message": f"Jenkins error: HTTP {e.code}", "parameters": []}
    except Exception as e:
        return {"success": False, "message": f"Failed to fetch job info: {e}", "parameters": []}

    params: List[Dict[str, Any]] = []
    for prop in job_data.get("property", []):
        for param_def in prop.get("parameterDefinitions", []):
            default_val = param_def.get("defaultParameterValue", {})
            raw_value = default_val.get("value")
            if isinstance(raw_value, bool):
                default_value = "true" if raw_value else "false"
            elif raw_value is not None:
                default_value = str(raw_value)
            else:
                default_value = ""
            params.append({
                "name": param_def.get("name", ""),
                "type": param_def.get("type", "StringParameterDefinition"),
                "description": param_def.get("description", ""),
                "default_value": default_value,
                "choices": param_def.get("choices"),
            })

    return {"success": True, "parameters": params, "job_name": job_name}


@router.post("/jenkins/build", response_model=JenkinsBuildResponse)
def trigger_jenkins_build(req: JenkinsBuildRequest) -> JenkinsBuildResponse:
    assert _client is not None
    cfg = _client._config.jenkins
    if not cfg.user or not cfg.token:
        return JenkinsBuildResponse(
            success=False,
            message="Jenkins credentials not configured. Set them in config.yaml or ~/.jenkins-config",
        )

    job_name = req.job_name or _JENKINS_JOB
    safe_job = urllib.parse.quote(job_name, safe="")

    try:
        if req.parameters:
            query = urllib.parse.urlencode(req.parameters)
            endpoint = f"/job/{safe_job}/buildWithParameters?{query}"
        else:
            endpoint = f"/job/{safe_job}/build"
        _jenkins_api(cfg, endpoint, method="POST")
        return JenkinsBuildResponse(
            success=True,
            message=f"Build triggered for {job_name}",
        )
    except urllib.error.HTTPError as e:
        return JenkinsBuildResponse(success=False, message=f"Jenkins error: HTTP {e.code}")
    except Exception as e:
        logger.exception("Jenkins build trigger failed")
        return JenkinsBuildResponse(success=False, message=f"Failed to reach Jenkins: {e}")


@router.get("/jenkins/builds", response_model=List[JenkinsBuildInfo])
def list_jenkins_builds(
    job_name: str = Query(_JENKINS_JOB, description="Jenkins job name"),
    limit: int = Query(10, description="Max builds to return"),
) -> List[JenkinsBuildInfo]:
    assert _client is not None
    cfg = _client._config.jenkins
    if not cfg.user or not cfg.token:
        return []

    safe_job = urllib.parse.quote(job_name, safe="")
    try:
        job_data = _jenkins_api(cfg, f"/job/{safe_job}/api/json")
    except Exception:
        logger.exception("Failed to fetch Jenkins job info")
        return []

    try:
        me_data = _jenkins_api(cfg, "/me/api/json")
    except Exception:
        me_data = {}

    build_refs = job_data.get("builds", [])[:20]
    identity_set = _build_identity_set(cfg.user, me_data)
    results: List[JenkinsBuildInfo] = []

    for ref in build_refs:
        if len(results) >= limit:
            break
        num = ref.get("number")
        if not num:
            continue
        try:
            b = _jenkins_api(cfg, f"/job/{safe_job}/{num}/api/json")
        except Exception:
            continue

        triggered_by = ""
        for action in b.get("actions", []):
            for cause in action.get("causes", []):
                uid = cause.get("userId") or cause.get("userName") or ""
                if uid:
                    triggered_by = uid
                    break
            if triggered_by:
                break

        if not _matches_identity(triggered_by, identity_set):
            continue

        branch = ""
        vm_names = ""
        for action in b.get("actions", []):
            for param in action.get("parameters", []):
                if param.get("name") == "BRANCH_NAME":
                    branch = param.get("value", "")
                elif param.get("name") == "VM_NAMES":
                    vm_names = param.get("value", "")

        status = b.get("result") or ("BUILDING" if b.get("building") else "UNKNOWN")
        duration = b.get("duration", 0)

        results.append(JenkinsBuildInfo(
            job_name=job_name,
            number=num,
            status=status,
            branch=branch,
            vm_names=vm_names,
            url=b.get("url", ""),
            timestamp=b.get("timestamp"),
            duration_s=duration // 1000 if duration else None,
        ))

    return results


@router.post("/jenkins/rebuild", response_model=JenkinsBuildResponse)
def rebuild_jenkins_build(req: JenkinsRebuildRequest) -> JenkinsBuildResponse:
    assert _client is not None
    cfg = _client._config.jenkins
    if not cfg.user or not cfg.token:
        return JenkinsBuildResponse(
            success=False,
            message="Jenkins credentials not configured",
        )

    safe_job = urllib.parse.quote(req.job_name, safe="")

    try:
        build_data = _jenkins_api(cfg, f"/job/{safe_job}/{req.build_number}/api/json")
    except Exception as e:
        return JenkinsBuildResponse(
            success=False,
            message=f"Failed to fetch build #{req.build_number}: {e}",
        )

    params: Dict[str, str] = {}
    for action in build_data.get("actions", []):
        for param in action.get("parameters", []):
            name = param.get("name", "")
            value = param.get("value")
            if name:
                params[name] = str(value) if value is not None else ""

    try:
        if params:
            query = urllib.parse.urlencode(params)
            endpoint = f"/job/{safe_job}/buildWithParameters?{query}"
        else:
            endpoint = f"/job/{safe_job}/build"
        _jenkins_api(cfg, endpoint, method="POST")
        return JenkinsBuildResponse(
            success=True,
            message=f"Rebuild triggered for {req.job_name} (from #{req.build_number})",
        )
    except urllib.error.HTTPError as e:
        return JenkinsBuildResponse(success=False, message=f"Jenkins error: HTTP {e.code}")
    except Exception as e:
        logger.exception("Jenkins rebuild failed")
        return JenkinsBuildResponse(success=False, message=f"Failed to reach Jenkins: {e}")
