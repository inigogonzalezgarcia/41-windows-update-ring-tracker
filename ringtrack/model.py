"""Loading: the Intune managed devices (managedDevices, with the ring groups from Entra ID or the ConfigMgr collections), the update ring
policies (windowsUpdateForBusinessConfiguration, and ConfigMgr software update deployments for co-managed devices), the update status per
device and month (Windows Update for Business reports: UCClientUpdateStatus, UCUpdateAlert and UCClient), the monthly builds, the versions
with their end of servicing and the known issues from Windows release health, the incidents tagged to an update, and settings.json; with
forgiving column names, into plain dataclasses."""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

DEVICE_ALIASES = {
    "name": ["devicename", "device name", "device", "computer name", "computername", "name"],
    "id": ["id", "intune device id", "managed device id", "device id"],
    "aad_id": ["azureaddeviceid", "azure ad device id", "entra device id", "aad device id"],
    "os_version": ["osversion", "os version", "os build", "osbuild", "operating system version"],
    "model": ["model"],
    "manufacturer": ["manufacturer", "oem", "oemname"],
    "last_sync": ["lastsyncdatetime", "last sync", "last check in", "last checkin", "last contact"],
    "upn": ["userprincipalname", "user principal name", "primary user upn", "primary user", "user"],
    "department": ["department", "user department", "departamento"],
    "site": ["site", "officelocation", "office location", "location", "office", "sede"],
    "category": ["devicecategorydisplayname", "device category", "category", "categoria"],
    "groups": ["groups", "ring groups", "group memberships", "memberof", "collections", "grupos"],
    "wufb_intune": ["configurationmanagerclientenabledfeatures windowsupdateforbusiness", "windowsupdateforbusiness", "wufb workload intune",
                    "update workload intune"],
    "management_agent": ["managementagent", "management agent", "managed by"],
}
POLICY_ALIASES = {
    "name": ["displayname", "display name", "policy", "policy name", "deployment name", "name"],
    "ring": ["ring", "anillo"],
    "source": ["source", "tool", "origen"],
    "groups": ["assignedgroups", "assigned groups", "groups", "target collection", "collection", "assignments"],
    "quality_deferral": ["qualityupdatesdeferralperiodindays", "quality deferral days", "quality deferral", "available after days"],
    "feature_deferral": ["featureupdatesdeferralperiodindays", "feature deferral days", "feature deferral"],
    "deadline": ["deadlineforqualityupdatesindays", "quality deadline days", "deadline days", "deadline"],
    "feature_deadline": ["deadlineforfeatureupdatesindays", "feature deadline days"],
    "grace": ["deadlinegraceperiodindays", "grace period days", "grace period", "grace"],
    "paused": ["qualityupdatespaused", "quality updates paused", "paused"],
    "pause_start": ["qualityupdatespausestartdate", "pause start", "paused on"],
    "pause_expiry": ["qualityupdatespauseexpirydatetime", "pause expiry", "pause expires"],
    "feature_paused": ["featureupdatespaused", "feature updates paused"],
    "modified": ["lastmodifieddatetime", "last modified", "modified"],
}
STATUS_ALIASES = {
    "name": ["devicename", "device name", "device", "computer name"],
    "aad_id": ["azureaddeviceid", "azure ad device id", "entra device id"],
    "category": ["updatecategory", "update category", "category"],
    "release": ["updatereleasetime", "update release time", "release date", "released"],
    "target_version": ["targetversion", "target version"],
    "target_build": ["targetbuild", "target build"],
    "kb": ["targetkbnumber", "target kb", "kb", "article id"],
    "state": ["clientstate", "client state", "state", "status"],
    "substate": ["clientsubstate", "client substate", "substate", "detail"],
    "restart_required": ["restartrequiredtime", "restart required time", "reboot required since"],
    "installed": ["updateinstalledtime", "update installed time", "installed", "install date"],
    "error": ["errorcode", "error code", "last error", "error"],
    "alert": ["alertsubtype", "alert subtype", "alert"],
    "last_scan": ["lastwuscantime", "lastwuscan", "last wu scan", "last scan", "last scan time"],
}
RELEASE_ALIASES = {
    "kind": ["kind", "type of row", "tipo"],
    "month": ["month", "mes"],
    "version": ["version", "osversion", "feature update"],
    "build": ["build", "os build"],
    "kb": ["kb", "kb article", "originating kb"],
    "release_date": ["release_date", "release date", "availability date", "date"],
    "update_type": ["update_type", "update type", "release type"],
    "end_of_servicing": ["end_of_servicing", "end of servicing", "end of updates", "end of updates enterprise"],
    "title": ["title", "summary", "issue"],
    "status": ["status", "estado"],
    "opened": ["opened", "opened on", "first reported"],
    "resolved": ["resolved", "resolved on"],
    "blocks": ["blocks", "blocks rings", "hold rings"],
}
INCIDENT_ALIASES = {
    "number": ["number", "incident", "issue key", "key", "id"],
    "short_description": ["short_description", "short description", "summary", "title"],
    "priority": ["priority", "prioridad"],
    "opened": ["opened_at", "opened", "created", "sys_created_on"],
    "resolved": ["resolved_at", "resolved", "resolution date"],
    "kb": ["kb", "update", "related update", "u_windows_update", "windows update"],
    "ring": ["ring", "u_update_ring", "update ring"],
    "devices": ["devices", "affected devices", "device count"],
    "rollback": ["rollback", "rolled back", "uninstalled"],
}

YES = {"yes", "y", "true", "1", "si", "x", "on"}
DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S",
                "%d/%m/%Y %H:%M", "%d/%m/%Y", "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M", "%m/%d/%Y")
# Windows 11 build numbers and versions; releases.csv overrides and extends them.
BUILD_VERSION = {22000: "21H2", 22621: "22H2", 22631: "23H2", 26100: "24H2", 26200: "25H2", 26300: "26H2", 28000: "26H1"}
# Error codes the reports show most often; settings.json "error_codes" adds or overrides.
ERROR_NAMES = {
    "0X800F0922": "CBS_E_INSTALLERS_FAILED: an advanced installer failed (System Reserved partition, Secure Boot task, firmware)",
    "0X80070002": "ERROR_FILE_NOT_FOUND: a file the update needs was not found",
    "0X800F081F": "CBS_E_SOURCE_MISSING: component store corruption, source not found",
    "0X80073712": "ERROR_SXS_COMPONENT_STORE_CORRUPT: the component store is inconsistent",
    "0X800F0831": "CBS_E_STORE_CORRUPTION: the component store is corrupted",
    "0X8024402C": "WU_E_PT_WINHTTP_NAME_NOT_RESOLVED: the proxy or Windows Update name cannot be resolved",
    "0X80070070": "ERROR_DISK_FULL: not enough disk space",
    "0X80070643": "ERROR_INSTALL_FAILURE: the installation failed",
    "0XC1900101": "Feature update rolled back, in most cases a driver",
}
DEFAULT_OWNERS = {"rings": "Endpoint engineering", "devices": "Desktop support", "failures": "Endpoint engineering",
                  "composition": "Endpoint engineering", "trend": "Head of end user computing"}


def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", "".join(ch for ch in s if not unicodedata.combining(ch))).strip()


def parse_dt(v) -> datetime | None:
    s = str(v or "").strip()
    if not s or _norm(s) in {"n a", "na", "none", "null", "never"}:
        return None
    s = re.sub(r"(\.\d+)?(Z|[+-]\d{2}:?\d{2})$", "", s)
    for f in DATE_FORMATS:
        try:
            return datetime.strptime(s, f)
        except ValueError:
            continue
    return None


def yes(v) -> bool:
    return _norm(v) in YES


def num(v) -> float | None:
    s = str(v or "").strip().replace(",", ".")
    try:
        return float(s) if s else None
    except ValueError:
        return None


def split_list(v) -> list[str]:
    return [x.strip() for x in re.split(r"[;|\n]+", str(v or "")) if x.strip()]


def _read(path: Path) -> tuple[list[str], list[dict]]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        header = fh.readline()
        fh.seek(0)
        delim = max(",;\t", key=header.count)
        reader = csv.DictReader(fh, delimiter=delim)
        return list(reader.fieldnames or []), list(reader)


def _map(fields: list[str], aliases: dict[str, list[str]]) -> dict[str, str]:
    heads = {_norm(h): h for h in fields}
    cols = {}
    for k, names in aliases.items():
        for n in names + [k.replace("_", " ")]:
            if _norm(n) in heads and heads[_norm(n)] not in cols.values():
                cols[k] = heads[_norm(n)]
                break
    return cols


def _rows(path: Path, aliases: dict[str, list[str]]) -> list[dict]:
    fields, raw = _read(path)
    cols = _map(fields, aliases)
    return [{k: (r.get(c) or "").strip() for k, c in cols.items()} for r in raw]


def parse_build(v) -> tuple[int, int]:
    """'10.0.26200.9711', '26200.9711' or 'OS Build 26200.9711' -> (26200, 9711); (0, 0) when unknown."""
    nums = [int(x) for x in re.findall(r"\d+", str(v or ""))]
    if len(nums) >= 4 and nums[0] == 10 and nums[1] == 0:
        return nums[2], nums[3]
    if len(nums) >= 2 and nums[0] >= 10000:
        return nums[0], nums[1]
    return (nums[0], 0) if nums and nums[0] >= 10000 else (0, 0)


def error_code(v) -> str:
    """'0x800f0922', '-2146498270' or '800F0922' -> '0X800F0922'; '' for none or 0."""
    s = str(v or "").strip()
    if not s or _norm(s) in {"0", "none", "0x0", "0x00000000", "n a"}:
        return ""
    if re.fullmatch(r"-?\d+", s):
        n = int(s)
        return "" if n == 0 else f"0X{n & 0xFFFFFFFF:08X}"
    s = s.upper().replace("0X", "")
    return f"0X{s.zfill(8)}" if re.fullmatch(r"[0-9A-F]{1,8}", s) else str(v).strip()


def update_category(v) -> str:
    n = _norm(v)
    return "feature" if "feature" in n or "upgrade" in n else "driver" if "driver" in n else "quality"


def month_key(d) -> str:
    return f"{d.year}-{d.month:02d}"


# ---------------------------------------------------------------- records

@dataclass
class Device:
    name: str
    id: str = ""
    aad_id: str = ""
    os_version: str = ""
    model: str = ""
    manufacturer: str = ""
    last_sync: datetime | None = None
    upn: str = ""
    department: str = ""
    site: str = ""
    category: str = ""
    groups: list[str] = field(default_factory=list)
    wufb_intune: bool | None = None     # None: unknown (no co-management column)
    management_agent: str = ""

    @property
    def build(self) -> tuple[int, int]:
        return parse_build(self.os_version)

    @property
    def key(self) -> str:
        return (self.aad_id or self.name).lower()


@dataclass
class Policy:
    name: str
    ring: str = ""
    source: str = "Intune"           # Intune (update ring) or ConfigMgr (software update deployment)
    groups: list[str] = field(default_factory=list)
    quality_deferral: int = 0
    feature_deferral: int = 0
    deadline: int | None = None
    feature_deadline: int | None = None
    grace: int | None = None
    paused: bool = False
    pause_start: datetime | None = None
    pause_expiry: datetime | None = None
    feature_paused: bool = False
    modified: datetime | None = None

    @property
    def configmgr(self) -> bool:
        return "config" in _norm(self.source) or "sccm" in _norm(self.source) or "mecm" in _norm(self.source)


@dataclass
class Status:
    name: str
    aad_id: str = ""
    category: str = "quality"        # quality, feature, driver
    release: datetime | None = None
    target_version: str = ""
    target_build: str = ""
    kb: str = ""
    state: str = ""
    substate: str = ""
    restart_required: datetime | None = None
    installed: datetime | None = None
    error: str = ""
    alert: str = ""
    last_scan: datetime | None = None

    @property
    def key(self) -> str:
        return (self.aad_id or self.name).lower()

    @property
    def is_installed(self) -> bool:
        return bool(self.installed) or _norm(self.state) == "installed"

    @property
    def restart_pending(self) -> bool:
        n = _norm(self.substate) + " " + _norm(self.state)
        return not self.is_installed and ("restart" in n or "reboot" in n)

    @property
    def safeguard(self) -> bool:
        return "safeguard" in _norm(self.alert) or "safeguard" in _norm(self.substate)


@dataclass
class Build:
    month: str
    version: str
    build: int
    revision: int
    kb: str = ""
    release_date: datetime | None = None
    update_type: str = "B"


@dataclass
class Version:
    version: str
    build: int
    end_of_servicing: date | None = None


@dataclass
class Issue:
    title: str
    versions: list[str] = field(default_factory=list)
    kb: str = ""
    status: str = ""
    opened: datetime | None = None
    resolved: datetime | None = None
    blocks: list[str] = field(default_factory=list)

    def open_at(self, t: datetime) -> bool:
        if self.opened and self.opened > t:
            return False
        return not (self.resolved and self.resolved <= t) and not (not self.resolved and _norm(self.status).startswith("resolved"))


@dataclass
class Incident:
    number: str
    short_description: str = ""
    priority: int = 0
    opened: datetime | None = None
    resolved: datetime | None = None
    kb: str = ""
    ring: str = ""
    devices: int = 0
    rollback: bool = False


@dataclass
class Settings:
    organisation: str = "Windows update ring tracker"
    as_of: datetime | None = None
    month: str = ""                                    # the update month; default: the latest B release on or before as_of
    rings: list = field(default_factory=list)          # [{name, order, match, quality_deferral_days, deadline_days, grace_days, ...}]
    feature_target: str = ""
    gate_compliance: float = 0.9
    gate_failure_max: float = 0.03
    gate_min_soak_days: int = 2
    gate_incident_max_priority: int = 2
    ring_late_days: int = 2
    stale_days: int = 7
    site_stale_share: float = 0.15
    chase_critical_count: int = 50
    pause_warning_days: int = 14
    pause_critical_days: int = 28
    vip_match: str = r"trading desktop"
    vip_ring: str = ""
    pilot_ring: str = ""
    broad_ring: str = ""
    pilot_max_department_share: float = 0.5
    pilot_model_coverage_min: float = 0.8
    ring_size_tolerance: float = 0.4
    trend_months: int = 3
    trend_days: list = field(default_factory=lambda: [7, 14, 21])
    trend_targets: dict = field(default_factory=lambda: {"7": 0.6, "14": 0.85, "21": 0.95})
    failure_cluster_min: int = 5
    model_failure_share_min: float = 0.2
    eos_warning_days: int = 60
    eos_critical_days: int = 30
    site_owners: dict = field(default_factory=dict)
    error_codes: dict = field(default_factory=dict)
    owners: dict = field(default_factory=lambda: dict(DEFAULT_OWNERS))

    def owner(self, area: str) -> str:
        return self.owners.get(area) or DEFAULT_OWNERS.get(area, "IT")

    def ring_names(self) -> list[str]:
        return [r["name"] for r in sorted(self.rings, key=lambda r: (r.get("order", 0), r["name"]))]

    def ring(self, name: str) -> dict:
        return next((r for r in self.rings if r["name"] == name), {"name": name, "order": 99})


def settings_from_dict(raw: dict) -> Settings:
    s = Settings()
    for k, v in raw.items():
        if not hasattr(s, k) or v is None:
            continue
        cur = getattr(s, k)
        if k == "as_of":
            s.as_of = parse_dt(v)
        elif k == "owners":
            cur.update(v)
        elif k == "rings":
            s.rings = [dict(r) for r in v]
        elif isinstance(cur, bool):
            setattr(s, k, bool(v))
        elif isinstance(cur, int):
            setattr(s, k, int(num(v) or 0))
        elif isinstance(cur, float):
            setattr(s, k, float(num(v) or 0))
        else:
            setattr(s, k, v)
    return s


@dataclass
class Data:
    settings: Settings
    as_of: datetime
    devices: list[Device] = field(default_factory=list)
    policies: list[Policy] = field(default_factory=list)
    status: list[Status] = field(default_factory=list)
    builds: list[Build] = field(default_factory=list)
    versions: dict = field(default_factory=dict)       # version -> Version
    issues: list[Issue] = field(default_factory=list)
    incidents: list[Incident] = field(default_factory=list)
    sources: dict = field(default_factory=dict)

    @property
    def today(self) -> date:
        return self.as_of.date()

    def version_of(self, build: int) -> str:
        for v in self.versions.values():
            if v.build == build:
                return v.version
        return BUILD_VERSION.get(build, str(build) if build else "unknown")


# ---------------------------------------------------------------- loaders

def _int(v, default=None):
    x = num(v)
    return default if x is None else int(x)


def _bool_or_none(v) -> bool | None:
    n = _norm(v)
    return None if not n else n in YES


def load_devices(path: Path) -> list[Device]:
    out = []
    for r in _rows(path, DEVICE_ALIASES):
        if not r.get("name"):
            continue
        out.append(Device(r["name"], r.get("id", ""), r.get("aad_id", ""), r.get("os_version", ""), r.get("model", ""), r.get("manufacturer", ""),
                          parse_dt(r.get("last_sync")), r.get("upn", ""), r.get("department", ""), r.get("site", ""), r.get("category", ""),
                          split_list(r.get("groups")), _bool_or_none(r.get("wufb_intune")), r.get("management_agent", "")))
    return out


def load_policies(path: Path, s: Settings | None = None) -> list[Policy]:
    out = []
    for r in _rows(path, POLICY_ALIASES):
        if not r.get("name"):
            continue
        p = Policy(r["name"], r.get("ring", ""), r.get("source") or "Intune", split_list(r.get("groups")), _int(r.get("quality_deferral"), 0),
                   _int(r.get("feature_deferral"), 0), _int(r.get("deadline")), _int(r.get("feature_deadline")), _int(r.get("grace")),
                   yes(r.get("paused")), parse_dt(r.get("pause_start")), parse_dt(r.get("pause_expiry")), yes(r.get("feature_paused")),
                   parse_dt(r.get("modified")))
        if p.paused and p.pause_start and not p.pause_expiry:
            p.pause_expiry = p.pause_start + timedelta(days=35)     # Intune pauses a ring for 35 days
        if not p.ring and s:
            for ring in s.rings:
                if ring.get("match") and re.search(ring["match"], p.name, re.I):
                    p.ring = ring["name"]
                    break
        out.append(p)
    return out


def load_status(path: Path) -> list[Status]:
    return [Status(r.get("name", ""), r.get("aad_id", ""), update_category(r.get("category")), parse_dt(r.get("release")), r.get("target_version", ""),
                   r.get("target_build", ""), r.get("kb", "").upper().replace("KB", ""), r.get("state", ""), r.get("substate", ""),
                   parse_dt(r.get("restart_required")), parse_dt(r.get("installed")), error_code(r.get("error")), r.get("alert", ""),
                   parse_dt(r.get("last_scan")))
            for r in _rows(path, STATUS_ALIASES) if r.get("name") or r.get("aad_id")]


def load_releases(path: Path) -> tuple[list[Build], dict, list[Issue]]:
    builds, versions, issues = [], {}, []
    for r in _rows(path, RELEASE_ALIASES):
        kind = _norm(r.get("kind"))
        if kind.startswith("issue") or kind.startswith("known"):
            issues.append(Issue(r.get("title", ""), split_list(r.get("version")), r.get("kb", "").upper().replace("KB", ""), r.get("status", ""),
                                parse_dt(r.get("opened")), parse_dt(r.get("resolved")), split_list(r.get("blocks"))))
        elif kind.startswith("version"):
            b, _ = parse_build(r.get("build"))
            eos = parse_dt(r.get("end_of_servicing"))
            versions[r.get("version", "")] = Version(r.get("version", ""), b, eos.date() if eos else None)
        else:
            b, rev = parse_build(r.get("build"))
            rd = parse_dt(r.get("release_date"))
            if b and rd:
                builds.append(Build(r.get("month") or month_key(rd), r.get("version") or BUILD_VERSION.get(b, str(b)), b, rev,
                                    r.get("kb", "").upper().replace("KB", ""), rd, (r.get("update_type") or "B").upper()))
    for b in builds:
        versions.setdefault(b.version, Version(b.version, b.build))
    builds.sort(key=lambda b: (b.release_date, b.build, b.revision))
    return builds, versions, issues


def load_incidents(path: Path) -> list[Incident]:
    out = []
    for r in _rows(path, INCIDENT_ALIASES):
        if not r.get("number"):
            continue
        m = re.search(r"\d", r.get("priority", ""))
        out.append(Incident(r["number"], r.get("short_description", ""), int(m.group()) if m else 0, parse_dt(r.get("opened")),
                            parse_dt(r.get("resolved")), r.get("kb", "").upper().replace("KB", ""), r.get("ring", ""), _int(r.get("devices"), 0),
                            yes(r.get("rollback"))))
    return out


FILES = {
    "devices.csv": "Intune managed devices with site, department and ring groups (managedDevices, Entra ID groups)",
    "ring-policies.csv": "Update rings (windowsUpdateForBusinessConfiguration) and ConfigMgr update deployments",
    "update-status.csv": "Update status per device and month (WUfB reports: UCClientUpdateStatus, UCUpdateAlert, UCClient)",
    "releases.csv": "Monthly builds, versions and end of servicing, known issues (Windows release health)",
    "incidents.csv": "Incidents tagged to an update",
}


def _find(folder: Path, name: str) -> Path | None:
    p = folder / name
    if p.exists():
        return p
    alts = sorted(folder.glob(f"{name.rsplit('.', 1)[0]}*.csv"))
    return alts[0] if alts else None


def load(folder: Path, as_of: datetime | None = None) -> Data:
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"no folder {folder}")
    sp = folder / "settings.json"
    s = settings_from_dict(json.loads(sp.read_text(encoding="utf-8"))) if sp.exists() else Settings()
    when = as_of or s.as_of or datetime.now().replace(second=0, microsecond=0)
    paths = {n: _find(folder, n) for n in FILES}
    for need in ("devices.csv", "ring-policies.csv", "releases.csv"):
        if not paths[need]:
            raise FileNotFoundError(f"{folder}: need {need} ({FILES[need]})")
    d = Data(s, when)
    d.devices = load_devices(paths["devices.csv"])
    d.policies = load_policies(paths["ring-policies.csv"], s)
    d.builds, d.versions, d.issues = load_releases(paths["releases.csv"])
    if paths["update-status.csv"]:
        d.status = load_status(paths["update-status.csv"])
    if paths["incidents.csv"]:
        d.incidents = load_incidents(paths["incidents.csv"])
    if not s.rings:
        s.rings = [{"name": n, "order": k} for k, n in enumerate(sorted({p.ring or p.name for p in d.policies}))]
    counts = {"devices.csv": len(d.devices), "ring-policies.csv": len(d.policies), "update-status.csv": len(d.status),
              "releases.csv": len(d.builds) + len(d.issues), "incidents.csv": len(d.incidents)}
    d.sources = {n: counts[n] for n in FILES if paths[n]}
    return d


def months_until(month: str, n: int) -> list[str]:
    """The n months ending with month, oldest first: '2026-10', 3 -> ['2026-08', '2026-09', '2026-10']."""
    y, m = (int(x) for x in month.split("-"))
    out = []
    for _ in range(n):
        out.append(f"{y}-{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return out[::-1]


__all__ = ["Data", "Settings", "Device", "Policy", "Status", "Build", "Version", "Issue", "Incident", "load", "parse_build", "error_code"]
