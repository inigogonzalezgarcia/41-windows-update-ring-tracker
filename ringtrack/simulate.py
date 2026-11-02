"""Fictional demo: Contoso Markets, a made-up firm with a trading floor and 1,500 Windows 11 endpoints in London, Frankfurt, Madrid and
Milan, co-managed with Intune and Configuration Manager, reviewed on Monday 2 November 2026, twenty days after the October Patch Tuesday.
The builds, KB numbers, versions, end of servicing dates and known issues are the real ones published in Windows release health; every
device, user, policy, incident and failure is made up, with the problems placed on purpose among the everyday devices."""
from __future__ import annotations

import csv
import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path

ORG = "Contoso Markets"
AS_OF = datetime(2026, 11, 2, 8, 0)
SEED = 41
R0, R1, R2, R3 = "Ring 0 - IT", "Ring 1 - Pilot", "Ring 2 - Broad", "Ring 3 - VIP and trading floor"

SETTINGS = {
    "organisation": ORG,
    "as_of": "2026-11-02 08:00",
    "month": "",
    "rings": [
        {"name": R0, "order": 0, "match": "Ring 0", "quality_deferral_days": 0, "deadline_days": 2, "grace_days": 1, "feature_deferral_days": 0,
         "target_share": 0.02},
        {"name": R1, "order": 1, "match": "Ring 1", "quality_deferral_days": 3, "deadline_days": 3, "grace_days": 2, "feature_deferral_days": 0,
         "target_share": 0.10},
        {"name": R2, "order": 2, "match": "Ring 2", "quality_deferral_days": 10, "deadline_days": 5, "grace_days": 2, "feature_deferral_days": 0,
         "target_share": 0.74},
        {"name": R3, "order": 3, "match": "Ring 3", "quality_deferral_days": 21, "deadline_days": 5, "grace_days": 2, "feature_deferral_days": 0,
         "target_share": 0.14, "late": True},
    ],
    "feature_target": "25H2",
    "gate_compliance": 0.9,
    "gate_failure_max": 0.03,
    "gate_min_soak_days": 2,
    "gate_incident_max_priority": 2,
    "ring_late_days": 2,
    "stale_days": 7,
    "site_stale_share": 0.15,
    "chase_critical_count": 50,
    "pause_warning_days": 14,
    "pause_critical_days": 28,
    "vip_match": "trading desktop",
    "vip_ring": R3,
    "pilot_ring": R1,
    "broad_ring": R2,
    "pilot_max_department_share": 0.5,
    "pilot_model_coverage_min": 0.8,
    "ring_size_tolerance": 0.3,
    "trend_months": 3,
    "trend_days": [7, 14, 21],
    "trend_targets": {"7": 0.1, "14": 0.6, "21": 0.85},
    "failure_cluster_min": 5,
    "model_failure_share_min": 0.2,
    "eos_warning_days": 60,
    "eos_critical_days": 30,
    "site_owners": {"London": "London desktop support (Tomasz Nowak)", "Frankfurt": "Frankfurt IT (Lena Hoffmann)",
                    "Madrid": "Madrid IT (Lucía Romero)", "Milan": "Milan IT (Marco Galli)"},
    "error_codes": {},
    "owners": {"rings": "Endpoint engineering", "devices": "Desktop support leads", "failures": "Endpoint engineering",
               "composition": "Endpoint engineering", "trend": "Head of end user computing"},
}

# Real Windows 11 releases (Windows release health, checked on 2 November 2026): month, version, build, KB, date, type
BUILDS = [
    ("2026-07", "23H2", "22631.7376", "5099414", "2026-07-14", "B"),
    ("2026-07", "24H2", "26100.8875", "5101650", "2026-07-14", "B"),
    ("2026-07", "25H2", "26200.8875", "5101650", "2026-07-14", "B"),
    ("2026-08", "23H2", "22631.7517", "5120240", "2026-08-11", "B"),
    ("2026-08", "24H2", "26100.9168", "5121003", "2026-08-11", "B"),
    ("2026-08", "25H2", "26200.9168", "5121003", "2026-08-11", "B"),
    ("2026-08", "24H2", "26100.9278", "5120998", "2026-08-27", "D"),
    ("2026-08", "25H2", "26200.9278", "5120998", "2026-08-27", "D"),
    ("2026-09", "23H2", "22631.7582", "5122880", "2026-09-08", "B"),
    ("2026-09", "24H2", "26100.9445", "5124008", "2026-09-08", "B"),
    ("2026-09", "25H2", "26200.9445", "5124008", "2026-09-08", "B"),
    ("2026-09", "23H2", "22631.7584", "5129242", "2026-09-14", "OOB"),
    ("2026-09", "24H2", "26100.9457", "5129195", "2026-09-14", "OOB"),
    ("2026-09", "25H2", "26200.9457", "5129195", "2026-09-14", "OOB"),
    ("2026-09", "24H2", "26100.9550", "5124010", "2026-09-22", "D"),
    ("2026-09", "25H2", "26200.9550", "5124010", "2026-09-22", "D"),
    ("2026-10", "23H2", "22631.7652", "5126653", "2026-10-13", "B"),
    ("2026-10", "24H2", "26100.9711", "5127648", "2026-10-13", "B"),
    ("2026-10", "25H2", "26200.9711", "5127648", "2026-10-13", "B"),
    ("2026-10", "26H2", "26300.9711", "5127648", "2026-10-13", "B"),
    ("2026-10", "23H2", "22631.7654", "5134130", "2026-10-26", "OOB"),
    ("2026-10", "24H2", "26100.9725", "5134133", "2026-10-26", "OOB"),
    ("2026-10", "25H2", "26200.9725", "5134133", "2026-10-26", "OOB"),
    ("2026-10", "26H2", "26300.9725", "5134133", "2026-10-26", "OOB"),
    ("2026-10", "25H2", "26200.9818", "5127936", "2026-10-28", "D"),
    ("2026-10", "26H2", "26300.9818", "5127936", "2026-10-28", "D"),
]
VERSIONS = [("23H2", "22631", "2026-11-10"), ("24H2", "26100", "2027-10-12"), ("25H2", "26200", "2028-10-10"), ("26H2", "26300", "2029-10-09")]
ISSUES = [  # title, versions, originating KB, status, opened, resolved, blocks (the team's decision)
    ("USB audio devices might fail to start or produce no sound", "23H2;24H2;25H2;26H2", "5124008", "Mitigated", "2026-09-25", "", R3),
    ("Domain-joined devices might lose their secure trust relationship with the domain", "24H2;25H2;26H2", "5124008", "Resolved", "2026-09-16",
     "2026-09-22", ""),
    ("Applications which require AC-3 audio decoding might close unexpectedly", "24H2;25H2;26H2", "5124010", "Resolved", "2026-10-08",
     "2026-10-13", ""),
    ("Remote Desktop connections might fail for non-admin users with error 0xC000000D", "24H2;25H2;26H2", "5124010", "Resolved", "2026-10-13",
     "2026-10-28", ""),
]
INCIDENTS = [  # number, description, priority, opened, resolved, kb, ring, devices, rollback
    ("INC0103870", "No sound from USB headsets on two trading desks in the pilot after the September update", "3 - Moderate", "2026-09-26 08:41",
     "2026-09-29 17:10", "KB5124008", R1, 2, "no"),
    ("INC0104311", "Remote Desktop to admin jump hosts fails with 0xC000000D after the October update", "3 - Moderate", "2026-10-15 10:02",
     "2026-10-29 12:30", "KB5127648", R1, 6, "no"),
    ("INC0104388", "Trading floor: USB headsets with no audio (Code 10) on 14 desks after the October update", "2 - High", "2026-10-26 07:12",
     "", "KB5127648", R2, 14, "yes"),
    ("INC0104402", "October update fails with 0x800f0922 on HP EliteBook 840 G8 laptops", "3 - Moderate", "2026-10-28 11:25", "", "KB5127648", R2,
     38, "no"),
]

SITES = [("London", "LON", {"Trading": 180, "Sales": 80, "Research": 60, "Operations": 110, "Finance": 60, "Risk": 50, "Compliance": 35,
                            "Technology": 70, "HR": 20, "Executive": 25, "Legal": 30}),
         ("Frankfurt", "FRA", {"Sales": 60, "Operations": 80, "Finance": 40, "Risk": 35, "Compliance": 25, "Technology": 30, "HR": 10, "Legal": 20}),
         ("Madrid", "MAD", {"Operations": 90, "Finance": 50, "Sales": 40, "Technology": 40, "Risk": 25, "HR": 15, "Compliance": 20}),
         ("Milan", "MIL", {"Sales": 60, "Operations": 60, "Finance": 30, "Research": 25, "Technology": 15, "HR": 10})]
Z2, OPTI, LAT74, LAT54, ELITE, T14, SURF = ("HP Z2 Tower G9 Workstation", "OptiPlex 7010", "Latitude 7440", "Latitude 5440", "HP EliteBook 840 G8",
                                            "ThinkPad T14 Gen 4", "Surface Laptop 5")
MAKER = {Z2: "HP", OPTI: "Dell Inc.", LAT74: "Dell Inc.", LAT54: "Dell Inc.", ELITE: "HP", T14: "LENOVO", SURF: "Microsoft Corporation"}
FIRST = ["Alex", "Sam", "Maria", "James", "Elena", "David", "Sofia", "Lukas", "Chiara", "Pablo", "Hannah", "Omar", "Isabel", "Marco", "Emma",
         "Jonas", "Laura", "Daniel", "Giulia", "Carlos", "Anna", "Ben", "Claire", "Felix", "Grace", "Hugo", "Ines", "Jack", "Katja", "Leo"]
LAST = ["Smith", "Garcia", "Rossi", "Muller", "Brown", "Martin", "Fischer", "Lopez", "Bianchi", "Weber", "Taylor", "Moreno", "Ricci", "Wagner",
        "Clark", "Navarro", "Greco", "Becker", "Walker", "Ortega", "Conti", "Schulz", "Hughes", "Ramos", "Marino", "Koch", "Evans", "Gil"]

G0, G1, G2, G2L, G3, CM2 = ("WUfB-Ring0-IT", "WUfB-Ring1-Pilot", "WUfB-Ring2-Broad", "WUfB-Ring2-Broad-2024", "WUfB-Ring3-VIP-Trading",
                            "SUM-Ring2-Broad-Madrid")
POLICIES = [  # name, source, groups, qdef, fdef, deadline, fdeadline, grace, paused, pause start, pause expiry, modified
    ("WUfB Ring 0 - IT", "Intune", G0, 0, 0, 2, 2, 1, False, "", "", "2026-03-02 10:14"),
    ("WUfB Ring 1 - Pilot", "Intune", G1, 3, 0, 3, 5, 2, False, "", "", "2026-03-02 10:20"),
    ("WUfB Ring 2 - Broad", "Intune", G2, 10, 0, 5, 7, 2, False, "", "", "2026-03-02 10:31"),
    ("WUfB Ring 2 - Broad (2024)", "Intune", G2L, 7, 0, 7, 7, 3, False, "", "", "2024-06-11 16:02"),
    ("WUfB Ring 3 - VIP and trading floor", "Intune", G3, 21, 0, 5, 7, 2, True, "2026-09-28 17:40", "2026-11-02 17:40", "2026-09-28 17:40"),
    ("SUM Ring 2 - Broad (Madrid co-managed)", "ConfigMgr", CM2, 7, 0, 14, None, None, False, "", "", "2025-11-20 09:45"),
]

FILES = {
    "devices.csv": ("dev", ["deviceName", "id", "azureADDeviceId", "osVersion", "model", "manufacturer", "lastSyncDateTime", "userPrincipalName",
                            "department", "site", "deviceCategoryDisplayName", "managementAgent",
                            "configurationManagerClientEnabledFeatures.windowsUpdateForBusiness", "groups"]),
    "ring-policies.csv": ("pol", ["displayName", "id", "source", "assignedGroups", "qualityUpdatesDeferralPeriodInDays",
                                  "featureUpdatesDeferralPeriodInDays", "deadlineForQualityUpdatesInDays", "deadlineForFeatureUpdatesInDays",
                                  "deadlineGracePeriodInDays", "qualityUpdatesPaused", "qualityUpdatesPauseStartDate",
                                  "qualityUpdatesPauseExpiryDateTime", "featureUpdatesPaused", "lastModifiedDateTime"]),
    "update-status.csv": ("st", ["DeviceName", "AzureADDeviceId", "UpdateCategory", "UpdateReleaseTime", "TargetVersion", "TargetBuild",
                                 "TargetKBNumber", "ClientState", "ClientSubstate", "RestartRequiredTime", "UpdateInstalledTime", "ErrorCode",
                                 "AlertSubtype", "LastWUScanTime"]),
    "releases.csv": ("rel", ["kind", "month", "version", "build", "kb", "release_date", "update_type", "end_of_servicing", "title", "status",
                             "opened", "resolved", "blocks"]),
    "incidents.csv": ("inc", ["number", "short_description", "priority", "opened_at", "resolved_at", "kb", "ring", "devices", "rollback"]),
}
REL = {"2026-08": date(2026, 8, 11), "2026-09": date(2026, 9, 8), "2026-10": date(2026, 10, 13)}
OOB = {"2026-09": date(2026, 9, 14), "2026-10": date(2026, 10, 26)}
REV = {  # month -> build -> (B revision, OOB revision)
    "2026-07": {22631: (7376, 7376), 26100: (8875, 8875), 26200: (8875, 8875), 26300: (8875, 8875)},
    "2026-08": {22631: (7517, 7517), 26100: (9168, 9168), 26200: (9168, 9168), 26300: (9168, 9168)},
    "2026-09": {22631: (7582, 7584), 26100: (9445, 9457), 26200: (9445, 9457), 26300: (9445, 9457)},
    "2026-10": {22631: (7652, 7654), 26100: (9711, 9725), 26200: (9711, 9725), 26300: (9711, 9725)},
}
KB = {"2026-08": {22631: "5120240"}, "2026-09": {22631: "5122880"}, "2026-10": {22631: "5126653"}}
KB_DEFAULT = {"2026-08": "5121003", "2026-09": "5124008", "2026-10": "5127648"}
VER = {22631: "23H2", 26100: "24H2", 26200: "25H2", 26300: "26H2"}
ALERT = {"0X800F0922": "InstallIssue", "0X80070002": "FileNotFound", "0X800F081F": "WindowsComponentCorruption",
         "0X80073712": "WindowsComponentCorruption", "0X80070070": "DiskFull", "0X8024402C": "NetworkIssue", "0XC1900101": "InstallSetupError"}


def _t(v) -> str:
    return v.strftime("%Y-%m-%d %H:%M") if v else ""


def _guid(rnd: random.Random) -> str:
    h = f"{rnd.getrandbits(128):032x}"
    return f"{h[:8]}-{h[8:12]}-4{h[13:16]}-{'89ab'[int(h[16], 16) % 4]}{h[17:20]}-{h[20:32]}"


def _at(rnd: random.Random, day: date, lo: int = 8, hi: int = 19) -> datetime:
    return datetime(day.year, day.month, day.day, rnd.randint(lo, hi), rnd.randint(0, 59))


def fleet(rnd: random.Random) -> list[dict]:
    devs, users = [], set()
    n = 0
    for site, code, depts in SITES:
        for dept, k in depts.items():
            for _ in range(k):
                n += 1
                if dept == "Trading":
                    model, cat = Z2, "Trading desktop"
                elif dept == "Executive":
                    model, cat = SURF, "Executive laptop"
                elif dept == "Technology":
                    model, cat = rnd.choice([LAT74, T14]), "Laptop"
                else:
                    x = rnd.random()
                    model = OPTI if x < 0.32 else LAT74 if x < 0.55 else LAT54 if x < 0.75 else ELITE if x < 0.88 else T14
                    cat = "Desktop" if model == OPTI else "Laptop"
                kind = "TD" if cat == "Trading desktop" else "DT" if cat == "Desktop" else "LT"
                base = f"{rnd.choice(FIRST).lower()}.{rnd.choice(LAST).lower()}"
                upn, k2 = base, 1
                while upn in users:
                    k2 += 1
                    upn = f"{base}{k2}"
                users.add(upn)
                devs.append(dict(name=f"CTM-{code}-{kind}{n:04d}", site=site, dept=dept, model=model, cat=cat, upn=f"{upn}@contoso.com",
                                 id=_guid(rnd), aad=_guid(rnd), groups=[], wufb="true", build=26200, plan="ok", chronic=False, new=False,
                                 err="", ring=""))
    return devs


def assign(rnd: random.Random, devs: list[dict]) -> None:
    free = sorted(devs, key=lambda d: d["name"])

    def take(k, cond, ring, groups, **kw):
        pool = [d for d in free if not d["ring"] and cond(d)]
        rnd.shuffle(pool)
        got = sorted(pool[:k], key=lambda d: d["name"])
        assert len(got) == k, (ring, k, len(got))
        for d in got:
            d["ring"] = ring
            d["groups"] = list(groups)
            d.update(kw)
        return got

    tech = lambda s: (lambda d: d["dept"] == "Technology" and d["site"] == s)  # noqa: E731
    for s, k in (("London", 16), ("Frankfurt", 4), ("Madrid", 4), ("Milan", 4)):
        take(k, tech(s), R0, [G0])
    for s, k in (("London", 40), ("Frankfurt", 16), ("Madrid", 16)):
        take(k, tech(s), R1, [G1])
    take(12, tech("London"), R1, [G1, G2], conflict=True)
    for dept in ("Operations", "Finance"):
        for d in take(4, lambda d, dp=dept: d["dept"] == dp and d["site"] == "London", R1, [G1]):
            d["model"] = LAT54
            d["cat"] = "Laptop"
            d["name"] = d["name"].replace("-DT", "-LT")
    trading = sorted([d for d in devs if d["cat"] == "Trading desktop"], key=lambda d: d["name"])
    for d in trading[:120]:
        d["ring"], d["groups"] = R3, [G3]
    for d in [x for x in devs if x["dept"] == "Executive"]:
        d["ring"], d["groups"] = R3, [G3]
    for d in trading[120:]:                                          # planted: 60 trading desktops in the broad ring
        d["ring"], d["groups"] = R2, [G2]
    for s, k in (("Frankfurt", 15), ("Madrid", 10), ("Milan", 15)):  # planted: 40 new devices in no ring
        take(k, lambda d, st=s: d["site"] == st and d["dept"] not in ("Technology",), "none", [], new=True)
    take(140, lambda d: d["site"] == "Madrid", R2, [CM2], cm=True, wufb="false")
    take(85, lambda d: d["site"] == "Milan", R2, [G2L], legacy=True)
    for d in devs:
        if not d["ring"]:
            d["ring"], d["groups"] = R2, [G2]
    for d in devs:
        if d["ring"] == "none":
            d["ring"] = ""


def plant(rnd: random.Random, devs: list[dict]) -> None:
    """The October problems, on disjoint sets of devices."""
    def pick(k, cond, plan, **kw):
        pool = sorted([d for d in devs if d["plan"] == "ok" and cond(d)], key=lambda d: d["name"])
        rnd.shuffle(pool)
        got = pool[:k]
        assert len(got) == k, (plan, k, len(got))
        for d in got:
            d["plan"] = plan
            d.update(kw)
        return got

    main = lambda d: d["ring"] == R2 and not d.get("cm") and d["cat"] != "Trading desktop"  # noqa: E731
    pick(55, lambda d: main(d) and d["site"] == "Frankfurt" and not d.get("legacy"), "stale")       # the Frankfurt VPN
    for s, k in (("London", 5), ("Madrid", 2), ("Milan", 2)):
        pick(k, lambda d, st=s: main(d) and d["site"] == st, "stale")
    pick(38, lambda d: main(d) and d["model"] == ELITE, "failed", err="0X800F0922")
    for code, k in (("0X80070002", 6), ("0X800F081F", 4), ("0X80073712", 3), ("0X80070070", 5), ("0X8024402C", 3)):
        pick(k, lambda d: main(d) and d["model"] != ELITE, "failed", err=code)
    for s, k, cond in (("London", 48, lambda d: True), ("Frankfurt", 17, lambda d: True), ("Milan", 15, lambda d: d.get("legacy")),
                       ("Milan", 10, lambda d: not d.get("legacy"))):
        pick(k, lambda d, st=s, c=cond: main(d) and d["site"] == st and c(d), "restart")
    pick(18, main, "late")
    for d in (sorted([x for x in devs if x["plan"] == "restart"], key=lambda x: x["name"])[::4]
              + sorted([x for x in devs if x["plan"] == "late"], key=lambda x: x["name"])[::2]):
        d["chronic"] = True
    pilot = lambda d: d["ring"] == R1 and not d.get("conflict")  # noqa: E731
    pick(3, pilot, "restart")
    pick(2, pilot, "failed", err="0X800F081F")
    pick(2, pilot, "late")
    pick(5, lambda d: d.get("conflict"), "late")
    pick(18, lambda d: d.get("new"), "noring")
    # versions: 34 on 23H2 (end of servicing 10 Nov 2026), 210 on 24H2, six testing 26H2 in ring 0
    for d in pick(34, lambda d: main(d) and d["model"] in (OPTI, LAT54) and d["site"] != "Frankfurt", "ok23"):
        d["build"] = 22631
    for k, d in enumerate(sorted([x for x in devs if x["plan"] == "ok23"], key=lambda x: x["name"])):
        d["feature"] = "hold" if k % 3 == 0 else "fail" if k % 6 == 1 else "progress"
    pool = sorted([d for d in devs if d["ring"] in (R2, "") and d["build"] == 26200 and d["cat"] != "Trading desktop"], key=lambda d: d["name"])
    rnd.shuffle(pool)
    for d in pool[:210]:
        d["build"] = 26100
    for d in sorted([d for d in devs if d["ring"] == R0], key=lambda d: d["name"])[:6]:
        d["build"] = 26300
    for d in devs:
        if d["plan"] == "ok23":
            d["plan"] = "ok"


def policy_of(d: dict) -> tuple[int, int, int]:
    """(deferral, deadline, grace) the device actually gets."""
    if d.get("cm"):
        return 7, 14, 0
    if d.get("legacy"):
        return 7, 7, 3
    return {R0: (0, 2, 1), R1: (3, 3, 2), R2: (10, 5, 2), R3: (21, 5, 2), "": (0, 0, 0)}[d["ring"]]


def install_day(rnd: random.Random, d: dict, month: str) -> date | None:
    rel = REL[month]
    dfr, dl, gr = policy_of(d)
    offer = rel + timedelta(days=dfr)
    if d["ring"] == R3 and month != "2026-08":
        return None                                      # paused since 28 September
    mean = {"2026-08": 1.5, "2026-09": 1.9, "2026-10": 2.4}[month]
    late_p = {"2026-08": 0.02, "2026-09": 0.06, "2026-10": 0.0}[month]
    if d["chronic"] or rnd.random() < late_p:
        return offer + timedelta(days=dl + gr + rnd.randint(2, 12))
    if d.get("conflict") and month == "2026-10":
        return rel + timedelta(days=rnd.randint(4, 12))
    if d["ring"] == R1 and month == "2026-10":
        # the October pilot was slow: about 70% installed when the broad ring was offered on 23 October
        return offer + timedelta(days=rnd.choice([0, 0, 1, 1, 2, 2, 3, 3, 4, 5, 6, 9, 11]))
    if d["ring"] == "" and month == "2026-10":
        return rel + timedelta(days=rnd.randint(0, 5))
    if d["ring"] == R0:
        delay = rnd.choice([0, 0, 0, 1, 1, 2])
    elif d.get("cm") and month == "2026-10":
        delay = rnd.randint(0, 20)                       # the Madrid deployment has a 14-day deadline
    else:
        delay = min(int(rnd.expovariate(1 / mean)), dl + gr)
    return offer + timedelta(days=delay)


def history(rnd: random.Random, devs: list[dict]) -> dict:
    """Status rows for August to October and the build each device ends on."""
    rows, last_installed = [], {}
    for d in sorted(devs, key=lambda d: d["name"]):
        b = d["build"]
        on = ("2026-07", False)
        scan = AS_OF - timedelta(hours=rnd.randint(1, 40))
        if d["plan"] == "stale":
            scan = datetime(2026, 10, rnd.randint(19, 22), rnd.randint(8, 18), rnd.randint(0, 59))
        d["last_scan"] = scan
        for month in ("2026-08", "2026-09", "2026-10"):
            if d["new"] and month != "2026-10":
                on = ("2026-09", True)
                continue
            rel = REL[month]
            kb = KB.get(month, {}).get(b, KB_DEFAULT[month])
            rb, ro = REV[month][b]
            tgt = f"10.0.{b}.{rb}"
            day = install_day(rnd, d, month)
            state, sub, err, alert, rr, inst = "Installed", "Installed", "", "", None, None
            if month == "2026-10":
                dfr, dl, gr = policy_of(d)
                offer = rel + timedelta(days=dfr)
                plan = d["plan"]
                if d["ring"] == R3:
                    state, sub, day = "OnHold", "OnHold", None
                elif plan == "stale":
                    state, sub, day = "Unknown", "Unknown", None
                elif plan == "failed":
                    state, sub, err, alert, day = "Installing", "Installing", d["err"], ALERT.get(d["err"], "InstallIssue"), None
                elif plan == "restart":
                    rr = _at(rnd, offer + timedelta(days=rnd.randint(0, 3)))
                    state, sub, day = "Installing", "RestartRequired", None
                elif plan in ("late", "noring"):
                    state, sub, day = "Offering", "DownloadStart" if rnd.random() < 0.5 else "Offering", None
                elif d.get("cm") and day and day > AS_OF.date() - timedelta(days=1):
                    state, sub, day = "Installing", "DownloadStart", None
                elif day and day >= AS_OF.date():
                    day = AS_OF.date() - timedelta(days=1)
            elif d["plan"] == "failed" and d["err"] in ("0X80073712", "0X800F081F") and month == "2026-09":
                state, sub, err, alert, day = "Installing", "Installing", d["err"], ALERT[d["err"]], None   # the same devices failed in September
            elif day is None:
                state, sub = "OnHold", "OnHold"
            elif day >= AS_OF.date():
                day = AS_OF.date() - timedelta(days=1)
            if day:
                inst = _at(rnd, day)
                on = (month, month in OOB and day >= OOB[month])
            rows.append([d["name"], d["aad"], "WindowsQualityUpdate", f"{rel:%Y-%m-%d}", VER[b], tgt, kb, state, sub, _t(rr), _t(inst), err.lower()
                         if err else "", alert, _t(scan)])
            last_installed[d["name"]] = on
        m, oob = on
        rb, ro = REV[m][b]
        d["os"] = f"10.0.{b}.{ro if oob else rb}"
        if d.get("feature"):
            f = d["feature"]
            rows.append([d["name"], d["aad"], "WindowsFeatureUpdate", "2025-09-30", "25H2", "10.0.26200.6584", "", "OnHold" if f == "hold" else
                         "Installing", "OnHold" if f == "hold" else "Installing" if f == "fail" else "DownloadStart",
                         "", "", "0xc1900101" if f == "fail" else "", "SafeguardHold" if f == "hold" else "InstallSetupError" if f == "fail" else "",
                         _t(scan)])
    return {"rows": rows}


def write(folder: Path) -> Path:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(SEED)
    devs = fleet(rnd)
    assign(rnd, devs)
    plant(rnd, devs)
    h = history(rnd, devs)
    out = {"dev": [], "pol": [], "st": h["rows"], "rel": [], "inc": []}
    for d in sorted(devs, key=lambda d: d["name"]):
        if d["plan"] == "stale":
            sync = d["last_scan"] + timedelta(hours=rnd.randint(1, 30))
        else:
            sync = AS_OF - timedelta(minutes=rnd.randint(20, 60 * 50))
        out["dev"].append([d["name"], d["id"], d["aad"], d["os"], d["model"], MAKER[d["model"]], _t(sync), d["upn"], d["dept"], d["site"], d["cat"],
                           "configurationManagerClientMdm", d["wufb"], ";".join(d["groups"])])
    for k, (name, src, grp, qd, fd, dl, fdl, gr, paused, ps, pe, mod) in enumerate(POLICIES):
        out["pol"].append([name, f"{0x5a1e0000 + k:08x}-0000-4000-8000-0000000000{k:02d}", src, grp, qd, fd, "" if dl is None else dl,
                           "" if fdl is None else fdl, "" if gr is None else gr, str(paused).lower(), ps, pe, "false", mod])
    for v, b, eos in VERSIONS:
        out["rel"].append(["version", "", v, b, "", "", "", eos, "", "", "", "", ""])
    for m, v, b, kb, rd, typ in BUILDS:
        out["rel"].append(["build", m, v, b, f"KB{kb}", rd, typ, "", "", "", "", "", ""])
    for title, vers, kb, status, opened, resolved, blocks in ISSUES:
        out["rel"].append(["issue", "", vers, "", f"KB{kb}", "", "", "", title, status, opened, resolved, blocks])
    out["inc"] = [list(x) for x in INCIDENTS]
    for name, (k, header) in FILES.items():
        with open(folder / name, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow(header)
            w.writerows(out[k])
    (folder / "settings.json").write_text(json.dumps(SETTINGS, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return folder
