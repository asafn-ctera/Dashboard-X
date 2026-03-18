import atexit
import logging
import re
import ssl
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from pyVim.connect import Disconnect, SmartConnect
from pyVmomi import vim

from app.config import AppConfig
from app.models import TemplateInfo, VMInfo

logger = logging.getLogger(__name__)

_VERSION_PATTERN = re.compile(r"(\d+\.\d+(?:\.\d+[\w.-]*)?)")


class VSphereClient:
    """Manages the connection to vCenter and queries VMs from configured folders."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._si: Optional[Any] = None
        self._cache: List[VMInfo] = []
        self._cache_ts: float = 0

    # -- connection --------------------------------------------------------

    def connect(self) -> None:
        vs = self._config.vsphere
        if not vs.user or not vs.password:
            raise RuntimeError("Missing vSphere credentials. Please log in.")
        ctx: Optional[ssl.SSLContext] = None
        if vs.allow_unverified_ssl:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        logger.info("Connecting to vCenter %s as %s …", vs.server, vs.user)
        self._si = SmartConnect(
            host=vs.server,
            user=vs.user,
            pwd=vs.password,
            sslContext=ctx,
        )
        atexit.register(Disconnect, self._si)
        logger.info("Connected to vCenter %s", vs.server)

    def disconnect(self) -> None:
        if self._si:
            Disconnect(self._si)
            self._si = None

    @property
    def is_connected(self) -> bool:
        if self._si is None:
            return False
        try:
            self._si.CurrentTime()
            return True
        except Exception:
            return False

    def _ensure_connected(self) -> None:
        if not self.is_connected:
            self.connect()

    # -- querying ----------------------------------------------------------

    def get_all_vms(self, *, force_refresh: bool = False) -> List[VMInfo]:
        ttl = self._config.dashboard.cache_ttl_seconds
        if not force_refresh and self._cache and (time.time() - self._cache_ts) < ttl:
            return self._cache

        self._ensure_connected()
        vms: list[VMInfo] = []
        for folder_path in self._config.folders:
            vms.extend(self._vms_in_folder(folder_path))

        self._cache = vms
        self._cache_ts = time.time()
        return vms

    # -- browsing & searching ----------------------------------------------

    def browse_folders(self, path: str = "") -> List[Dict[str, Any]]:
        """List child folders and datacenters at the given inventory path."""
        self._ensure_connected()
        content = self._si.RetrieveContent()
        current: Any = content.rootFolder
        if path:
            for part in (p for p in path.split("/") if p):
                found = False
                for child in self._get_child_entities(current):
                    if child.name == part:
                        current = child
                        found = True
                        break
                if not found:
                    return []

        items: List[Dict[str, Any]] = []
        for child in self._get_child_entities(current):
            child_path = f"{path}/{child.name}".strip("/")
            if isinstance(child, vim.Folder):
                vm_count = sum(
                    1 for e in child.childEntity
                    if isinstance(e, vim.VirtualMachine)
                )
                has_subfolders = any(
                    isinstance(e, (vim.Folder, vim.Datacenter))
                    for e in child.childEntity
                )
                items.append({
                    "name": child.name,
                    "type": "folder",
                    "path": child_path,
                    "vm_count": vm_count,
                    "has_children": has_subfolders,
                })
            elif isinstance(child, vim.Datacenter):
                items.append({
                    "name": child.name,
                    "type": "datacenter",
                    "path": child_path,
                    "vm_count": 0,
                    "has_children": True,
                })
        items.sort(key=lambda x: x["name"].lower())
        return items

    def search_vms_global(
        self, query: str, limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Search for VMs by name across the entire vCenter inventory."""
        self._ensure_connected()
        content = self._si.RetrieveContent()
        container = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.VirtualMachine], True,
        )
        query_lower = query.lower()
        results: List[Dict[str, Any]] = []
        try:
            for vm in container.view:
                try:
                    if vm.config and vm.config.template:
                        continue
                    name = vm.name
                    if query_lower not in name.lower():
                        continue
                    folder_path = self._get_vm_folder_path(
                        vm, content.rootFolder,
                    )
                    results.append({
                        "name": name,
                        "folder": folder_path,
                        "status": (
                            str(vm.summary.runtime.powerState)
                            if vm.summary else "unknown"
                        ),
                        "ip_address": (
                            vm.guest.ipAddress if vm.guest else None
                        ),
                    })
                    if len(results) >= limit:
                        break
                except Exception:
                    continue
        finally:
            container.Destroy()
        return results

    # -- folder traversal --------------------------------------------------

    def _vms_in_folder(self, folder_path: str) -> List[VMInfo]:
        content = self._si.RetrieveContent()
        folder = self._navigate_to_folder(content.rootFolder, folder_path)
        if folder is None:
            logger.warning("Folder not found: %s", folder_path)
            return []
        return self._collect_vms(folder, folder_path)

    def _navigate_to_folder(
        self, root: vim.Folder, path: str
    ) -> Optional[vim.Folder]:
        parts = [p for p in path.split("/") if p]
        current: Any = root

        for part in parts:
            found = False
            children = self._get_child_entities(current)
            for child in children:
                if child.name == part:
                    current = child
                    found = True
                    break
            if not found:
                logger.debug("Could not find '%s' in %s", part, current.name)
                return None

        if isinstance(current, vim.Folder):
            return current
        return None

    @staticmethod
    def _get_child_entities(obj: Any) -> List:
        if isinstance(obj, vim.Folder):
            return list(obj.childEntity)
        if isinstance(obj, vim.Datacenter):
            return list(obj.vmFolder.childEntity)
        return []

    def _collect_vms(self, folder: vim.Folder, folder_path: str) -> List[VMInfo]:
        scheme = self._config.dashboard.connect_url_scheme
        vms: list[VMInfo] = []
        for entity in folder.childEntity:
            if isinstance(entity, vim.VirtualMachine):
                vms.append(self._vm_to_info(entity, folder_path, scheme))
            elif isinstance(entity, vim.Folder):
                vms.extend(self._collect_vms(entity, folder_path))
        return vms

    def _get_vm_folder_path(
        self, vm: vim.VirtualMachine, root_folder: vim.Folder,
    ) -> str:
        """Reconstruct the navigable folder path by walking the parent chain."""
        parts: list[str] = []
        current = vm.parent
        while current is not None and current != root_folder:
            if isinstance(current, vim.Datacenter):
                parts.append(current.name)
            elif isinstance(current, vim.Folder):
                if isinstance(getattr(current, "parent", None), vim.Datacenter):
                    current = current.parent
                    continue
                parts.append(current.name)
            current = getattr(current, "parent", None)
        parts.reverse()
        return "/".join(parts)

    # -- VM detail extraction ----------------------------------------------

    def _vm_to_info(
        self, vm: vim.VirtualMachine, folder_path: str, scheme: str
    ) -> VMInfo:
        config = vm.config
        guest = vm.guest
        summary = vm.summary

        name = config.name if config else vm.name
        status = str(summary.runtime.powerState) if summary else "unknown"
        ip = guest.ipAddress if guest else None

        creation_date = self._extract_creation_date(config)
        portal_version = self._extract_portal_version(config, name)
        connect_url = f"{scheme}://{ip}" if ip else None

        return VMInfo(
            name=name,
            folder=folder_path,
            portal_version=portal_version,
            creation_date=creation_date,
            ip_address=ip,
            connect_url=connect_url,
            status=status,
        )

    @staticmethod
    def _extract_creation_date(config: Any) -> Optional[datetime]:
        if config is None:
            return None
        cd = getattr(config, "createDate", None)
        if cd is not None:
            if cd.tzinfo is None:
                return cd.replace(tzinfo=timezone.utc)
            return cd
        return None

    @staticmethod
    def _extract_portal_version(config: Any, vm_name: str) -> Optional[str]:
        """Try multiple sources to find the portal version."""
        if config and config.annotation:
            m = _VERSION_PATTERN.search(config.annotation)
            if m:
                return m.group(1)

        m = _VERSION_PATTERN.search(vm_name)
        if m:
            return m.group(1)

        return None

    @staticmethod
    def filter_vms_by_owner_email(vms: List[VMInfo], owner_email: str) -> List[VMInfo]:
        """Filter VMs by matching owner email or local-part in name/folder."""
        email = owner_email.strip().lower()
        if not email:
            return vms

        local = email.split("@", 1)[0]
        tokens = [email]
        if local:
            tokens.append(local)

        filtered: List[VMInfo] = []
        for vm in vms:
            hay = f"{vm.name} {vm.folder}".lower()
            if any(token and token in hay for token in tokens):
                filtered.append(vm)
        return filtered

    # -- power actions -----------------------------------------------------

    def power_off(self, vm_name: str, folder_path: str) -> Tuple[bool, str]:
        self._ensure_connected()
        vm = self._find_vm_in_folder(vm_name, folder_path)
        if vm is None:
            return False, f"VM '{vm_name}' not found in {folder_path}"
        try:
            task = vm.PowerOffVM_Task()
            self._wait_for_task(task)
            self._cache_ts = 0
            return True, f"VM '{vm_name}' powered off"
        except Exception as e:
            return False, f"Power off failed: {e}"

    def power_on(self, vm_name: str, folder_path: str) -> Tuple[bool, str]:
        self._ensure_connected()
        vm = self._find_vm_in_folder(vm_name, folder_path)
        if vm is None:
            return False, f"VM '{vm_name}' not found in {folder_path}"
        try:
            task = vm.PowerOnVM_Task()
            self._wait_for_task(task)
            self._cache_ts = 0
            return True, f"VM '{vm_name}' powered on"
        except Exception as e:
            return False, f"Power on failed: {e}"

    def restart(self, vm_name: str, folder_path: str) -> Tuple[bool, str]:
        self._ensure_connected()
        vm = self._find_vm_in_folder(vm_name, folder_path)
        if vm is None:
            return False, f"VM '{vm_name}' not found in {folder_path}"
        try:
            task = vm.ResetVM_Task()
            self._wait_for_task(task)
            self._cache_ts = 0
            return True, f"VM '{vm_name}' restarted"
        except Exception as e:
            return False, f"Restart failed: {e}"

    def delete_vm(self, vm_name: str, folder_path: str) -> Tuple[bool, str]:
        self._ensure_connected()
        vm = self._find_vm_in_folder(vm_name, folder_path)
        if vm is None:
            return False, f"VM '{vm_name}' not found in {folder_path}"
        try:
            if vm.runtime.powerState == vim.VirtualMachinePowerState.poweredOn:
                off_task = vm.PowerOffVM_Task()
                self._wait_for_task(off_task)
            task = vm.Destroy_Task()
            self._wait_for_task(task)
            self._cache_ts = 0
            return True, f"VM '{vm_name}' deleted"
        except Exception as e:
            return False, f"Delete failed: {e}"

    # -- snapshots ---------------------------------------------------------

    def create_snapshot(self, vm_name: str, folder_path: str) -> Tuple[bool, str, Optional[str]]:
        """Create a snapshot for a VM. Returns (success, message, snapshot_name)."""
        self._ensure_connected()
        vm = self._find_vm_in_folder(vm_name, folder_path)
        if vm is None:
            return False, f"VM '{vm_name}' not found in {folder_path}", None

        now = datetime.now().strftime("%Y-%m-%d_%H-%M")
        snap_name = f"{vm_name}_{now}"

        try:
            task = vm.CreateSnapshot_Task(
                name=snap_name,
                description=f"Created by Dashboard-X on {now}",
                memory=False,
                quiesce=False,
            )
            self._wait_for_task(task)
            logger.info("Snapshot '%s' created for VM '%s'", snap_name, vm_name)
            return True, f"Snapshot '{snap_name}' created successfully", snap_name
        except Exception as e:
            logger.error("Snapshot failed for '%s': %s", vm_name, e)
            return False, f"Snapshot failed: {e}", None

    def list_snapshots(self, vm_name: str, folder_path: str) -> List[str]:
        """List all snapshot names for a VM."""
        self._ensure_connected()
        vm = self._find_vm_in_folder(vm_name, folder_path)
        if vm is None:
            return []

        snapshot_info = getattr(vm, "snapshot", None)
        root_snaps = list(getattr(snapshot_info, "rootSnapshotList", []) or [])
        names: List[str] = []
        self._collect_snapshot_names(root_snaps, names)
        return names

    def restore_snapshot(
        self,
        vm_name: str,
        folder_path: str,
        snapshot_name: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Restore a VM to either the current or a named snapshot."""
        self._ensure_connected()
        vm = self._find_vm_in_folder(vm_name, folder_path)
        if vm is None:
            return False, f"VM '{vm_name}' not found in {folder_path}"

        snapshot_info = getattr(vm, "snapshot", None)
        root_snaps = list(getattr(snapshot_info, "rootSnapshotList", []) or [])
        if not root_snaps:
            return False, f"No snapshots found for VM '{vm_name}'"

        try:
            if snapshot_name:
                snap_mo = self._find_snapshot_by_name(root_snaps, snapshot_name)
                if snap_mo is None:
                    return False, f"Snapshot '{snapshot_name}' not found for VM '{vm_name}'"
                task = snap_mo.RevertToSnapshot_Task()
                self._wait_for_task(task)
                self._cache_ts = 0
                return True, f"VM '{vm_name}' restored to snapshot '{snapshot_name}'"

            task = vm.RevertToCurrentSnapshot_Task()
            self._wait_for_task(task)
            self._cache_ts = 0
            return True, f"VM '{vm_name}' restored to its current snapshot"
        except Exception as e:
            logger.error("Restore snapshot failed for '%s': %s", vm_name, e)
            return False, f"Restore snapshot failed: {e}"

    def _find_snapshot_by_name(self, nodes: List[Any], snapshot_name: str) -> Optional[Any]:
        """Return snapshot managed object by traversing snapshot tree recursively."""
        for node in nodes:
            if getattr(node, "name", None) == snapshot_name:
                return getattr(node, "snapshot", None)
            children = list(getattr(node, "childSnapshotList", []) or [])
            found = self._find_snapshot_by_name(children, snapshot_name)
            if found is not None:
                return found
        return None

    def _collect_snapshot_names(self, nodes: List[Any], out: List[str]) -> None:
        for node in nodes:
            name = getattr(node, "name", None)
            if name:
                out.append(name)
            children = list(getattr(node, "childSnapshotList", []) or [])
            if children:
                self._collect_snapshot_names(children, out)

    def _find_vm_in_folder(self, vm_name: str, folder_path: str) -> Optional[vim.VirtualMachine]:
        content = self._si.RetrieveContent()
        folder = self._navigate_to_folder(content.rootFolder, folder_path)
        if folder is None:
            return None
        return self._search_vm_in_folder(folder, vm_name)

    def _search_vm_in_folder(self, folder: vim.Folder, vm_name: str) -> Optional[vim.VirtualMachine]:
        for entity in folder.childEntity:
            if isinstance(entity, vim.VirtualMachine) and entity.name == vm_name:
                return entity
            if isinstance(entity, vim.Folder):
                result = self._search_vm_in_folder(entity, vm_name)
                if result:
                    return result
        return None

    # -- templates ---------------------------------------------------------

    def list_templates(self, limit: int = 10) -> List[TemplateInfo]:
        self._ensure_connected()
        content = self._si.RetrieveContent()
        template_folder_path = self._config.clone.template_folder
        folder = self._navigate_to_folder(content.rootFolder, template_folder_path)
        if folder is None:
            logger.warning("Template folder not found: %s", template_folder_path)
            return []

        templates: List[TemplateInfo] = []
        for entity in folder.childEntity:
            if isinstance(entity, vim.VirtualMachine) and entity.config.template:
                cfg = entity.config
                templates.append(TemplateInfo(
                    name=entity.name,
                    folder=template_folder_path,
                    portal_version=self._extract_portal_version(cfg, entity.name),
                    creation_date=self._extract_creation_date(cfg),
                ))

        # Prefer newest templates first. If date is missing, fallback to name ordering.
        templates.sort(
            key=lambda t: (
                t.creation_date is not None,
                t.creation_date or datetime.min.replace(tzinfo=timezone.utc),
                t.name.lower(),
            ),
            reverse=True,
        )
        if limit > 0:
            templates = templates[:limit]
        return templates

    # -- clone from template -----------------------------------------------

    def clone_vm(self, template_name: str, vm_name: str) -> Tuple[bool, str]:
        """Clone a VM from a PIM template using reference VM parameters."""
        self._ensure_connected()
        content = self._si.RetrieveContent()

        template = self._find_template(content, template_name)
        if template is None:
            return False, f"Template '{template_name}' not found"

        ref_vm = self._find_reference_vm(content)
        if ref_vm is None:
            return False, (
                f"Reference VM not found at '{self._config.clone.reference_vm_path}' "
                f"and no fallback VM exists in monitored folders. "
                f"Update 'clone.reference_vm_path' in config.yaml to point to an existing VM."
            )

        target_folder = self._navigate_to_folder(
            content.rootFolder, self._config.clone.target_folder
        )
        if target_folder is None:
            return False, f"Target folder '{self._config.clone.target_folder}' not found"
        if self._search_vm_in_folder(target_folder, vm_name) is not None:
            return False, f"VM '{vm_name}' already exists in '{self._config.clone.target_folder}'"

        try:
            relocate_spec = self._build_relocate_spec(ref_vm)
            clone_spec = vim.vm.CloneSpec(
                location=relocate_spec,
                powerOn=False,
                template=False,
            )

            logger.info("Cloning '%s' -> '%s'", template_name, vm_name)
            task = template.Clone(folder=target_folder, name=vm_name, spec=clone_spec)
            self._wait_for_task(task)

            cloned_vm = self._wait_for_vm_in_folder(target_folder, vm_name)
            warnings: List[str] = []
            if cloned_vm is None:
                warnings.append("Clone completed but VM is not yet visible in target folder")
            else:
                try:
                    self._reconfigure_network(cloned_vm, ref_vm)
                except Exception as net_err:
                    logger.warning("Network reconfig failed (VM still created): %s", net_err)
                    warnings.append(f"network reconfiguration failed ({net_err})")
                try:
                    power_task = cloned_vm.PowerOnVM_Task()
                    self._wait_for_task(power_task)
                except Exception as power_err:
                    logger.warning("Power on failed (VM still created): %s", power_err)
                    warnings.append(f"power on failed ({power_err})")

            self._cache_ts = 0
            logger.info("Clone complete: '%s'", vm_name)
            base_msg = f"VM '{vm_name}' created successfully from template '{template_name}'"
            if warnings:
                return True, f"{base_msg}; warnings: " + "; ".join(warnings)
            return True, base_msg
        except Exception as e:
            logger.error("Clone failed: %s", e)
            return False, f"Clone failed: {e}"

    def _wait_for_vm_in_folder(
        self,
        folder: vim.Folder,
        vm_name: str,
        timeout: int = 60,
    ) -> Optional[vim.VirtualMachine]:
        start = time.time()
        while time.time() - start <= timeout:
            vm = self._search_vm_in_folder(folder, vm_name)
            if vm is not None:
                return vm
            time.sleep(2)
        return None

    def _find_template(self, content: Any, template_name: str) -> Optional[vim.VirtualMachine]:
        folder = self._navigate_to_folder(
            content.rootFolder, self._config.clone.template_folder
        )
        if folder is None:
            return None
        for entity in folder.childEntity:
            if isinstance(entity, vim.VirtualMachine) and entity.name == template_name:
                return entity
        return None

    def _find_reference_vm(self, content: Any) -> Optional[vim.VirtualMachine]:
        ref_path = self._config.clone.reference_vm_path
        parts = ref_path.rsplit("/", 1)
        if len(parts) == 2:
            folder_path, vm_name = parts
            folder = self._navigate_to_folder(content.rootFolder, folder_path)
            if folder is not None:
                for entity in folder.childEntity:
                    if isinstance(entity, vim.VirtualMachine) and entity.name == vm_name:
                        return entity
            logger.warning(
                "Configured reference VM '%s' not found, searching for fallback in monitored folders",
                ref_path,
            )

        for folder_path in self._config.folders:
            folder = self._navigate_to_folder(content.rootFolder, folder_path)
            if folder is None:
                continue
            for entity in folder.childEntity:
                if (
                    isinstance(entity, vim.VirtualMachine)
                    and not entity.config.template
                    and entity.resourcePool is not None
                ):
                    logger.info("Using fallback reference VM: '%s' from '%s'", entity.name, folder_path)
                    return entity

        return None

    def _build_relocate_spec(self, ref_vm: vim.VirtualMachine) -> vim.vm.RelocateSpec:
        spec = vim.vm.RelocateSpec()
        spec.pool = ref_vm.resourcePool
        if ref_vm.datastore:
            spec.datastore = ref_vm.datastore[0]
        return spec

    def _reconfigure_network(self, vm: vim.VirtualMachine, ref_vm: vim.VirtualMachine) -> None:
        """After clone, update the VM's NIC to match the reference VM's network."""
        ref_nics = [
            d for d in ref_vm.config.hardware.device
            if isinstance(d, vim.vm.device.VirtualEthernetCard)
        ]
        clone_nics = [
            d for d in vm.config.hardware.device
            if isinstance(d, vim.vm.device.VirtualEthernetCard)
        ]
        if not ref_nics or not clone_nics:
            return

        ref_backing = ref_nics[0].backing
        clone_nic = clone_nics[0]

        new_backing = vim.vm.device.VirtualEthernetCard.NetworkBackingInfo()
        new_backing.deviceName = ref_backing.deviceName
        if hasattr(ref_backing, "network") and ref_backing.network:
            new_backing.network = ref_backing.network

        nic_spec = vim.vm.device.VirtualDeviceSpec()
        nic_spec.operation = vim.vm.device.VirtualDeviceSpec.Operation.edit
        nic_spec.device = clone_nic
        nic_spec.device.backing = new_backing
        nic_spec.device.connectable = vim.vm.device.VirtualDevice.ConnectInfo()
        nic_spec.device.connectable.startConnected = True
        nic_spec.device.connectable.allowGuestControl = True

        config_spec = vim.vm.ConfigSpec()
        config_spec.deviceChange = [nic_spec]
        task = vm.ReconfigVM_Task(spec=config_spec)
        self._wait_for_task(task)
        logger.info("Network reconfigured to '%s'", ref_backing.deviceName)

    # -- create empty VM ---------------------------------------------------

    def create_empty_vm(
        self,
        vm_name: str,
        num_cpus: int = 4,
        memory_gb: int = 8,
        disk_gb: int = 100,
    ) -> Tuple[bool, str]:
        """Create an empty VM (no OS) for use as an edge filer."""
        self._ensure_connected()
        content = self._si.RetrieveContent()

        ref_vm = self._find_reference_vm(content)
        if ref_vm is None:
            return False, (
                f"Reference VM not found at '{self._config.clone.reference_vm_path}' "
                f"and no fallback VM exists in monitored folders. "
                f"Update 'clone.reference_vm_path' in config.yaml to point to an existing VM."
            )

        target_folder = self._navigate_to_folder(
            content.rootFolder, self._config.clone.target_folder
        )
        if target_folder is None:
            return False, f"Target folder '{self._config.clone.target_folder}' not found"
        if self._search_vm_in_folder(target_folder, vm_name) is not None:
            return False, f"VM '{vm_name}' already exists in '{self._config.clone.target_folder}'"

        resource_pool = ref_vm.resourcePool
        datastore = ref_vm.datastore[0] if ref_vm.datastore else None
        if datastore is None:
            return False, "Reference VM has no datastore"

        try:
            config_spec = self._build_empty_vm_spec(
                vm_name, num_cpus, memory_gb, disk_gb, datastore, ref_vm,
            )

            logger.info(
                "Creating empty VM '%s' (%d vCPU, %d GB RAM, %d GB disk)",
                vm_name, num_cpus, memory_gb, disk_gb,
            )
            task = target_folder.CreateVM_Task(config=config_spec, pool=resource_pool)
            self._wait_for_task(task)

            created_vm = self._wait_for_vm_in_folder(target_folder, vm_name)
            warnings: List[str] = []
            if created_vm is None:
                warnings.append("VM created but not yet visible in target folder")
            else:
                try:
                    power_task = created_vm.PowerOnVM_Task()
                    self._wait_for_task(power_task)
                except Exception as power_err:
                    logger.warning("Power on failed (VM still created): %s", power_err)
                    warnings.append(f"power on failed ({power_err})")

            self._cache_ts = 0
            logger.info("Empty VM created: '%s'", vm_name)
            base_msg = f"VM '{vm_name}' created successfully"
            if warnings:
                return True, f"{base_msg}; warnings: " + "; ".join(warnings)
            return True, base_msg
        except Exception as e:
            logger.error("Create empty VM failed: %s", e)
            return False, f"Create VM failed: {e}"

    def _build_empty_vm_spec(
        self,
        vm_name: str,
        num_cpus: int,
        memory_gb: int,
        disk_gb: int,
        datastore: Any,
        ref_vm: vim.VirtualMachine,
    ) -> vim.vm.ConfigSpec:
        ds_name = datastore.name

        scsi_ctrl = vim.vm.device.VirtualLsiLogicSASController()
        scsi_ctrl.key = 1000
        scsi_ctrl.busNumber = 0
        scsi_ctrl.sharedBus = vim.vm.device.VirtualSCSIController.Sharing.noSharing
        scsi_ctrl_spec = vim.vm.device.VirtualDeviceSpec()
        scsi_ctrl_spec.operation = vim.vm.device.VirtualDeviceSpec.Operation.add
        scsi_ctrl_spec.device = scsi_ctrl

        disk_backing = vim.vm.device.VirtualDisk.FlatVer2BackingInfo()
        disk_backing.fileName = f"[{ds_name}]"
        disk_backing.diskMode = "persistent"
        disk_backing.thinProvisioned = True

        disk = vim.vm.device.VirtualDisk()
        disk.key = 2000
        disk.controllerKey = 1000
        disk.unitNumber = 0
        disk.capacityInKB = disk_gb * 1024 * 1024
        disk.backing = disk_backing
        disk_spec = vim.vm.device.VirtualDeviceSpec()
        disk_spec.operation = vim.vm.device.VirtualDeviceSpec.Operation.add
        disk_spec.fileOperation = vim.vm.device.VirtualDeviceSpec.FileOperation.create
        disk_spec.device = disk

        nic_spec = self._build_nic_spec_from_ref(ref_vm)

        device_changes = [scsi_ctrl_spec, disk_spec]
        if nic_spec is not None:
            device_changes.append(nic_spec)

        spec = vim.vm.ConfigSpec()
        spec.name = vm_name
        spec.numCPUs = num_cpus
        spec.memoryMB = memory_gb * 1024
        spec.guestId = "centos9_64Guest"
        spec.annotation = "Edge Filer (empty VM)"
        spec.files = vim.vm.FileInfo(vmPathName=f"[{ds_name}]")
        spec.deviceChange = device_changes
        return spec

    def _build_nic_spec_from_ref(
        self, ref_vm: vim.VirtualMachine
    ) -> Optional[vim.vm.device.VirtualDeviceSpec]:
        """Build a NIC device spec matching the reference VM's first network."""
        ref_nics = [
            d for d in ref_vm.config.hardware.device
            if isinstance(d, vim.vm.device.VirtualEthernetCard)
        ]
        if not ref_nics:
            return None

        ref_backing = ref_nics[0].backing

        nic = vim.vm.device.VirtualVmxnet3()
        nic.key = 4000
        backing = vim.vm.device.VirtualEthernetCard.NetworkBackingInfo()
        backing.deviceName = ref_backing.deviceName
        if hasattr(ref_backing, "network") and ref_backing.network:
            backing.network = ref_backing.network
        nic.backing = backing
        nic.connectable = vim.vm.device.VirtualDevice.ConnectInfo()
        nic.connectable.startConnected = True
        nic.connectable.allowGuestControl = True
        nic.connectable.connected = True
        nic.addressType = "generated"

        nic_spec = vim.vm.device.VirtualDeviceSpec()
        nic_spec.operation = vim.vm.device.VirtualDeviceSpec.Operation.add
        nic_spec.device = nic
        return nic_spec

    # -- task helper -------------------------------------------------------

    @staticmethod
    def _wait_for_task(task: Any, timeout: int = 600) -> None:
        start = time.time()
        while task.info.state in (vim.TaskInfo.State.queued, vim.TaskInfo.State.running):
            if time.time() - start > timeout:
                raise TimeoutError(f"Task timed out after {timeout}s")
            time.sleep(2)
        if task.info.state == vim.TaskInfo.State.error:
            raise RuntimeError(task.info.error.msg if task.info.error else "Task failed")
