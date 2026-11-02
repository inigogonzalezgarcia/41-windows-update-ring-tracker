"""The checks. The update month is the latest Patch Tuesday (B) release on or before the reference date; its builds give the expected
build of each Windows 11 version (a device is current when its OS build revision is that build or later). Every device gets its ring
(from the groups or collections its ring policies are assigned to), its own offer date, deadline and grace from its policy, and a reason
when it is not current. Then five areas: rings and gates (each ring against its deadline, promotions made without passing the gate, the
go/no-go for the next one, paused rings, policies that drift from the standard), devices behind (past the deadline, restart pending, not
checked in, no ring, two rings, end of servicing, safeguard holds), failures (error codes by model, repeated failures, incidents tagged to
the update), composition (the late ring for trading desktops, a pilot that looks like the broad ring, ring sizes) and the trend (share on
the build at day 7, 14 and 21 for the last months, median days to install by ring, devices behind every month)."""
from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .model import ERROR_NAMES, Data, Device, Policy, Status, _norm, month_key, months_until

CRITICAL, WARNING, INFO = "critical", "warning", "info"
ORDER = {CRITICAL: 0, WARNING: 1, INFO: 2}
AREAS = ("Rings and gates", "Devices behind", "Failures", "Composition", "Trend")
VERDICT = {CRITICAL: "action needed", WARNING: "attention", None: "on track"}
NO_RING = "(no ring)"
NOT_BEHIND = ("not offered yet", "in window")
PLURAL = {"policy": "policies"}


@dataclass
class Finding:
    severity: str
    area: str
    code: str
    subject: str
    detail: str
    fix: str
    owner: str = ""
    items: list[str] = field(default_factory=list)


@dataclass
class Issue:
    severity: str
    code: str
    text: str
    n: int = 1


def _n(k: int, word: str, plural: str | None = None) -> str:
    return f"{k} {word if k == 1 else (plural or word + 's')}"


def _top(items: list[str], k: int = 6, sep: str = ", ") -> str:
    return sep.join(items[:k]) + (f" and {len(items) - k} more" if len(items) > k else "")


def _d(v) -> str:
    if not v:
        return "never"
    return v.strftime("%a %d %b") if isinstance(v, (date, datetime)) else str(v)


def pct(x: float | None) -> str:
    return "–" if x is None else f"{x:.0%}"


def worst(issues: list[Issue]) -> str | None:
    sev = {i.severity for i in issues}
    return CRITICAL if CRITICAL in sev else WARNING if WARNING in sev else None


def _row(**kw) -> dict:
    kw.setdefault("issues", [])
    kw["severity"] = worst(kw["issues"])
    kw["verdict"] = VERDICT[kw["severity"]]
    return kw


def error_name(d: Data, code: str) -> str:
    return d.settings.error_codes.get(code) or ERROR_NAMES.get(code.upper(), "")


def _dt(x: date) -> datetime:
    return datetime(x.year, x.month, x.day)


# ---------------------------------------------------------------- the month, rings and devices

def month_info(d: Data) -> dict:
    s = d.settings
    bs = [b for b in d.builds if b.update_type == "B"]
    month = s.month or max((b.month for b in bs if b.release_date <= d.as_of), default="")
    if not month:
        raise ValueError("releases.csv has no Patch Tuesday (B) build released on or before the reference date")
    mb = [b for b in d.builds if b.month == month]
    b_rel = [b for b in mb if b.update_type == "B"] or mb
    expected = {}
    for b in b_rel:
        expected[b.build] = min(expected.get(b.build, b.revision), b.revision)
    release = min(b.release_date for b in b_rel).date()
    return {"month": month, "release": release, "expected": expected, "kbs": sorted({b.kb for b in mb if b.kb}),
            "builds": mb, "b_kb": sorted({b.kb for b in b_rel if b.kb})}


def policy_dates(p: Policy, release: date) -> dict:
    offer = release + timedelta(days=p.quality_deferral)
    paused_now = False
    if p.paused and p.pause_start and p.pause_start.date() <= offer:
        exp = p.pause_expiry.date() if p.pause_expiry else offer
        offer = max(offer, exp)
    deadline = offer + timedelta(days=p.deadline or 0)
    grace_end = deadline + timedelta(days=p.grace or 0)
    return {"offer": offer, "deadline": deadline, "grace_end": grace_end, "paused_now": paused_now}


def is_paused(p: Policy, when: datetime) -> bool:
    return p.paused and (not p.pause_expiry or p.pause_expiry > when)


def ring_order(d: Data, ring: str) -> int:
    r = d.settings.ring(ring)
    return int(r.get("order", 99))


def standard_diff(d: Data, p: Policy) -> list[str]:
    std = d.settings.ring(p.ring or p.name)
    if "quality_deferral_days" not in std:
        return [f"not in the ring standard of settings.json"]
    out = []
    for key, label, val in (("quality_deferral_days", "quality deferral", p.quality_deferral), ("deadline_days", "deadline", p.deadline),
                            ("grace_days", "grace", p.grace), ("feature_deferral_days", "feature deferral", p.feature_deferral)):
        if key in std and (val if val is not None else (0 if key == "grace_days" and p.configmgr else None)) != std[key]:
            out.append(f"{label} {'not set' if val is None else f'{val} days'} (standard {std[key]})")
    return out


def _policies_for(d: Data, dev: Device) -> list[Policy]:
    gs = {g.lower() for g in dev.groups}
    ps = [p for p in d.policies if gs & {g.lower() for g in p.groups}]
    if dev.wufb_intune is True:          # co-managed with the Windows Update policies workload in Intune: ConfigMgr deployments do not apply
        ps = [p for p in ps if not p.configmgr]
    elif dev.wufb_intune is False:       # workload still in ConfigMgr: the Intune update rings do not apply
        ps = [p for p in ps if p.configmgr]
    return ps


def status_index(d: Data, month: str) -> tuple[dict, dict]:
    """(quality records of the month, feature records) by device key, the latest record per key."""
    q, f = {}, {}
    for st in d.status:
        if st.category == "feature":
            prev = f.get(st.key)
            if not prev or (st.release or datetime.min) >= (prev.release or datetime.min):
                f[st.key] = st
        elif st.category == "quality" and st.release and month_key(st.release) == month:
            q[st.key] = st
    return q, f


def _rec(idx: dict, dev: Device):
    return idx.get(dev.aad_id.lower()) if dev.aad_id and dev.aad_id.lower() in idx else idx.get(dev.name.lower())


def classify(d: Data, mi: dict) -> list[dict]:
    s, today = d.settings, d.today
    qidx, fidx = status_index(d, mi["month"])
    stale_before = d.as_of - timedelta(days=s.stale_days)
    out = []
    for dev in sorted(d.devices, key=lambda x: x.name.lower()):
        ps = _policies_for(d, dev)
        rings = sorted({p.ring or p.name for p in ps}, key=lambda r: (ring_order(d, r), r))
        ring = rings[0] if rings else NO_RING
        own = sorted([p for p in ps if (p.ring or p.name) == ring], key=lambda p: (p.configmgr, p.name))
        pol = own[0] if own else None
        dates = policy_dates(pol, mi["release"]) if pol else None
        b, rev = dev.build
        exp = mi["expected"].get(b)
        st, fst = _rec(qidx, dev), _rec(fidx, dev)
        current = exp is not None and rev >= exp
        stale = not dev.last_sync or dev.last_sync < stale_before
        drift = bool(pol and standard_diff(d, pol))
        reason = ""
        if not current:
            if exp is None:
                reason = "version not serviced"
            elif not rings:
                reason = "no ring"
            elif any(is_paused(p, d.as_of) for p in own):
                reason = "ring paused"
            elif stale:
                reason = "not checked in"
            elif st and st.error and not st.is_installed:
                reason = "failed"
            elif dates and dates["offer"] > today:
                reason = "not offered yet"
            elif dates and today <= dates["grace_end"]:
                reason = "in window"
            elif st and st.restart_pending:
                reason = "restart pending"
            else:
                reason = "past deadline"
        installed = st.installed if st and st.installed else None
        out.append(dict(dev=dev, policies=ps, rings=rings, ring=ring, policy=pol, dates=dates, version=d.version_of(b), build=b, rev=rev,
                        expected=f"{b}.{exp}" if exp is not None else "", current=current, stale=stale, drift=drift, st=st, fst=fst,
                        installed=installed, reason=reason, behind=bool(reason) and reason not in NOT_BEHIND,
                        past=(today - dates["grace_end"]).days if dates and reason and today > dates["grace_end"] else 0))
    return out


def compliance(rows: list[dict], when: datetime, now: datetime) -> float | None:
    if not rows:
        return None
    ok = sum(1 for r in rows if (r["installed"] and r["installed"] <= when) or (r["current"] and not r["installed"] and when >= now))
    return ok / len(rows)


# ---------------------------------------------------------------- rings and gates

def ring_rows(d: Data, mi: dict, devs: list[dict]) -> list[dict]:
    s, today = d.settings, d.today
    by = defaultdict(list)
    for r in devs:
        by[r["ring"]].append(r)
    names = s.ring_names() + sorted({p.ring or p.name for p in d.policies} - set(s.ring_names()))
    total = len(devs)
    out = []
    for name in names:
        rows = by.get(name, [])
        pols = [p for p in d.policies if (p.ring or p.name) == name]
        if not pols and not rows:
            continue
        counts = Counter(id(r["policy"]) for r in rows)
        main = max(pols, key=lambda p: (counts.get(id(p), 0), not p.configmgr, p.name)) if pols else None
        dt = policy_dates(main, mi["release"]) if main else None
        std = s.ring(name)
        comp = compliance(rows, d.as_of, d.as_of)
        issues = []
        if dt and today > dt["grace_end"] and comp is not None and comp < s.gate_compliance and not any(is_paused(p, d.as_of) for p in pols):
            late = (today - dt["grace_end"]).days
            issues.append(Issue(CRITICAL if late > s.ring_late_days else WARNING, "RING-01",
                                f"{name}: {pct(comp)} on the {mi['month']} build, {late} days after its deadline and grace ended on "
                                f"{_d(dt['grace_end'])} (target {pct(s.gate_compliance)})", len(rows)))
        for p in pols:
            if is_paused(p, d.as_of) and p.pause_start:
                days = (d.as_of - p.pause_start).days
                if days >= s.pause_warning_days:
                    missed = sorted({b.month for b in d.builds if b.update_type == "B" and p.pause_start.date()
                                     <= b.release_date.date() + timedelta(days=p.quality_deferral) <= today})
                    issues.append(Issue(CRITICAL if days >= s.pause_critical_days else WARNING, "RING-03",
                                        f"{p.name}: quality updates paused for {days} days since {_d(p.pause_start)}"
                                        f"{f', expires {p.pause_expiry:%a %d %b %H:%M}' if p.pause_expiry else ''}; "
                                        f"{len(rows)} devices missed {', '.join(missed) or 'no release yet'}", len(rows)))
            diff = standard_diff(d, p)
            if diff:
                nd = sum(1 for r in rows if r["policy"] is p)
                issues.append(Issue(WARNING, "RING-04", f"{p.name} ({p.source}, {nd} devices): {'; '.join(diff)}", nd))
        share = len(rows) / total if total else 0
        tgt = std.get("target_share")
        if tgt and abs(share - tgt) / tgt > s.ring_size_tolerance:
            issues.append(Issue(WARNING, "COMP-03", f"{name}: {len(rows)} devices, {pct(share)} of the fleet against a target of {pct(tgt)}"))
        mrows = [r for r in rows if r["installed"]]
        med = statistics.median((r["installed"].date() - mi["release"]).days for r in mrows) if mrows else None
        out.append(_row(ring=name, order=ring_order(d, name), policies=pols, main=main, dates=dt, devices=len(rows), share=share, target=tgt,
                        compliance=comp, current=sum(r["current"] for r in rows), behind=sum(r["behind"] for r in rows),
                        restart=sum(r["reason"] == "restart pending" for r in rows), failed=sum(r["reason"] == "failed" for r in rows),
                        stale=sum(r["reason"] == "not checked in" for r in rows), window=sum(r["reason"] in NOT_BEHIND for r in rows),
                        paused=any(is_paused(p, d.as_of) for p in pols), late=bool(std.get("late")), median=med, rows=rows, issues=issues))
    return out


def gate_rows(d: Data, mi: dict, rings: list[dict], devs: list[dict]) -> list[dict]:
    s, today = d.settings, d.today
    chain = [r for r in rings if r["ring"] in s.ring_names() and r["dates"]]
    chain.sort(key=lambda r: (r["order"], r["ring"]))
    out, seen_next = [], False
    kbs = set(mi["kbs"])
    for prev, nxt in zip(chain, chain[1:]):
        when = nxt["dates"]["offer"]
        t = min(_dt(when), d.as_of)
        comp = compliance(prev["rows"], t, d.as_of)
        fail = sum(1 for r in prev["rows"] if r["st"] and r["st"].error and not r["st"].is_installed) / prev["devices"] if prev["devices"] else 0
        soak = (when - prev["dates"]["offer"]).days
        upto = {r["ring"] for r in chain if r["order"] <= prev["order"]}
        incs = [i for i in d.incidents if i.kb in kbs and (not i.ring or i.ring in upto) and 0 < i.priority <= s.gate_incident_max_priority
                and i.opened and i.opened <= t and not (i.resolved and i.resolved <= t)]
        iss = [k for k in d.issues if k.open_at(t) and (nxt["ring"] in k.blocks or any(_norm(b) == "all" for b in k.blocks))]
        reasons = []
        if comp is None or comp < s.gate_compliance:
            reasons.append(f"{prev['ring']} at {pct(comp)} on the build (gate {pct(s.gate_compliance)})")
        if fail > s.gate_failure_max:
            reasons.append(f"{pct(fail)} of {prev['ring']} failing (max {pct(s.gate_failure_max)})")
        if soak < s.gate_min_soak_days:
            reasons.append(f"only {soak} days after {prev['ring']} was offered (minimum {s.gate_min_soak_days})")
        reasons += [f"{i.number} P{i.priority} {i.short_description}{' (rolled back)' if i.rollback else ''}" for i in incs]
        reasons += [f"known issue open: {k.title} ({k.status or 'open'})" for k in iss]
        state = "promoted" if when <= today else ("next" if not seen_next else "later")
        seen_next = seen_next or state == "next"
        go = not reasons
        issues = []
        if state == "promoted" and not go:
            issues.append(Issue(CRITICAL, "RING-02", f"{nxt['ring']} offered on {_d(when)} although the gate was not met: {'; '.join(reasons)}",
                                nxt["devices"]))
        elif state == "next":
            issues.append(Issue(INFO if go else CRITICAL, "RING-05",
                                f"{nxt['ring']} is due on {_d(when)} ({nxt['devices']} devices): "
                                + ("GO, every gate condition met" if go else f"NO-GO: {'; '.join(reasons)}"), nxt["devices"]))
        out.append(_row(prev=prev["ring"], nxt=nxt["ring"], when=when, state=state, compliance=comp, failure=fail, soak=soak, incidents=incs,
                        known=iss, go=go, reasons=reasons, issues=issues))
    return out


# ---------------------------------------------------------------- devices behind

def _sites(rows: list[dict]) -> list[tuple[str, list[dict]]]:
    by = defaultdict(list)
    for r in rows:
        by[r["dev"].site or "(no site)"].append(r)
    return sorted(by.items(), key=lambda kv: (-len(kv[1]), kv[0]))


def device_issues(d: Data, mi: dict, devs: list[dict]) -> list[dict]:
    """Rows by site and reason, each with its issue (DEV-01 … DEV-07)."""
    s, out = d.settings, []
    site_n = Counter(r["dev"].site or "(no site)" for r in devs)
    groups = [("past deadline", "DEV-01", "not on the build after the deadline and grace, no error and no restart pending"),
              ("restart pending", "DEV-02", "installed and waiting for a restart past the deadline and grace"),
              ("not checked in", "DEV-03", f"not checked in for more than {s.stale_days} days")]
    for reason, code, what in groups:
        rows = [r for r in devs if r["reason"] == reason]
        sev = CRITICAL if len(rows) >= s.chase_critical_count else WARNING
        for site, rs in _sites(rows):
            sv = sev
            if code == "DEV-03":
                share = len(rs) / site_n[site]
                sv = CRITICAL if share >= s.site_stale_share else WARNING
                last = max((r["dev"].last_sync for r in rs if r["dev"].last_sync), default=None)
                txt = f"{site}: {len(rs)} devices ({pct(share)} of the site) {what}, the most recent on {_d(last)}"
            else:
                txt = f"{site}: {len(rs)} devices {what}, up to {max(r['past'] for r in rs)} days late"
            out.append(_row(kind=code, site=site, rows=rs, issues=[Issue(sv, code, txt, len(rs))]))
    nr = [r for r in devs if r["ring"] == NO_RING]
    for site, rs in _sites(nr):
        out.append(_row(kind="DEV-04", site=site, rows=rs, issues=[Issue(WARNING, "DEV-04", f"{site}: {len(rs)} devices in no update ring "
                                                                         f"(no deferral, deadline or pause applies; {sum(not r['current'] for r in rs)} "
                                                                         f"not on the build)", len(rs))]))
    two = [r for r in devs if len(r["rings"]) > 1]
    for combo, rs in sorted(Counter(" + ".join(r["rings"]) for r in two).items()):
        lst = [r for r in two if " + ".join(r["rings"]) == combo]
        out.append(_row(kind="DEV-05", site=combo, rows=lst, issues=[Issue(WARNING, "DEV-05", f"{rs} devices in two rings ({combo}): conflicting "
                                                                          f"settings are not applied", rs)]))
    for v in sorted(d.versions.values(), key=lambda v: v.build):
        if not v.end_of_servicing:
            continue
        days = (v.end_of_servicing - d.today).days
        rs = [r for r in devs if r["build"] == v.build]
        if rs and days <= s.eos_warning_days:
            sev = CRITICAL if days <= s.eos_critical_days else WARNING
            txt = (f"Windows 11 {v.version}: {len(rs)} devices, end of servicing "
                   + (f"on {v.end_of_servicing:%d %b %Y} ({days} days)" if days >= 0 else f"passed on {v.end_of_servicing:%d %b %Y}"))
            out.append(_row(kind="DEV-06", site=v.version, rows=rs, issues=[Issue(sev, "DEV-06", txt, len(rs))]))
    holds = [r for r in devs if r["fst"] and r["fst"].safeguard and not r["fst"].is_installed]
    for ver, n in sorted(Counter(r["version"] for r in holds).items()):
        rs = [r for r in holds if r["version"] == ver]
        tgt = rs[0]["fst"].target_version or s.feature_target
        out.append(_row(kind="DEV-07", site=ver, rows=rs, issues=[Issue(WARNING, "DEV-07", f"{n} devices on {ver} under a safeguard hold for the "
                                                                        f"feature update to {tgt}", n)]))
    return out


# ---------------------------------------------------------------- failures

def failure_rows(d: Data, mi: dict, devs: list[dict]) -> tuple[list[dict], list[dict]]:
    s = d.settings
    model_n = Counter(r["dev"].model for r in devs)
    out = []
    for cat in ("quality", "feature"):
        failed = [r for r in devs if (r["st"] if cat == "quality" else r["fst"]) and (r["st"] if cat == "quality" else r["fst"]).error
                  and not (r["st"] if cat == "quality" else r["fst"]).is_installed and (cat == "feature" or not r["current"])]
        by = defaultdict(list)
        for r in failed:
            by[(r["st"] if cat == "quality" else r["fst"]).error].append(r)
        for code, rs in sorted(by.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            mc = Counter(r["dev"].model for r in rs)
            model, cnt = mc.most_common(1)[0]
            mshare = cnt / model_n[model] if model_n[model] else 0
            name = error_name(d, code)
            issues = []
            short = f" ({name.split(':')[0]})" if name else ""
            what = f"{'feature update' if cat == 'feature' else mi['month'] + ' update'} fails with {code}{short}"
            if cnt >= s.failure_cluster_min and mshare >= s.model_failure_share_min and cnt / len(rs) >= 0.6:
                issues.append(Issue(CRITICAL, "FAIL-01", f"{model}: {cnt} of {model_n[model]} devices ({pct(mshare)}): {what}", cnt))
            else:
                issues.append(Issue(WARNING, "FAIL-02", f"{code}: {len(rs)} devices, {what}; models {', '.join(f'{m} ({k})' for m, k in mc.most_common(3))}",
                                    len(rs)))
            out.append(_row(category=cat, code=code, name=name, rows=rs, model=model, model_count=cnt, model_share=mshare,
                            sites=Counter(r["dev"].site for r in rs), rings=Counter(r["ring"] for r in rs), issues=issues))
    # repeated failures across the months of the trend
    months = months_until(mi["month"], s.trend_months)
    errs = defaultdict(set)
    for st in d.status:
        if st.category == "quality" and st.error and not st.is_installed and st.release and month_key(st.release) in months:
            errs[st.key].add(month_key(st.release))
    rep = [r for r in devs if len(errs.get(r["dev"].key, set()) | errs.get(r["dev"].name.lower(), set())) >= 2]
    extra = []
    if rep:
        extra.append(_row(kind="FAIL-03", rows=rep, issues=[Issue(WARNING, "FAIL-03", f"{len(rep)} devices failed in two or more of "
                                                                  f"{', '.join(months)}: {_top([r['dev'].name for r in rep], 8)}", len(rep))]))
    kbs = set(mi["kbs"])
    for i in sorted(d.incidents, key=lambda i: (i.opened or datetime.min, i.number)):
        if i.kb not in kbs:
            continue
        open_ = not i.resolved or i.resolved > d.as_of
        sev = (CRITICAL if (open_ or i.rollback) else WARNING) if 0 < i.priority <= s.gate_incident_max_priority else INFO
        extra.append(_row(kind="FAIL-04", incident=i, rows=[], issues=[Issue(sev, "FAIL-04",
                     f"{i.number} P{i.priority} {i.short_description} ({i.ring or 'no ring'}, {i.devices} devices, KB{i.kb}"
                     f"{', rolled back' if i.rollback else ''}, {'open' if open_ else 'resolved ' + _d(i.resolved)})")]))
    return out, extra


# ---------------------------------------------------------------- composition

def composition(d: Data, devs: list[dict], rings: list[dict]) -> dict:
    s = d.settings
    vip_re = re.compile(s.vip_match, re.I) if s.vip_match else None
    issues = []
    vip = [r for r in devs if vip_re and (vip_re.search(r["dev"].category) or vip_re.search(r["dev"].department))]
    wrong = [r for r in vip if s.vip_ring and r["ring"] != s.vip_ring]
    for ring, n in sorted(Counter(r["ring"] for r in wrong).items()):
        rs = [r for r in wrong if r["ring"] == ring]
        sites = Counter(r["dev"].site for r in rs)
        issues.append(Issue(CRITICAL, "COMP-01", f"{n} devices matching '{s.vip_match}' in {ring} instead of {s.vip_ring} "
                                                 f"({', '.join(f'{k} {v}' for k, v in sites.most_common())}; departments "
                                                 f"{', '.join(k for k, _ in Counter(r['dev'].department for r in rs).most_common(3))})", n))
    pilot = [r for r in devs if r["ring"] == s.pilot_ring]
    broad = [r for r in devs if r["ring"] == s.broad_ring]
    rep = {}
    if pilot and broad:
        dept = Counter(r["dev"].department for r in pilot)
        top, k = dept.most_common(1)[0]
        pm = {r["dev"].model for r in pilot}
        cov = sum(1 for r in broad if r["dev"].model in pm) / len(broad)
        missing_models = Counter(r["dev"].model for r in broad if r["dev"].model not in pm)
        sites_missing = sorted({r["dev"].site for r in broad} - {r["dev"].site for r in pilot})
        rep = dict(top=top, top_share=k / len(pilot), coverage=cov, missing_models=missing_models, sites_missing=sites_missing,
                   departments=len(dept), broad_departments=len({r["dev"].department for r in broad}))
        if k / len(pilot) > s.pilot_max_department_share:
            issues.append(Issue(WARNING, "COMP-02", f"{s.pilot_ring}: {pct(k / len(pilot))} of the pilot is {top} "
                                                   f"(max {pct(s.pilot_max_department_share)}); {len(dept)} departments against "
                                                   f"{rep['broad_departments']} in {s.broad_ring}"))
        if cov < s.pilot_model_coverage_min:
            issues.append(Issue(WARNING, "COMP-02", f"{s.pilot_ring}: the pilot's models cover {pct(cov)} of {s.broad_ring} (min "
                                                   f"{pct(s.pilot_model_coverage_min)}); missing "
                                                   f"{', '.join(f'{m} ({n})' for m, n in missing_models.most_common(4))}"))
        if sites_missing:
            issues.append(Issue(WARNING, "COMP-02", f"{s.pilot_ring}: no pilot devices at {', '.join(sites_missing)}"))
    for r in rings:
        issues += [i for i in r["issues"] if i.code == "COMP-03"]
    return {"vip": vip, "wrong": wrong, "rep": rep, "pilot": pilot, "broad": broad, "issues": issues}


# ---------------------------------------------------------------- trend

def trend(d: Data, mi: dict, devs: list[dict]) -> dict:
    s = d.settings
    months = months_until(mi["month"], s.trend_months)
    ring_of = {}
    for r in devs:
        ring_of[r["dev"].key] = r["ring"]
        ring_of[r["dev"].name.lower()] = r["ring"]
    rel = {}
    for m in months:
        bs = [b for b in d.builds if b.month == m and b.update_type == "B"]
        if bs:
            rel[m] = min(b.release_date for b in bs).date()
    by_month = defaultdict(dict)
    for st in d.status:
        if st.category == "quality" and st.release and month_key(st.release) in rel:
            by_month[month_key(st.release)][st.key] = st
    days = [int(x) for x in s.trend_days]
    pol_of = {}
    for r in devs:
        pol_of[r["dev"].key] = pol_of[r["dev"].name.lower()] = r["policy"]
    rows, late, complete = [], defaultdict(int), defaultdict(int)
    for m in months:
        if m not in rel:
            continue
        recs = by_month.get(m, {})
        groups = [("All", list(recs.items()))] + [(rg, [(k, v) for k, v in recs.items() if ring_of.get(k) == rg]) for rg in
                                                  s.ring_names() + [NO_RING]]
        for rg, items in groups:
            if not items:
                continue
            dl = [(v.installed.date() - rel[m]).days for _, v in items if v.installed]
            shares = {x: (sum(1 for y in dl if y <= x) / len(items) if rel[m] + timedelta(days=x) <= d.today else None) for x in days}
            rows.append(dict(month=m, release=rel[m], ring=rg, devices=len(items), installed=len(dl), shares=shares,
                             median=statistics.median(dl) if dl else None))
        for k, v in recs.items():
            pol = pol_of.get(k)
            lim = policy_dates(pol, rel[m])["grace_end"] if pol else rel[m] + timedelta(days=max(days))
            if lim < d.today:
                complete[k] += 1
                if not (v.installed and v.installed.date() <= lim):
                    late[k] += 1
    allr = [r for r in rows if r["ring"] == "All"]
    issues = []
    tg = {int(k): v for k, v in s.trend_targets.items()}
    if allr:
        for x in days:
            ser = [r["shares"][x] for r in allr if r["shares"][x] is not None]
            falling = len(ser) >= 2 and all(b < a for a, b in zip(ser, ser[1:]))
            if ser and x in tg and (ser[-1] < tg[x] or falling):
                issues.append(Issue(WARNING, "TRD-01", f"day {x}: " + " → ".join(f"{r['month']} {pct(r['shares'][x])}" for r in allr
                                                                                 if r["shares"][x] is not None)
                                    + f" (target {pct(tg[x])}{', falling every month' if falling else ''})"))
        for rg in s.ring_names():
            rr = [r for r in rows if r["ring"] == rg and r["median"] is not None]
            std = s.ring(rg)
            exp = std.get("quality_deferral_days", 0) + std.get("deadline_days", 0) + std.get("grace_days", 0)
            if rr and std.get("deadline_days") is not None and rr[-1]["median"] > exp:
                issues.append(Issue(WARNING, "TRD-02", f"{rg}: median {rr[-1]['median']:g} days to install in {rr[-1]['month']}, the policy allows "
                                                       f"{exp} (" + " → ".join(f"{r['month']} {r['median']:g}" for r in rr) + ")"))
    rep = []
    for r in devs:
        k = r["dev"].key if r["dev"].key in complete else r["dev"].name.lower()
        if r["behind"] and complete.get(k, 0) >= 2 and late.get(k, 0) == complete[k]:
            rep.append(r)
    if rep:
        issues.append(Issue(WARNING, "TRD-03", f"{len(rep)} devices past their deadline and grace in every month of the trend, and behind again in "
                                               f"{mi['month']}: {_top([r['dev'].name for r in rep], 8)}", len(rep)))
    return {"months": [m for m in months if m in rel], "release": rel, "rows": rows, "all": allr, "repeat": rep, "issues": issues,
            "days": days, "targets": tg}


# ---------------------------------------------------------------- review

def review(d: Data) -> dict:
    mi = month_info(d)
    devs = classify(d, mi)
    rings = ring_rows(d, mi, devs)
    gates = gate_rows(d, mi, rings, devs)
    dev_rows = device_issues(d, mi, devs)
    fails, fail_extra = failure_rows(d, mi, devs)
    comp = composition(d, devs, rings)
    tr = trend(d, mi, devs)
    return {"month": mi, "devices": devs, "rings": rings, "gates": gates, "device_rows": dev_rows, "failures": fails,
            "failure_extra": fail_extra, "composition": comp, "trend": tr}


CODES = {  # code: (area, owner key, subject, next step, item word)
    "RING-01": ("Rings and gates", "rings", "rings behind schedule after their deadline",
                "Chase the devices behind in the ring (devices-behind.csv) and hold the next promotion until the ring is back above the gate.", "ring"),
    "RING-02": ("Rings and gates", "rings", "rings promoted although the gate was not met",
                "Record why at the patch meeting; from next month, promote only on a recorded GO (gates.csv) or pause the next ring.", "ring"),
    "RING-03": ("Rings and gates", "rings", "update rings paused for too long",
                "Decide today: resume with a date, or extend the pause with a reason and an owner; a forgotten pause leaves devices months behind.",
                "policy"),
    "RING-04": ("Rings and gates", "rings", "ring policies that differ from the standard",
                "Align the deferral, deadline and grace with the ring standard, or retire the extra policy and move its group.", "policy"),
    "RING-05": ("Rings and gates", "rings", "the next promotion",
                "Take the go/no-go to the patch meeting before the offer date; on NO-GO pause the ring or move its deferral, and record the decision.",
                "ring"),
    "DEV-01": ("Devices behind", "devices", "devices past the deadline without the update",
               "Check them in the Windows Update report (scan, download, install state) and ask the user to keep the device online and restart.", "site"),
    "DEV-02": ("Devices behind", "devices", "devices with a restart pending past the deadline and grace",
               "Contact the users by site; a restart pending for days is a device that is never shut down or a restart blocked by an application.",
               "site"),
    "DEV-03": ("Devices behind", "devices", "devices not checked in",
               "A whole site going quiet is a network problem (VPN, proxy, DNS), not users: fix it first, then let the devices sync.", "site"),
    "DEV-04": ("Devices behind", "devices", "devices in no update ring",
               "Add them to the ring group that matches their role (dynamic group rules catch new devices).", "site"),
    "DEV-05": ("Devices behind", "devices", "devices in two rings",
               "Remove them from one group; with two update ring policies the conflicting settings are not applied.", "conflict"),
    "DEV-06": ("Devices behind", "devices", "devices on a version close to its end of servicing",
               "Move them to the target version with the feature update policy before the date; after it they get no security updates.", "version"),
    "DEV-07": ("Devices behind", "devices", "devices under a feature update safeguard hold",
               "Look up the hold in the report and Windows release health; update the driver or app it names, do not bypass it on business devices.",
               "version"),
    "FAIL-01": ("Failures", "failures", "a model failing the update with one error code",
                "Test the update on one device of the model with the latest firmware and drivers; fix the model's baseline, then retry the group.", "model"),
    "FAIL-02": ("Failures", "failures", "update failures by error code",
                "Use the error code (failures.csv) to pick the fix: component store repair, disk space, proxy or name resolution.", "code"),
    "FAIL-03": ("Failures", "failures", "devices failing month after month", "Rebuild or repair them; the same devices fail every month.", "group"),
    "FAIL-04": ("Failures", "failures", "incidents tagged to this month's update",
                "Review them at the patch meeting: scope, workaround, known issue, and whether they stop the next ring.", "incident"),
    "COMP-01": ("Composition", "composition", "trading desktops outside the late ring",
                "Move them to the late ring group before the next release; check how they got there (a dynamic rule, a manual add).", "ring"),
    "COMP-02": ("Composition", "composition", "a pilot that does not look like the broad ring",
                "Add pilot users from the business departments, sites and models of the broad ring; IT staff alone do not test trading and finance apps.",
                "gap"),
    "COMP-03": ("Composition", "composition", "rings off their target size", "Resize the ring groups to the target share.", "ring"),
    "TRD-01": ("Trend", "trend", "share of devices on the build by day after Patch Tuesday",
               "Take the trend to the monthly service review; the fixes above (restarts, failures, check-ins) are what moves it.", "checkpoint"),
    "TRD-02": ("Trend", "trend", "rings slower than their policy allows",
               "Compare the median with deferral + deadline + grace: a median above it means deadlines are not enforcing.", "ring"),
    "TRD-03": ("Trend", "trend", "devices behind every month", "Give each one an owner: replace, rebuild or remove from the fleet.", "group"),
}


def all_issues(rv: dict) -> list[Issue]:
    rows = rv["rings"] + rv["gates"] + rv["device_rows"] + rv["failures"] + rv["failure_extra"]
    out = [i for r in rows for i in r["issues"] if i.code != "COMP-03"]
    return out + rv["composition"]["issues"] + rv["trend"]["issues"]


def run_all(d: Data, rv: dict | None = None) -> list[Finding]:
    rv = rv if rv is not None else review(d)
    s = d.settings
    hits = defaultdict(list)
    for i in all_issues(rv):
        hits[i.code].append(i)
    out: list[Finding] = []
    for code, (area, owner, subject, fix, word) in CODES.items():
        for sev in (CRITICAL, WARNING, INFO):
            xs = list({i.text: i for i in hits.get(code, []) if i.severity == sev}.values())
            if not xs:
                continue
            n = sum(i.n for i in xs)
            head = _n(n, "device") if code.startswith(("DEV", "FAIL-01", "FAIL-02", "FAIL-03", "TRD-03")) else _n(len(xs), word, PLURAL.get(word))
            subj = f"{head}: {subject}" if sev != INFO else f"{head} for information ({code}): {subject}"
            out.append(Finding(sev, area, code, subj, _top([i.text for i in xs], 6, "; "), fix if sev != INFO or code == "RING-05"
                               else "No action unless it changes before the next promotion.", s.owner(owner), [i.text.split(":")[0] for i in xs]))
    sm = summary(d, rv)
    out.append(Finding(INFO, "Rings and gates", "MET-01", f"{sm['devices']} devices, {pct(sm['current_share'])} on the {sm['month']} build",
                       f"{sm['behind']} behind, {sm['window']} still inside their ring's window; next promotion: {sm['next_gate'] or 'none'}",
                       "Track it at every patch meeting.", s.owner("rings")))
    out.sort(key=lambda f: (ORDER[f.severity], AREAS.index(f.area), f.code))
    return out


def summary(d: Data, rv: dict) -> dict:
    devs, mi = rv["devices"], rv["month"]
    reasons = Counter(r["reason"] for r in devs if r["reason"])
    nxt = next((g for g in rv["gates"] if g["state"] == "next"), None)
    tr = rv["trend"]["all"]
    return dict(
        month=mi["month"], release=mi["release"], kb=", ".join(f"KB{k}" for k in mi["b_kb"]), devices=len(devs),
        current=sum(r["current"] for r in devs), current_share=sum(r["current"] for r in devs) / len(devs) if devs else 0,
        behind=sum(r["behind"] for r in devs), window=sum(r["reason"] in NOT_BEHIND for r in devs), reasons=reasons,
        restart=reasons.get("restart pending", 0), failed=reasons.get("failed", 0), stale=reasons.get("not checked in", 0),
        no_ring=sum(r["ring"] == NO_RING for r in devs), two_rings=sum(len(r["rings"]) > 1 for r in devs),
        paused=[p.name for p in d.policies if is_paused(p, d.as_of)], drift=sum(r["drift"] for r in devs),
        vip_wrong=len(rv["composition"]["wrong"]), promoted_bad=sum(1 for g in rv["gates"] if g["state"] == "promoted" and not g["go"]),
        next_gate=(f"{nxt['nxt']} on {_d(nxt['when'])}: {'GO' if nxt['go'] else 'NO-GO'}" if nxt else ""), next=nxt,
        trend14=[(r["month"], r["shares"].get(14)) for r in tr], days=(d.today - mi["release"]).days,
        failure_codes=len(rv["failures"]), repeat=len(rv["trend"]["repeat"]),
    )


def area_status(findings: list[Finding]) -> dict[str, str]:
    st = {}
    for a in AREAS:
        sev = [f.severity for f in findings if f.area == a and f.severity != INFO]
        st[a] = CRITICAL if CRITICAL in sev else WARNING if sev else "ok"
    return st


def overall(findings: list[Finding]) -> str:
    st = set(area_status(findings).values())
    return VERDICT[CRITICAL] if CRITICAL in st else VERDICT[WARNING] if WARNING in st else VERDICT[None]


def now_label(when: datetime) -> str:
    return f"{when:%a %d %b %Y}"


__all__ = ["AREAS", "CRITICAL", "WARNING", "INFO", "Finding", "Issue", "review", "run_all", "summary", "area_status", "overall"]
