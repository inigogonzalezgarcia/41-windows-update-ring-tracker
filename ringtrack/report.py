"""Outputs: report.html (with the ring timeline of the month and its gates), rollout-pack.md (the monthly patch meeting or CAB pack), and the
CSVs: devices behind, rings, gates, failures, composition, trend, actions and findings."""
from __future__ import annotations

import csv
import html
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from .checks import AREAS, CRITICAL, INFO, NO_RING, VERDICT, WARNING, Finding, area_status, error_name, now_label, overall, pct, summary
from .model import FILES, Data, Policy

e = html.escape
ACTION = {
    "no ring": "Add to the ring group for its role",
    "ring paused": "Decide on the pause of its ring",
    "not checked in": "Get it online (VPN, proxy) and let it sync",
    "failed": "Fix by error code (failures.csv)",
    "restart pending": "Ask the user to restart today",
    "past deadline": "Check scan and download in the report",
    "version not serviced": "Feature update to the target version",
    "in window": "None yet: inside its ring's deadline and grace",
    "not offered yet": "None yet: its ring has not been offered the update",
}
REASONS = ("restart pending", "failed", "not checked in", "past deadline", "no ring", "ring paused", "version not serviced")


def _g(x) -> str:
    return "–" if x is None else f"{x:g}"


def _pol(p: Policy) -> str:
    dl = "–" if p.deadline is None else p.deadline
    gr = "–" if p.grace is None else p.grace
    return f"{p.name} ({p.source}): defer {p.quality_deferral}, deadline {dl}, grace {gr}" + (", PAUSED" if p.paused else "")


# ---------------------------------------------------------------- csv

def _w(path: Path, header: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def _t(v) -> str:
    if not v:
        return ""
    return v.strftime("%Y-%m-%d %H:%M") if isinstance(v, datetime) else v.strftime("%Y-%m-%d")


def _iss(issues) -> str:
    return " | ".join(f"{i.code} {i.text}" for i in issues)


def _f(x, k=3) -> str:
    return "" if x is None else f"{x:.{k}f}"


def write_findings(findings: list[Finding], path: Path) -> None:
    _w(path, ["severity", "area", "code", "subject", "detail", "next_step", "owner", "items"],
       [[f.severity, f.area, f.code, f.subject, f.detail, f.fix, f.owner, "; ".join(f.items)] for f in findings])


def write_actions(findings: list[Finding], path: Path) -> None:
    _w(path, ["ref", "action", "next_step", "owner", "severity", "due", "done"],
       [[f.code, f.subject, f.fix, f.owner, f.severity, "", ""] for f in findings if f.severity != INFO])


def _flags(r: dict) -> str:
    out = []
    if len(r["rings"]) > 1:
        out.append("two rings")
    if r["drift"]:
        out.append("policy differs from standard")
    if r["fst"] and r["fst"].safeguard and not r["fst"].is_installed:
        out.append("safeguard hold")
    return "; ".join(out)


def write_devices(d: Data, rv: dict, path: Path) -> None:
    s = d.settings
    rows = []
    for r in sorted((r for r in rv["devices"] if not r["current"]), key=lambda r: (not r["behind"], r["dev"].site, r["reason"], r["dev"].name)):
        dev, st = r["dev"], r["st"]
        code = st.error if st and st.error and not st.is_installed else ""
        rows.append([dev.name, dev.upn, dev.site, s.site_owners.get(dev.site, ""), dev.department, dev.category, dev.model, r["ring"],
                     r["policy"].name if r["policy"] else "", dev.os_version, r["version"], r["expected"], r["reason"], "yes" if r["behind"] else "no",
                     code, error_name(d, code) if code else "", _t(st.restart_required) if st else "", _t(dev.last_sync), _t(st.last_scan) if st else "",
                     r["past"] or "", _flags(r), ACTION.get(r["reason"], "")])
    _w(path, ["deviceName", "userPrincipalName", "site", "site_owner", "department", "category", "model", "ring", "policy", "osVersion", "version",
              "expected_build", "reason", "behind", "error_code", "error_name", "restart_required_since", "last_sync", "last_wu_scan",
              "days_past_grace", "flags", "action"], rows)


def write_rings(d: Data, rv: dict, path: Path) -> None:
    rows = []
    for r in rv["rings"]:
        p, dt = r["main"], r["dates"] or {}
        rows.append([r["ring"], r["order"], "; ".join(f"{x.name} ({x.source})" for x in r["policies"]), r["devices"], _f(r["share"]),
                     _f(r["target"]), p.quality_deferral if p else "", "" if not p or p.deadline is None else p.deadline,
                     "" if not p or p.grace is None else p.grace, "yes" if r["paused"] else "no", _t(dt.get("offer")), _t(dt.get("deadline")),
                     _t(dt.get("grace_end")), r["current"], _f(r["compliance"]), r["behind"], r["restart"], r["failed"], r["stale"], r["window"],
                     "" if r["median"] is None else r["median"], r["verdict"], _iss(r["issues"])])
    _w(path, ["ring", "order", "policies", "devices", "share_of_fleet", "target_share", "quality_deferral_days", "deadline_days", "grace_days", "paused",
              "offer", "deadline", "grace_end", "current", "compliance", "behind", "restart_pending", "failed", "not_checked_in", "in_window",
              "median_days_to_install", "verdict", "issues"], rows)


def write_gates(d: Data, rv: dict, path: Path) -> None:
    s = d.settings
    _w(path, ["from_ring", "to_ring", "offer_date", "state", "compliance", "gate_compliance", "failure_rate", "gate_failure_max", "soak_days",
              "incidents", "known_issues", "result", "reasons"],
       [[g["prev"], g["nxt"], _t(g["when"]), g["state"], _f(g["compliance"]), s.gate_compliance, _f(g["failure"]), s.gate_failure_max, g["soak"],
         "; ".join(i.number for i in g["incidents"]), "; ".join(k.title for k in g["known"]), "GO" if g["go"] else "NO-GO", " | ".join(g["reasons"])]
        for g in rv["gates"]])


def write_failures(d: Data, rv: dict, path: Path) -> None:
    m = rv["month"]["month"]
    _w(path, ["month", "category", "error_code", "error_name", "devices", "top_model", "top_model_devices", "top_model_failure_share", "sites", "rings",
              "verdict", "issues"],
       [[m, r["category"], r["code"], r["name"], len(r["rows"]), r["model"], r["model_count"], _f(r["model_share"]),
         "; ".join(f"{k} {v}" for k, v in r["sites"].most_common()), "; ".join(f"{k} {v}" for k, v in r["rings"].most_common()), r["verdict"],
         _iss(r["issues"])] for r in rv["failures"]])


def write_composition(d: Data, rv: dict, path: Path) -> None:
    s = d.settings
    by = defaultdict(list)
    for r in rv["devices"]:
        by[r["ring"]].append(r)
    broad = by.get(s.broad_ring, [])
    dims = (("department", lambda r: r["dev"].department), ("site", lambda r: r["dev"].site), ("model", lambda r: r["dev"].model),
            ("category", lambda r: r["dev"].category), ("version", lambda r: r["version"]))
    rows = []
    for ring in s.ring_names() + [NO_RING]:
        rs = by.get(ring, [])
        for dim, get in dims:
            c = Counter(get(r) for r in rs)
            bc = Counter(get(r) for r in broad)
            for v, n in sorted(c.items(), key=lambda kv: (-kv[1], kv[0])):
                rows.append([ring, dim, v, n, _f(n / len(rs)), _f(bc.get(v, 0) / len(broad)) if broad else ""])
    _w(path, ["ring", "dimension", "value", "devices", "share_of_ring", "share_of_broad_ring"], rows)


def write_trend(d: Data, rv: dict, path: Path) -> None:
    tr = rv["trend"]
    _w(path, ["month", "release_date", "ring", "devices", "installed"] + [f"share_day_{x}" for x in tr["days"]] + ["median_days_to_install"],
       [[r["month"], _t(r["release"]), r["ring"], r["devices"], r["installed"]] + [_f(r["shares"][x]) for x in tr["days"]]
        + ["" if r["median"] is None else r["median"]] for r in tr["rows"]])


# ---------------------------------------------------------------- the pack

TODO = "**[TO COMPLETE]**"


def _md(x: str) -> str:
    return str(x).replace("|", "/")


def chase(rv: dict) -> list[tuple[str, Counter, int]]:
    by = defaultdict(Counter)
    for r in rv["devices"]:
        if r["behind"]:
            by[r["dev"].site or "(no site)"][r["reason"]] += 1
    return sorted(((k, c, sum(c.values())) for k, c in by.items()), key=lambda x: (-x[2], x[0]))


def _med(tr: dict, month: str, ring: str) -> str:
    r = next((x for x in tr["rows"] if x["month"] == month and x["ring"] == ring), None)
    return _g(r["median"] if r else None)


def _gate_table(d: Data, g: dict) -> list[str]:
    s = d.settings
    ok_c = g["compliance"] is not None and g["compliance"] >= s.gate_compliance
    return ["| Condition | Value | Gate | Met |", "|---|---|---|---|",
            f"| {g['prev']} on the build | {pct(g['compliance'])} | {pct(s.gate_compliance)} | {'yes' if ok_c else 'no'} |",
            f"| {g['prev']} failing | {pct(g['failure'])} | max {pct(s.gate_failure_max)} | {'yes' if g['failure'] <= s.gate_failure_max else 'no'} |",
            f"| Days since {g['prev']} was offered | {g['soak']} | min {s.gate_min_soak_days} | {'yes' if g['soak'] >= s.gate_min_soak_days else 'no'} |",
            f"| Open P1/P{s.gate_incident_max_priority} incidents on the update | {', '.join(i.number for i in g['incidents']) or 'none'} | none | "
            f"{'no' if g['incidents'] else 'yes'} |",
            f"| Known issues that block this ring | {_md('; '.join(k.title for k in g['known'])) or 'none'} | none | {'no' if g['known'] else 'yes'} |"]


def pack_md(d: Data, rv: dict, findings: list[Finding], title: str) -> str:
    s, sm, st = d.settings, summary(d, rv), area_status(findings)
    mi, tr = rv["month"], rv["trend"]
    out = [f"# {title}", "",
           f"> Generated by ringtrack on {now_label(d.as_of)} from the exports listed under *Scope and evidence*. Read-only: nothing was changed in "
           f"Intune or Configuration Manager. Sections marked {TODO} are for the patch meeting.", "",
           f"**Overall: {overall(findings).upper()}**", "", "| Area | Status | To act on |", "|---|---|---|"]
    for a in AREAS:
        n = sum(f.area == a and f.severity != INFO for f in findings)
        out.append(f"| {a} | {'ON TRACK' if st[a] == 'ok' else VERDICT[st[a]].upper()} | {n} |")
    nxt = sm["next"]
    why = f" Reasons: {'; '.join(nxt['reasons'])}." if nxt and not nxt["go"] else ""
    out += ["", "## Headlines", "",
            f"- {mi['month']} update ({sm['kb']}, released {mi['release']:%a %d %b}), day {sm['days']}: {sm['current']} of {sm['devices']} devices on the "
            f"build ({pct(sm['current_share'])}); {sm['behind']} behind, {sm['window']} still inside their ring's deadline and grace.",
            f"- Behind: {sm['restart']} restart pending, {sm['failed']} failed, {sm['stale']} not checked in, {sm['reasons'].get('past deadline', 0)} past "
            f"the deadline, {sm['reasons'].get('ring paused', 0)} in a paused ring, {sm['reasons'].get('no ring', 0)} with no ring.",
            f"- Next promotion: {sm['next_gate'] or 'none this month'}.{why}",
            f"- Promotions this month without a met gate: {sm['promoted_bad']}; paused rings: {', '.join(sm['paused']) or 'none'}.",
            f"- Rings: {sm['no_ring']} devices in no ring, {sm['two_rings']} in two, {sm['drift']} under a policy that differs from the standard; "
            f"{sm['vip_wrong']} trading desktops outside the late ring.",
            "- Share on the build at day 14: " + ", ".join(f"{m} {pct(x)}" for m, x in sm["trend14"]) + f"; {sm['repeat']} devices behind every month.",
            "", "## Scope and evidence", "", f"- Organisation: {s.organisation}", f"- Reference date: {d.as_of:%a %d %b %Y %H:%M}",
            f"- Update month: {mi['month']}; expected builds: " + ", ".join(f"{d.version_of(b)} {b}.{r}" for b, r in sorted(mi["expected"].items())), "",
            "| Source | File | Records |", "|---|---|---|"]
    out += [f"| {FILES.get(k, k)} | `{k}` | {v} |" for k, v in d.sources.items()]
    # 1 rings
    out += ["", "## 1. Status by ring", "", "| Ring | Devices | Offer | Deadline + grace | On the build | Behind | Restart | Failed | Not checked in | "
            "In window | Status |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rv["rings"]:
        dt = r["dates"] or {}
        out.append(f"| {r['ring']}{' (paused)' if r['paused'] else ''} | {r['devices']} | {_t(dt.get('offer'))} | {_t(dt.get('grace_end'))} | "
                   f"{pct(r['compliance'])} | {r['behind']} | {r['restart']} | {r['failed']} | {r['stale']} | {r['window']} | {r['verdict'].upper()} |")
    # 2 go / no-go
    out += ["", "## 2. Go/no-go for the next promotion", ""]
    if nxt:
        out += [f"**{nxt['nxt']}**, due on {nxt['when']:%a %d %b %Y}: **{'GO' if nxt['go'] else 'NO-GO'}**", ""] + _gate_table(d, nxt)
        out += ["", f"Decision: {TODO} (promote / pause the ring / move the deferral) · Decided by: {TODO}"]
    else:
        out.append("No promotion left this month.")
    out += ["", "## 3. Gates this month", "", "| From | To | Offered | State | Result | Reasons |", "|---|---|---|---|---|---|"]
    for g in rv["gates"]:
        out.append(f"| {g['prev']} | {g['nxt']} | {_t(g['when'])} | {g['state']} | {'GO' if g['go'] else 'NO-GO'} | {_md('; '.join(g['reasons'])) or '–'} |")
    # 4 chase
    out += ["", "## 4. Devices to chase by site", "", "| Site | Owner | Behind | " + " | ".join(x.capitalize() for x in REASONS) + " |",
            "|---|---|---|" + "---|" * len(REASONS)]
    for site, c, n in chase(rv):
        out.append(f"| {site} | {s.site_owners.get(site, '–')} | {n} | " + " | ".join(str(c.get(x, 0)) for x in REASONS) + " |")
    out += ["", "Every device with its user, reason, error and action is in `devices-behind.csv`; filter it by site for each local team.", ""]
    for r in rv["device_rows"]:
        for i in r["issues"]:
            out.append(f"- **{i.code}** {_md(i.text)}")
    # 5 failures
    out += ["", "## 5. Failure codes", "", "| Update | Code | Meaning | Devices | Top model | Model devices failing | Status |", "|---|---|---|---|---|---|---|"]
    for r in rv["failures"]:
        out.append(f"| {r['category']} | {r['code']} | {_md(r['name']) or '–'} | {len(r['rows'])} | {r['model']} | {r['model_count']} ({pct(r['model_share'])}) | "
                   f"{r['verdict'].upper()} |")
    rep = [r for r in rv["failure_extra"] if r["kind"] == "FAIL-03"]
    if rep:
        out += ["", f"- **FAIL-03** {_md(rep[0]['issues'][0].text)}"]
    # 6 feature updates
    out += ["", "## 6. Versions and feature updates", "", f"Target version: {s.feature_target or '–'}.", "",
            "| Version | Build | Devices | End of servicing (Enterprise) | Days left |", "|---|---|---|---|---|"]
    vc = Counter(r["build"] for r in rv["devices"])
    for v in sorted(d.versions.values(), key=lambda v: v.build):
        if vc.get(v.build):
            left = (v.end_of_servicing - d.today).days if v.end_of_servicing else "–"
            out.append(f"| {v.version} | {v.build} | {vc[v.build]} | {_t(v.end_of_servicing) or '–'} | {left} |")
    fu = [r for r in rv["devices"] if r["fst"] and not r["fst"].is_installed]
    if fu:
        c = Counter("safeguard hold" if r["fst"].safeguard else (f"failed {r['fst'].error}" if r["fst"].error else "in progress") for r in fu)
        out += ["", "Feature update status: " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())) + "."]
    # 7 composition
    cp = rv["composition"]
    out += ["", "## 7. Ring composition", "", "| Ring | Devices | Share | Target | Top departments | Sites |", "|---|---|---|---|---|---|"]
    for r in rv["rings"]:
        dc = Counter(x["dev"].department for x in r["rows"]).most_common(3)
        sc = Counter(x["dev"].site for x in r["rows"]).most_common()
        out.append(f"| {r['ring']} | {r['devices']} | {pct(r['share'])} | {pct(r['target'])} | {', '.join(f'{k} {v}' for k, v in dc)} | "
                   f"{', '.join(f'{k} {v}' for k, v in sc)} |")
    out.append("")
    out += [f"- **{i.code}** {_md(i.text)}" for i in cp["issues"]]
    # 8 trend
    out += ["", "## 8. Trend", "", "| Month | Released | Devices | " + " | ".join(f"Day {x}" for x in tr["days"]) + " | Median days |",
            "|---|---|---|" + "---|" * len(tr["days"]) + "---|"]
    for r in tr["all"]:
        out.append(f"| {r['month']} | {_t(r['release'])} | {r['devices']} | " + " | ".join(pct(r["shares"][x]) for x in tr["days"]) + f" | {_g(r['median'])} |")
    out += ["", "Median days from Patch Tuesday to install, by ring:", "", "| Ring | " + " | ".join(tr["months"]) + " |",
            "|---|" + "---|" * len(tr["months"])]
    for rg in s.ring_names():
        out.append(f"| {rg} | " + " | ".join(_med(tr, m, rg) for m in tr["months"]) + " |")
    out.append("")
    out += [f"- **{i.code}** {_md(i.text)}" for i in tr["issues"]]
    # 9 release health and incidents
    out += ["", "## 9. Known issues and incidents", "", "| Known issue (Windows release health) | Originating KB | Status | Opened | Resolved | Blocks |",
            "|---|---|---|---|---|---|"]
    for k in sorted(d.issues, key=lambda k: (k.opened or datetime.min, k.title), reverse=True):
        out.append(f"| {_md(k.title)} | KB{k.kb} | {k.status} | {_t(k.opened)} | {_t(k.resolved) or '–'} | {', '.join(k.blocks) or '–'} |")
    out += ["", "| Incident | P | Opened | Update | Ring | Devices | Rolled back | Resolved |", "|---|---|---|---|---|---|---|---|"]
    for i in sorted(d.incidents, key=lambda i: (i.opened or datetime.min, i.number)):
        out.append(f"| {i.number} {_md(i.short_description)} | {i.priority} | {_t(i.opened)} | KB{i.kb} | {i.ring or '–'} | {i.devices} | "
                   f"{'yes' if i.rollback else 'no'} | {_t(i.resolved) or 'open'} |")
    out += ["", "## Findings", ""]
    for f in findings:
        if f.severity == INFO:
            continue
        out += [f"### {f.code} · {f.subject} ({f.severity})", "", _md(f.detail), "", f"Next step: {f.fix} Owner: {f.owner}.", ""]
    out += ["## Actions", "", "| Ref | Action | Next step | Owner | Due |", "|---|---|---|---|---|"]
    out += [f"| {f.code} | {_md(f.subject)} | {f.fix} | {f.owner} | {TODO if f.severity == CRITICAL else ''} |" for f in findings if f.severity != INFO]
    out += ["", "## Notes", "",
            "- A device is on the build when its OS build revision (the last part of osVersion) is the month's Patch Tuesday revision or later; "
            "the out-of-band and preview updates of the month count.",
            "- The ring of a device comes from the groups (or ConfigMgr collections) its update ring policies are assigned to; co-managed devices "
            "with the Windows Update workload in Configuration Manager take the ConfigMgr deployments, the others the Intune rings.",
            "- Offer = Patch Tuesday + the quality deferral (later if the ring is paused); a device is behind only after its own deadline and grace, "
            "unless it has no ring, its ring is paused, it has not checked in or the update failed.",
            f"- A gate is met when the previous ring is at {pct(s.gate_compliance)} or more on the build, fails under {pct(s.gate_failure_max)}, was offered "
            f"at least {s.gate_min_soak_days} days before, and no P1/P{s.gate_incident_max_priority} incident on the update or blocking known issue is open. "
            "Gates already passed use the install times up to the offer date; the failure rate is today's.",
            "- Trend: share of the devices with a status record for the month that had installed the update by day 7, 14 and 21 after Patch Tuesday.",
            f"- Decisions of the meeting: {TODO}", "",
            "## Sign-off", "", f"- Prepared by (endpoint engineering): {TODO}", f"- Approved by (change advisory board): {TODO}", f"- Date: {TODO}", ""]
    return "\n".join(out)


# ---------------------------------------------------------------- html

CSS = """
:root{--bg:#f6f7f8;--card:#fff;--ink:#1b2128;--muted:#66717c;--line:#e2e5e9;--ok:#1e7a4c;--warn:#a46200;--bad:#b42318;--info:#0b6bcb;--bar:#3d6fb4;--frz:#eef1f6;--dl:#cfe0f5;--gr:#f6e3c2}
@media (prefers-color-scheme:dark){:root{--bg:#13171b;--card:#1b2127;--ink:#e7eaee;--muted:#9aa5b0;--line:#2b333b;--ok:#4cc38a;--warn:#f0a83a;--bad:#f2685c;--info:#5aa9f0;--bar:#6c9be0;--frz:#232b35;--dl:#24405f;--gr:#5a4423}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1100px;margin:0 auto;padding:28px 18px 60px}h1{font-size:26px;margin:0 0 4px}h2{font-size:18px;margin:34px 0 12px}
.muted{color:var(--muted)}.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin-top:20px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}.tile b{display:block;font-size:26px}
.overall{display:inline-block;margin-top:14px;padding:6px 14px;border-radius:99px;font-weight:700;border:2px solid currentColor}
.areas{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.area{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--ok);border-radius:10px;padding:10px 14px}
.area.critical{border-left-color:var(--bad)}.area.warning{border-left-color:var(--warn)}
.area .lbl{display:block;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin-bottom:4px}.area .cnt{display:block;font-size:13px;color:var(--muted);margin-top:4px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
tr:last-child td{border-bottom:0}.wrap{overflow-x:auto}.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.pill{display:inline-block;white-space:nowrap;padding:1px 8px;border-radius:99px;font-size:12px;font-weight:600;border:1px solid currentColor}
.critical{color:var(--bad)}.warning{color:var(--warn)}.info{color:var(--info)}.ok{color:var(--ok)}
.area.critical,.area.warning,.area.ok{color:inherit}
.pill.on-track,.pill.go{color:var(--ok)}.pill.attention{color:var(--warn)}.pill.action-needed,.pill.no-go{color:var(--bad)}
td.subj{min-width:190px}td.nw{white-space:nowrap}td.fix{font-size:13px;color:var(--muted);min-width:200px;max-width:380px}td.sm{font-size:13px}
.brk{overflow-wrap:anywhere;word-break:break-word}
table.tl{table-layout:fixed;min-width:980px}table.tl th,table.tl td{padding:4px 0;font-size:11px;text-align:center;border-left:1px solid var(--line);vertical-align:middle}
table.tl th.rg,table.tl td.rg{width:190px;text-align:left;padding-left:8px;font-size:12px}table.tl th.we{background:var(--frz)}
table.tl td.dl{background:var(--dl)}table.tl td.gr{background:var(--gr)}table.tl td.pz{background:repeating-linear-gradient(135deg,var(--frz),var(--frz) 4px,transparent 4px,transparent 8px)}
table.tl .today{outline:2px solid var(--ink);outline-offset:-2px}table.tl .gate{font-weight:700;font-size:15px}
.legend span{margin-right:14px;font-size:13px}.sw{display:inline-block;width:14px;height:10px;border-radius:2px;margin-right:4px;vertical-align:middle}
.bars{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;align-items:end;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 16px 12px;margin-bottom:12px}
.col{display:flex;flex-direction:column;align-items:stretch;text-align:center;font-size:13px}.col .b{background:var(--bar);border-radius:4px 4px 0 0;min-height:2px}
.col .b.over{background:var(--bad)}.col .v{font-variant-numeric:tabular-nums;font-weight:600;margin-bottom:4px}.col .k{color:var(--muted);margin-top:6px}
footer{margin-top:40px;font-size:13px}
"""


def _pill(cls: str, text: str) -> str:
    return f"<span class='pill {cls}'>{e(text)}</span>"


def _vpill(v: str) -> str:
    return _pill(v.replace(" ", "-"), v.upper())


def _issues(issues) -> str:
    xs = sorted(issues, key=lambda x: (x.severity != CRITICAL, x.severity == INFO))
    return "<br>".join(f"<span class='{x.severity}'>●</span> <b>{e(x.code)}</b> {e(x.text)}" for x in xs) or "<span class='muted'>–</span>"


def _table(head: list[str], rows: list[str]) -> str:
    return "<div class='wrap'><table><tr>" + "".join(f"<th>{e(h)}</th>" for h in head) + "</tr>" + "".join(rows) + "</table></div>"


def _sect(h: list, n: int, title: str, area: str | None, st: dict, note: str) -> None:
    pill = _vpill("on track" if st[area] == "ok" else VERDICT[st[area]]) if area else ""
    h.append(f"<h2>{n}. {e(title)} {pill}</h2><p class='muted'>{e(note)}</p>")


def _counts(c: Counter, k: int | None = None) -> str:
    return ", ".join(f"{a} {b}" for a, b in c.most_common(k))


def timeline(d: Data, rv: dict) -> str:
    rel = rv["month"]["release"]
    ends = [r["dates"]["grace_end"] for r in rv["rings"] if r["dates"]] + [d.today + timedelta(days=7)]
    last = min(max(ends), rel + timedelta(days=34))
    days = [rel - timedelta(days=1) + timedelta(days=k) for k in range((last - rel).days + 2)]
    gate_at = {(g["nxt"], g["when"]): g for g in rv["gates"]}
    head = ("<tr><th class='rg'>Ring</th>" + "".join(f"<th class='{'we' if x.weekday() >= 5 else ''}{' today' if x == d.today else ''}'>"
                                                   f"{x:%a}<br>{x.day}{'<br>PT' if x == rel else ''}</th>" for x in days) + "</tr>")
    rows = []
    for r in rv["rings"]:
        dt = r["dates"]
        if not dt:
            continue
        pz = [p for p in r["policies"] if p.paused and p.pause_start]
        tds = []
        for x in days:
            cls = []
            if any(p.pause_start.date() <= x < (p.pause_expiry.date() if p.pause_expiry else x + timedelta(days=1)) for p in pz):
                cls.append("pz")
            elif dt["offer"] <= x <= dt["deadline"]:
                cls.append("dl")
            elif dt["deadline"] < x <= dt["grace_end"]:
                cls.append("gr")
            if x == d.today:
                cls.append("today")
            g = gate_at.get((r["ring"], x))
            mark = ""
            if g:
                tip = "GO" if g["go"] else "NO-GO: " + "; ".join(g["reasons"])
                mark = f"<span class='gate {'ok' if g['go'] else 'critical'}' title='{e(tip)}'>◆</span>"
            elif x == dt["offer"]:
                mark = "<span class='gate muted'>▸</span>"
            tds.append(f"<td class='{' '.join(cls)}'>{mark}</td>")
        rows.append(f"<tr><td class='rg'><b>{e(r['ring'])}</b><br><span class='muted'>{r['devices']} devices · {pct(r['compliance'])} on the build"
                    f"{' · paused' if r['paused'] else ''}</span></td>{''.join(tds)}</tr>")
    legend = ("<p class='legend muted'><span><span class='sw' style='background:var(--dl)'></span>offer to deadline</span>"
              "<span><span class='sw' style='background:var(--gr)'></span>grace period</span><span>hatched: paused</span>"
              "<span><b class='ok'>◆</b> gate met · <b class='critical'>◆</b> gate not met (hover for the reasons)</span><span>PT: Patch Tuesday · "
              "framed column: today</span></p>")
    return legend + "<div class='wrap'><table class='tl'>" + head + "".join(rows) + "</table></div>"


def render_html(d: Data, rv: dict, findings: list[Finding], title: str) -> str:
    s, sm, st = d.settings, summary(d, rv), area_status(findings)
    ov = overall(findings)
    mi, tr, cp = rv["month"], rv["trend"], rv["composition"]
    nxt = sm["next"]
    h = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
         f"<title>{e(title)}</title><style>{CSS}</style></head><body><main>",
         f"<h1>{e(title)}</h1><p class='muted'>The {mi['month']} update ({e(sm['kb'])}, released {mi['release']:%a %d %b}) through the rings, day "
         f"{sm['days']} · as of {now_label(d.as_of)}</p>",
         f"<span class='overall {'critical' if ov == 'action needed' else 'warning' if ov == 'attention' else 'ok'}'>Overall: {e(ov.upper())}</span>"
         "<div class='tiles'>"]
    eos = [x for x in rv["device_rows"] if x["kind"] == "DEV-06"]
    t14 = sm["trend14"]
    tiles = [("On the build", pct(sm["current_share"]), f"{sm['current']} of {sm['devices']} devices"),
             ("Behind", str(sm["behind"]), f"{sm['window']} more still in their window"),
             ("Restart pending", str(sm["restart"]), "past the deadline and grace"),
             ("Failed", str(sm["failed"]), f"{sm['failure_codes']} error codes"),
             ("Not checked in", str(sm["stale"]), f"for more than {s.stale_days} days"),
             ("No ring / two rings", f"{sm['no_ring']} / {sm['two_rings']}", f"{sm['drift']} under a non-standard policy"),
             ("Next promotion", ("GO" if nxt["go"] else "NO-GO") if nxt else "–", f"{nxt['nxt']}, {nxt['when']:%a %d %b}" if nxt else "none left"),
             ("Paused rings", str(len(sm["paused"])), ", ".join(sm["paused"]) or "none"),
             ("Day 14 on the build", pct(t14[-1][1]) if t14 else "–", " → ".join(pct(x) for _, x in t14)),
             ("Trading desktops", str(sm["vip_wrong"]), "outside the late ring")]
    if eos:
        tiles.append(("End of servicing", str(len(eos[0]["rows"])), eos[0]["issues"][0].text.split(":")[0]))
    h += [f"<div class='tile'><span class='muted'>{e(a)}</span><b>{e(x)}</b><span class='muted'>{e(y)}</span></div>" for a, x, y in tiles]
    h.append("</div><h2>Status by area</h2><div class='areas'>")
    for a in AREAS:
        n = sum(f.area == a and f.severity != INFO for f in findings)
        h.append(f"<div class='area {st[a]}'><span class='lbl'>{e(a)}</span>{_pill(st[a], 'ON TRACK' if st[a] == 'ok' else VERDICT[st[a]].upper())}"
                 f"<span class='cnt'>{n} to act on</span></div>")
    h.append("</div>")
    crit = [f for f in findings if f.severity == CRITICAL]
    if crit:
        h.append("<h2>Fix first</h2>")
        h.append(_table(["Subject", "What", "Next step", "Owner"],
                        [f"<tr><td class='subj'><b>{e(f.subject)}</b><br><span class='muted'>{e(f.area)} · {e(f.code)}</span></td>"
                         f"<td class='sm brk'>{e(f.detail)}</td><td class='fix'>{e(f.fix)}</td><td class='nw'>{e(f.owner)}</td></tr>" for f in crit]))
    # 1 timeline and gates
    _sect(h, 1, "This month's rollout", "Rings and gates", st,
          "Each ring from its offer date (Patch Tuesday + deferral) to its deadline and grace, the gates between rings and today. "
          "rings.csv and gates.csv have the numbers.")
    h.append(timeline(d, rv))
    grow = []
    for g in rv["gates"]:
        res = _pill("go" if g["go"] else "no-go", "GO" if g["go"] else "NO-GO")
        grow.append(f"<tr><td class='sm'><b>{e(g['prev'])}</b> → <b>{e(g['nxt'])}</b></td><td class='nw sm'>{g['when']:%a %d %b}</td>"
                    f"<td class='sm'>{e(g['state'])}</td><td>{res}</td><td class='sm'>{e('; '.join(g['reasons'])) or '–'}</td></tr>")
    h.append("<p></p>" + _table(["Gate", "Date", "State", "Result", "Reasons"], grow))
    # 2 rings
    _sect(h, 2, "Rings", "Rings and gates", st,
          f"Every ring against its deadline (target {pct(s.gate_compliance)} on the build after deadline and grace), paused rings and policies "
          "that differ from the ring standard in settings.json.")
    rrow = []
    for r in rv["rings"]:
        pols = "<br>".join(e(_pol(p)) for p in r["policies"])
        rrow.append(f"<tr><td class='sm'><b>{e(r['ring'])}</b><br><span class='muted'>{pct(r['share'])} of the fleet, target {pct(r['target'])}</span></td>"
                    f"<td class='sm'>{pols}</td><td class='num'>{r['devices']}</td><td class='num'>{pct(r['compliance'])}</td><td class='num'>{r['behind']}</td>"
                    f"<td>{_vpill(r['verdict'])}</td><td class='sm'>{_issues([i for i in r['issues'] if i.code != 'COMP-03'])}</td></tr>")
    h.append(_table(["Ring", "Policies (days)", "Devices", "On the build", "Behind", "Status", "Issues"], rrow))
    # 3 devices
    _sect(h, 3, "Devices behind", "Devices behind", st,
          "Devices not on the build after their own deadline and grace, by site and reason, plus devices with no ring or two, versions near their end of "
          "servicing and safeguard holds. devices-behind.csv lists every device with its user and the action.")
    h.append(_table(["Site", "Owner", "Behind"] + [x.capitalize() for x in REASONS],
                    [f"<tr><td class='nw'><b>{e(site)}</b></td><td class='sm'>{e(s.site_owners.get(site, '–'))}</td><td class='num'>{n}</td>"
                     + "".join(f"<td class='num'>{c.get(x, 0) or ''}</td>" for x in REASONS) + "</tr>" for site, c, n in chase(rv)]))
    h.append("<p></p>" + _table(["Check", "Status", "Detail"],
                                [f"<tr><td class='nw'><b>{e(r['kind'])}</b></td><td>{_vpill(r['verdict'])}</td><td class='sm'>{_issues(r['issues'])}</td></tr>"
                                 for r in rv["device_rows"]]))
    # 4 failures
    _sect(h, 4, "Failures and incidents", "Failures", st,
          f"Failed installs this month by error code and model (a model with {s.failure_cluster_min} or more failures and {pct(s.model_failure_share_min)} "
          "of its devices failing points to a firmware or driver baseline), repeated failures and the incidents tagged to the update.")
    frow = [f"<tr><td class='nw'><b>{e(r['code'])}</b><br><span class='muted'>{e(r['category'])}</span></td><td class='sm'>{e(r['name']) or '–'}</td>"
            f"<td class='num'>{len(r['rows'])}</td><td class='sm'>{e(r['model'])}<br><span class='muted'>{r['model_count']} failing, "
            f"{pct(r['model_share'])} of the model</span></td><td>{_vpill(r['verdict'])}</td><td class='sm'>{_issues(r['issues'])}</td></tr>"
            for r in rv["failures"]]
    for r in rv["failure_extra"]:
        what = e(r["incident"].short_description) if r.get("incident") else "Repeated failures"
        frow.append(f"<tr><td class='nw'><b>{e(r['kind'])}</b></td><td class='sm' colspan='3'>{what}</td><td>{_vpill(r['verdict'])}</td>"
                    f"<td class='sm'>{_issues(r['issues'])}</td></tr>")
    h.append(_table(["Code", "Meaning", "Devices", "Top model", "Status", "Issues"], frow))
    # 5 composition
    _sect(h, 5, "Ring composition", "Composition", st,
          f"Trading desktops ('{s.vip_match}') in the late ring, a pilot that looks like the broad ring (departments, models, sites) and ring sizes. "
          "composition.csv compares every ring with the broad ring.")
    crow = []
    for r in rv["rings"]:
        crow.append(f"<tr><td class='nw'><b>{e(r['ring'])}</b></td><td class='num'>{r['devices']}<br><span class='muted'>{pct(r['share'])} / "
                    f"{pct(r['target'])}</span></td><td class='sm'>{e(_counts(Counter(x['dev'].department for x in r['rows']), 4))}</td>"
                    f"<td class='sm'>{e(_counts(Counter(x['dev'].model for x in r['rows']), 3))}</td>"
                    f"<td class='sm'>{e(_counts(Counter(x['dev'].site for x in r['rows'])))}</td></tr>")
    h.append(_table(["Ring", "Devices (share / target)", "Departments", "Models", "Sites"], crow))
    if cp["issues"]:
        h.append("<p></p>" + _table(["Status", "Detail"], [f"<tr><td>{_vpill(VERDICT[i.severity])}</td><td class='sm'>{_issues([i])}</td></tr>"
                                                            for i in cp["issues"]]))
    rep = cp["rep"]
    if rep:
        h.append(f"<p class='muted'>Pilot: {pct(rep['top_share'])} {e(rep['top'])}, {rep['departments']} departments (broad ring: "
                 f"{rep['broad_departments']}); its models cover {pct(rep['coverage'])} of the broad ring.</p>")
    # 6 trend
    _sect(h, 6, "Trend", "Trend", st,
          "Share of devices on each month's update by day 7, 14 and 21 after Patch Tuesday, and the median days to install by ring. trend.csv has "
          "every ring and month.")
    x14 = 14 if 14 in tr["days"] else tr["days"][0]
    tgt = tr["targets"].get(x14)
    bars = []
    for r in tr["all"]:
        v = r["shares"][x14]
        over = " over" if tgt and v is not None and v < tgt else ""
        bars.append(f"<div class='col'><span class='v'>{pct(v)}</span><span class='b{over}' style='height:{max(2, round(160 * (v or 0)))}px'></span>"
                    f"<span class='k'>{e(r['month'])} · day {x14}<br>{r['devices']} devices</span></div>")
    h.append("<div class='bars'>" + "".join(bars) + "</div>")
    trow = [f"<tr><td class='nw'><b>{e(r['month'])}</b></td><td class='nw sm'>{r['release']:%a %d %b}</td>"
            + "".join(f"<td class='num'>{pct(r['shares'][x])}</td>" for x in tr["days"]) + f"<td class='num'>{_g(r['median'])}</td>"
            + "".join(f"<td class='num'>{_med(tr, r['month'], rg)}</td>" for rg in s.ring_names()) + "</tr>" for r in tr["all"]]
    h.append(_table(["Month", "Released"] + [f"Day {x}" for x in tr["days"]] + ["Median days"] + [f"{rg.split(' - ')[0]} median" for rg in s.ring_names()],
                    trow))
    if tr["issues"]:
        h.append("<p></p>" + _table(["Status", "Detail"], [f"<tr><td>{_vpill(VERDICT[i.severity])}</td><td class='sm'>{_issues([i])}</td></tr>"
                                                            for i in tr["issues"]]))
    # 7 release health
    h.append("<h2>7. Known issues and incidents</h2><p class='muted'>Windows release health items for the versions in the fleet, with the rings "
             "each one blocks (the team's decision), and the incidents tagged to an update.</p>")
    h.append(_table(["Known issue", "KB", "Status", "Opened", "Resolved", "Blocks"],
                    [f"<tr><td class='sm'>{e(k.title)}</td><td class='nw sm'>KB{e(k.kb)}</td><td class='sm'>{e(k.status)}</td><td class='nw sm'>"
                     f"{_t(k.opened)}</td><td class='nw sm'>{_t(k.resolved) or '–'}</td><td class='sm'>{e(', '.join(k.blocks)) or '–'}</td></tr>"
                     for k in sorted(d.issues, key=lambda k: (k.opened or datetime.min, k.title), reverse=True)]))
    h.append("<p></p>" + _table(["Incident", "P", "Opened", "Update", "Ring", "Devices", "Rolled back", "Resolved"],
                                [f"<tr><td class='sm'><b>{e(i.number)}</b> {e(i.short_description)}</td><td class='num'>{i.priority}</td>"
                                 f"<td class='nw sm'>{_t(i.opened)}</td><td class='nw sm'>KB{e(i.kb)}</td><td class='sm'>{e(i.ring or '–')}</td>"
                                 f"<td class='num'>{i.devices}</td><td class='sm'>{'yes' if i.rollback else 'no'}</td>"
                                 f"<td class='nw sm'>{_t(i.resolved) or 'open'}</td></tr>"
                                 for i in sorted(d.incidents, key=lambda i: (i.opened or datetime.min, i.number))]))
    h.append("<h2>All findings</h2>")
    h.append(_table(["Severity", "Area", "Subject", "Detail", "Next step", "Owner"],
                    [f"<tr><td>{_pill(f.severity, f.severity.upper())}</td><td class='nw'>{e(f.area)}</td><td>{e(f.subject)}</td>"
                     f"<td class='sm brk'>{e(f.detail)}</td><td class='fix'>{e(f.fix)}</td><td class='nw'>{e(f.owner)}</td></tr>" for f in findings]))
    h.append("<footer class='muted'>Generated by ringtrack. Fictional demo data unless you ran it on your own exports. The patch meeting pack is "
             "rollout-pack.md.</footer></main></body></html>")
    return "".join(h)


__all__ = ["render_html", "pack_md", "WARNING"]
