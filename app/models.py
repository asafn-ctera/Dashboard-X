from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel


class VMInfo(BaseModel):
    name: str
    folder: str
    portal_version: Optional[str] = None
    creation_date: Optional[datetime] = None
    ip_address: Optional[str] = None
    connect_url: Optional[str] = None
    status: str  # poweredOn, poweredOff, suspended


class FolderVMs(BaseModel):
    folder: str
    vms: List[VMInfo]


class DashboardStatus(BaseModel):
    connected: bool
    server: str
    user: str
    folders: List[str]
    vm_count: int


class AuthStatus(BaseModel):
    connected: bool
    server: str
    user: str
    has_saved_credentials: bool


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    success: bool
    message: str


class TemplateInfo(BaseModel):
    name: str
    folder: str
    portal_version: Optional[str] = None
    creation_date: Optional[datetime] = None


class SnapshotRequest(BaseModel):
    vm_name: str
    folder: str


class SnapshotRestoreRequest(BaseModel):
    vm_name: str
    folder: str
    snapshot_name: Optional[str] = None


class SnapshotResponse(BaseModel):
    success: bool
    message: str
    snapshot_name: Optional[str] = None


class CloneRequest(BaseModel):
    template_name: str
    vm_name: str


class CloneResponse(BaseModel):
    success: bool
    message: str
    task_id: Optional[str] = None


class VMActionRequest(BaseModel):
    vm_name: str
    folder: str


class VMActionResponse(BaseModel):
    success: bool
    message: str


class CreateEmptyVMRequest(BaseModel):
    vm_name: str
    num_cpus: int = 4
    memory_gb: int = 8
    disk_gb: int = 100


class FolderRequest(BaseModel):
    folder: str


class JenkinsBuildRequest(BaseModel):
    job_name: str = "build_and_deploy_private_portal"
    parameters: Dict[str, str] = {}


class JenkinsBuildResponse(BaseModel):
    success: bool
    message: str


class JenkinsBuildInfo(BaseModel):
    job_name: str = ""
    number: int
    status: str  # SUCCESS, FAILURE, BUILDING, ABORTED, UNSTABLE
    branch: str
    vm_names: str
    url: str
    timestamp: Optional[int] = None
    duration_s: Optional[int] = None


class JenkinsRebuildRequest(BaseModel):
    job_name: str
    build_number: int


class JenkinsJobRequest(BaseModel):
    job_name: str


class JenkinsJobInfo(BaseModel):
    name: str
    url: str
    color: str = ""
