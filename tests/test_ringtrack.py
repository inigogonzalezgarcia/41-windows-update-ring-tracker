import csv
import hashlib
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from ringtrack import cli
from ringtrack.checks import (CRITICAL, INFO, ORDER, WARNING, area_status, classify, month_info, overall, review, run_all, summary)
from ringtrack.model import (Build, Data, Device, Incident, Issue, Policy, Status, Version, error_code, load, load_devices, load_incidents,
                             load_policies, load_releases, load_status, parse_build, settings_from_dict)

AS_OF = datetime(2026, 11, 2, 8, 0)          # Monday, twenty days after the October Patch Tuesday (13 Oct 2026)
RINGS = [{"name": "R0", "order": 0, "match": "Ring 0", "quality_deferral_days": 0, "deadline_days": 2, "grace_days": 1, "feature_deferral_days": 0,
          "target_share": 0.1},
         {"name": "R1", "order": 1, "match": "Ring 1", "quality_deferral_days": 3, "deadline_days": 3, "grace_days": 2, "feature_deferral_days": 0},
         {"name": "R2", "order": 2, "match": "Ring 2", "quality_deferral_days": 10, "deadline_days": 5, "grace_days": 2, "feature_deferral_days": 0},
         {"name": "R3", "order": 3, "match": "Ring 3", "quality_deferral_days": 21, "deadline_days": 5, "grace_days": 2, "feature_deferral_days": 0}]
REL = {"2026-08": datetime(2026, 8, 11), "2026-09": datetime(2026, 9, 8), "2026-10": datetime(2026, 10, 13)}
REV = {"2026-08": 9168, "2026-09": 9445, "2026-10": 9711}


def write(path: Path, header: list[str], rows: list[list], delimiter: str = ",") -> Path:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter=delimiter)
        w.writerow(header)
        w.writerows(rows)
    return path


def pol(name, ring, qd, dl, gr, group=None, **kw) -> Policy:
    return Policy(name, ring, kw.pop("source", "Intune"), [group or ring], qd, 0, dl, None, gr, **kw)


POLS = [pol("Ring 0", "R0", 0, 2, 1), pol("Ring 1", "R1", 3, 3, 2), pol("Ring 2", "R2", 10, 5, 2), pol("Ring 3", "R3", 21, 5, 2)]


def dev(name, group="R2", rev=9711, site="London", **kw) -> Device:
    return Device(name, aad_id="", os_version=f"10.0.{kw.pop('build', 26200)}.{rev}", model=kw.pop("model", "Latitude 7440"),
                  last_sync=kw.pop("last_sync", AS_OF - timedelta(hours=3)), department=kw.pop("department", "Sales"), site=site,
                  category=kw.pop("category", "Laptop"), groups=[group] if group else [], **kw)


def st(name, month="2026-10", day=None, **kw) -> Status:
    inst = REL[month] + timedelta(days=day, hours=10) if day is not None else None
    return Status(name, "", kw.pop("category", "quality"), REL[month], "25H2", f"10.0.26200.{REV[month]}", "5127648",
                  "Installed" if inst else kw.pop("state", "Installing"), kw.pop("substate", "Installed" if inst else "DownloadStart"),
                  installed=inst, **kw)


def builds() -> list[Build]:
    out = [Build(m, "25H2", 26200, REV[m], "5127648" if m == "2026-10" else "", REL[m], "B") for m in REL]
    out.append(Build("2026-10", "25H2", 26200, 9725, "5134133", datetime(2026, 10, 26), "OOB"))
    return out


def data(devices=(), status=(), policies=None, incidents=(), issues=(), versions=None, **raw) -> Data:
    raw.setdefault("rings", RINGS)
    raw.setdefault("pilot_ring", "R1")
    raw.setdefault("broad_ring", "R2")
    raw.setdefault("vip_ring", "R3")
    d = Data(settings_from_dict(raw), AS_OF, list(devices), list(policies if policies is not None else POLS), list(status), builds(),
             versions or {"25H2": Version("25H2", 26200, date(2028, 10, 10))}, list(issues), list(incidents))
    return d


def codes(findings, code):
    return [f for f in findings if f.code == code]


def by_name(rv):
    return {r["dev"].name: r for r in rv["devices"]}


class TestLoading(unittest.TestCase):
    def test_devices_and_policies_from_graph_exports(self):
        with tempfile.TemporaryDirectory() as t:
            dv = write(Path(t) / "dev.csv", ["deviceName", "id", "azureADDeviceId", "osVersion", "model", "manufacturer", "lastSyncDateTime",
                                             "userPrincipalName", "department", "officeLocation", "deviceCategoryDisplayName",
                                             "configurationManagerClientEnabledFeatures.windowsUpdateForBusiness", "groups"],
                       [["PC1", "a1", "AAD-1", "10.0.26200.9711", "Latitude 7440", "Dell Inc.", "2026-11-01T22:10:05Z", "a@contoso.com", "Sales",
                         "Madrid", "Trading desktop", "False", "WUfB-Ring2; SUM-Madrid"]], delimiter=";")
            pp = write(Path(t) / "pol.csv", ["displayName", "source", "assignedGroups", "qualityUpdatesDeferralPeriodInDays",
                                             "deadlineForQualityUpdatesInDays", "deadlineGracePeriodInDays", "qualityUpdatesPaused",
                                             "qualityUpdatesPauseStartDate"],
                       [["WUfB Ring 3 - VIP", "Intune", "G3", "21", "5", "2", "True", "2026-09-28T17:40:00Z"],
                        ["SUM Ring 2 Madrid", "ConfigMgr", "SUM-Madrid", "7", "14", "", "false", ""]])
            d = load_devices(dv)[0]
            p3, cm = load_policies(pp, settings_from_dict({"rings": RINGS}))
        self.assertEqual((d.build, d.aad_id, d.site, d.category, d.groups, d.wufb_intune, d.last_sync),
                         ((26200, 9711), "AAD-1", "Madrid", "Trading desktop", ["WUfB-Ring2", "SUM-Madrid"], False, datetime(2026, 11, 1, 22, 10, 5)))
        self.assertEqual((p3.ring, p3.paused, p3.pause_expiry, p3.quality_deferral, p3.grace), ("R3", True, datetime(2026, 11, 2, 17, 40), 21, 2))
        self.assertEqual((cm.ring, cm.configmgr, cm.deadline, cm.grace), ("R2", True, 14, None))

    def test_status_releases_and_incidents(self):
        with tempfile.TemporaryDirectory() as t:
            sp = write(Path(t) / "st.csv", ["DeviceName", "AzureADDeviceId", "UpdateCategory", "UpdateReleaseTime", "TargetBuild", "ClientState",
                                            "ClientSubstate", "UpdateInstalledTime", "ErrorCode", "AlertSubtype"],
                       [["PC1", "AAD-1", "WindowsQualityUpdate", "10/13/2026", "10.0.26200.9711", "Installing", "RestartRequired", "", "", ""],
                        ["PC2", "", "WindowsFeatureUpdate", "2025-09-30", "10.0.26200.6584", "OnHold", "OnHold", "", "-2146498270", "SafeguardHold"]])
            rp = write(Path(t) / "rel.csv", ["kind", "month", "version", "build", "kb", "release_date", "update_type", "end_of_servicing", "title",
                                             "status", "opened", "resolved", "blocks"],
                       [["version", "", "23H2", "22631", "", "", "", "2026-11-10", "", "", "", "", ""],
                        ["build", "2026-10", "25H2", "26200.9711", "KB5127648", "2026-10-13", "B", "", "", "", "", "", ""],
                        ["issue", "", "25H2", "", "KB5124008", "", "", "", "USB audio", "Mitigated", "2026-09-25", "", "R3; R2"]])
            ip = write(Path(t) / "inc.csv", ["number", "short_description", "priority", "opened_at", "kb", "ring", "devices", "rollback"],
                       [["INC1", "No audio", "2 - High", "2026-10-26 07:12", "KB5127648", "R2", "14", "yes"]])
            a, b = load_status(sp)
            bs, vs, iss = load_releases(rp)
            inc = load_incidents(ip)[0]
        self.assertEqual((a.category, a.restart_pending, a.is_installed, a.key), ("quality", True, False, "aad-1"))
        self.assertEqual((b.category, b.error, b.safeguard), ("feature", "0X800F0922", True))
        self.assertEqual((error_code("0x800f0922"), error_code("800F081F"), error_code("0"), parse_build("OS Build 26100.9725")),
                         ("0X800F0922", "0X800F081F", "", (26100, 9725)))
        self.assertEqual((bs[0].build, bs[0].revision, bs[0].kb, vs["23H2"].end_of_servicing, vs["25H2"].build), (26200, 9711, "5127648",
                                                                                                                  date(2026, 11, 10), 26200))
        self.assertEqual((iss[0].blocks, iss[0].open_at(AS_OF), iss[0].open_at(datetime(2026, 9, 1))), (["R3", "R2"], True, False))
        self.assertEqual((inc.priority, inc.kb, inc.devices, inc.rollback), (2, "5127648", 14, True))


class TestDevices(unittest.TestCase):
    def test_current_build_and_reasons(self):
        paused = pol("Ring 3", "R3", 21, 5, 2, paused=True, pause_start=datetime(2026, 9, 28), pause_expiry=datetime(2026, 11, 2, 17))
        devs = [dev("OK", rev=9711), dev("OOB", rev=9725), dev("OLD", build=22000, rev=9999), dev("NORING", group=None, rev=9445),
                dev("PAUSED", group="R3", rev=9168), dev("STALE", rev=9445, last_sync=datetime(2026, 10, 20)), dev("FAIL", rev=9445),
                dev("RESTART", rev=9445), dev("LATE", rev=9445), dev("PILOT", group="R1", rev=9445), dev("CM", group="SUM", rev=9445, wufb_intune=False)]
        sts = [st("FAIL", error="0X800F0922"), st("RESTART", substate="RestartRequired"), st("LATE")]
        cm = pol("SUM Ring 2", "R2", 7, 14, None, group="SUM", source="ConfigMgr")
        d = data(devs, sts, POLS[:3] + [paused, cm])
        rv = review(d)
        r = by_name(rv)
        self.assertEqual(month_info(d)["expected"], {26200: 9711})
        self.assertTrue(r["OK"]["current"] and r["OOB"]["current"])
        got = {k: v["reason"] for k, v in r.items()}
        self.assertEqual(got, {"OK": "", "OOB": "", "OLD": "version not serviced", "NORING": "no ring", "PAUSED": "ring paused", "STALE": "not checked in",
                               "FAIL": "failed", "RESTART": "restart pending", "LATE": "past deadline", "PILOT": "past deadline", "CM": "in window"})
        self.assertFalse(r["CM"]["behind"])
        self.assertEqual((r["CM"]["policy"].name, r["CM"]["dates"]["grace_end"], r["CM"]["drift"]), ("SUM Ring 2", date(2026, 11, 3), True))
        self.assertEqual((r["LATE"]["past"], r["PAUSED"]["dates"]["offer"]), (3, date(2026, 11, 3)))

    def test_comanagement_workload_and_two_rings(self):
        cm = pol("SUM", "R2", 7, 14, None, group="SUM", source="ConfigMgr")
        devs = [dev("INTUNE", group="R1", wufb_intune=True), dev("CMGR", group="R1", wufb_intune=False), dev("BOTH"), dev("X")]
        devs[2].groups = ["R1", "R2"]
        devs[1].groups = ["R1", "SUM"]
        rv = review(data(devs, policies=POLS + [cm]))
        r = by_name(rv)
        self.assertEqual((r["INTUNE"]["ring"], r["CMGR"]["ring"], r["CMGR"]["policy"].name), ("R1", "R2", "SUM"))
        self.assertEqual((r["BOTH"]["rings"], r["BOTH"]["ring"]), (["R1", "R2"], "R1"))
        f = run_all(data(devs, policies=POLS + [cm]))
        self.assertEqual(codes(f, "DEV-05")[0].items, ["12 devices in two rings (R1 + R2)".replace("12", "1")])

    def test_site_stale_restart_threshold_eos_and_safeguard(self):
        devs = ([dev(f"F{k}", site="Frankfurt", rev=9445, last_sync=datetime(2026, 10, 21)) for k in range(4)]
                + [dev(f"G{k}", site="Frankfurt") for k in range(6)] + [dev(f"L{k}", rev=9445, last_sync=datetime(2026, 10, 21)) for k in range(1)]
                + [dev(f"L{k + 1}") for k in range(19)] + [dev(f"R{k}", rev=9445) for k in range(3)]
                + [dev("OLD23", build=22631, rev=7652, site="Madrid")])
        sts = [st(f"R{k}", substate="RestartRequired") for k in range(3)]
        sts.append(Status("OLD23", category="feature", release=datetime(2025, 9, 30), target_version="25H2", state="OnHold", alert="SafeguardHold"))
        d = data(devs, sts, versions={"25H2": Version("25H2", 26200, date(2028, 10, 10)), "23H2": Version("23H2", 22631, date(2026, 11, 10))},
                 chase_critical_count=3)
        d.builds.append(Build("2026-10", "23H2", 22631, 7652, "5126653", REL["2026-10"], "B"))
        f = run_all(d)
        dev3 = codes(f, "DEV-03")
        self.assertEqual([(x.severity, x.items) for x in dev3], [(CRITICAL, ["Frankfurt"]), (WARNING, ["London"])])
        self.assertIn("40% of the site", dev3[0].detail)
        self.assertEqual([(x.severity, x.subject.split(":")[0]) for x in codes(f, "DEV-02")], [(CRITICAL, "3 devices")])
        self.assertEqual((codes(f, "DEV-06")[0].severity, codes(f, "DEV-07")[0].severity), (CRITICAL, WARNING))
        self.assertIn("8 days", codes(f, "DEV-06")[0].detail)


class TestRingsAndGates(unittest.TestCase):
    def test_behind_paused_and_drift(self):
        paused = pol("Ring 3", "R3", 21, 5, 2, paused=True, pause_start=datetime(2026, 9, 28), pause_expiry=datetime(2026, 11, 2, 17))
        legacy = pol("Ring 2 (2024)", "R2", 7, 7, 3, group="LEG")
        devs = [dev(f"B{k}", rev=9711 if k < 7 else 9445) for k in range(10)] + [dev("V", group="R3", rev=9168), dev("LEG1", group="LEG")]
        sts = [st(f"B{k}", day=11) for k in range(7)] + [st(f"B{k}") for k in range(7, 10)]
        f = run_all(data(devs, sts, POLS[:3] + [paused, legacy]))
        r1 = codes(f, "RING-01")[0]
        self.assertEqual((r1.severity, r1.items), (CRITICAL, ["R2"]))
        self.assertIn("73%", r1.detail)
        r3 = codes(f, "RING-03")[0]
        self.assertEqual(r3.severity, CRITICAL)
        self.assertIn("paused for 35 days", r3.detail)
        self.assertIn("missed 2026-09", r3.detail)
        r4 = codes(f, "RING-04")[0]
        self.assertIn("deadline 7 days (standard 5)", r4.detail)
        self.assertIn("grace 3 days (standard 2)", r4.detail)

    def test_promoted_without_gate_and_next_promotion(self):
        devs = ([dev(f"P{k}", group="R1") for k in range(10)] + [dev(f"B{k}") for k in range(10)] + [dev("V", group="R3", rev=9445)]
                + [dev("Z", group="R0")])
        # pilot: 6 of 10 installed before the broad ring was offered on 23 Oct, the rest after
        sts = ([st(f"P{k}", day=4 if k < 6 else 12) for k in range(10)] + [st(f"B{k}", day=11) for k in range(10)] + [st("Z", day=0)])
        inc = Incident("INC9", "Headsets", 2, datetime(2026, 10, 26), None, "5127648", "R2", 3, True)
        issue = Issue("USB audio", ["25H2"], "5124008", "Mitigated", datetime(2026, 9, 25), None, ["R3"])
        rv = review(data(devs, sts, incidents=[inc], issues=[issue]))
        g = {x["nxt"]: x for x in rv["gates"]}
        self.assertEqual((g["R1"]["state"], g["R1"]["go"]), ("promoted", True))
        self.assertEqual((g["R2"]["state"], g["R2"]["go"], round(g["R2"]["compliance"], 2)), ("promoted", False, 0.6))
        self.assertEqual((g["R3"]["state"], g["R3"]["go"], g["R3"]["when"]), ("next", False, date(2026, 11, 3)))
        self.assertEqual(len(g["R3"]["reasons"]), 2)
        self.assertIn("INC9", g["R3"]["reasons"][0])
        f = run_all(data(devs, sts, incidents=[inc], issues=[issue]))
        self.assertEqual((codes(f, "RING-02")[0].severity, codes(f, "RING-05")[0].severity, codes(f, "FAIL-04")[0].severity),
                         (CRITICAL, CRITICAL, CRITICAL))
        rv = review(data(devs, sts))
        self.assertTrue(next(x for x in rv["gates"] if x["nxt"] == "R3")["go"])
        self.assertEqual(codes(run_all(data(devs, sts)), "RING-05")[0].severity, INFO)


class TestFailuresCompositionTrend(unittest.TestCase):
    def test_model_cluster_codes_and_repeats(self):
        devs = ([dev(f"E{k}", model="HP EliteBook 840 G8", rev=9445) for k in range(6)] + [dev(f"E{k + 6}", model="HP EliteBook 840 G8") for k in range(6)]
                + [dev(f"O{k}", model="OptiPlex 7010", rev=9445) for k in range(3)] + [dev(f"N{k}") for k in range(20)])
        sts = ([st(f"E{k}", error="0X800F0922") for k in range(6)] + [st(f"O{k}", error="0X80070070") for k in range(3)]
               + [st("O0", "2026-09", error="0X80070070"), st("O0", "2026-08", error="0X80070070")])
        f = run_all(data(devs, sts))
        f1 = codes(f, "FAIL-01")[0]
        self.assertEqual((f1.severity, f1.subject.split(":")[0]), (CRITICAL, "6 devices"))
        self.assertIn("HP EliteBook 840 G8: 6 of 12 devices (50%)", f1.detail)
        self.assertIn("ERROR_DISK_FULL", codes(f, "FAIL-02")[0].detail)
        self.assertIn("O0", codes(f, "FAIL-03")[0].detail)

    def test_trading_desktops_pilot_and_sizes(self):
        devs = ([dev(f"T{k}", category="Trading desktop", group="R3", department="Trading") for k in range(4)]
                + [dev(f"TB{k}", category="Trading desktop", department="Trading") for k in range(2)]
                + [dev(f"P{k}", group="R1", department="Technology") for k in range(9)] + [dev("P9", group="R1", department="Finance")]
                + [dev(f"B{k}", model="OptiPlex 7010", site=["London", "Milan"][k % 2], department=["Sales", "Ops", "Risk"][k % 3]) for k in range(30)]
                + [dev("Z", group="R0")])
        rv = review(data(devs, vip_match="trading desktop", ring_size_tolerance=0.3))
        comp = rv["composition"]
        self.assertEqual(len(comp["wrong"]), 2)
        texts = [i.text for i in comp["issues"]]
        self.assertTrue(any(i.code == "COMP-01" and i.severity == CRITICAL for i in comp["issues"]))
        self.assertTrue(any("90% of the pilot is Technology" in x for x in texts))
        self.assertTrue(any("cover 6%" in x for x in texts))
        self.assertTrue(any("no pilot devices at Milan" in x for x in texts))
        self.assertTrue(any(i.code == "COMP-03" and "R0" in i.text for i in comp["issues"]))

    def test_trend_by_day_falling_and_repeat(self):
        devs = [dev(f"D{k}", group="R0", rev=9711 if k else 9445) for k in range(10)]
        sts = []
        for k in range(10):
            sts.append(st(f"D{k}", "2026-08", day=2 if k > 0 else 30))                 # 90% by day 7
            sts.append(st(f"D{k}", "2026-09", day=2 if 0 < k < 8 else 30))                 # 70%
            sts.append(st(f"D{k}", "2026-10", day=2 if 0 < k < 3 else (None if k == 0 else 12)))  # 20%
        rv = review(data(devs, sts, trend_targets={"7": 0.8, "14": 0.9, "21": 0.95}))
        allr = rv["trend"]["all"]
        self.assertEqual([round(r["shares"][7], 2) for r in allr], [0.9, 0.7, 0.2])
        self.assertIsNone(allr[-1]["shares"][21])
        t1 = [i for i in rv["trend"]["issues"] if i.code == "TRD-01"]
        self.assertIn("falling every month", t1[0].text)
        self.assertEqual([r["dev"].name for r in rv["trend"]["repeat"]], ["D0"])
        self.assertTrue(any(i.code == "TRD-02" for i in rv["trend"]["issues"]))


class TestVerdictAndDemo(unittest.TestCase):
    def test_status_by_area_and_overall(self):
        ok = [dev(f"D{k}", group=g) for k, g in enumerate(["R0"] * 3 + ["R1"] * 3 + ["R2"] * 20 + ["R3"] * 4)]
        sts = [st(d.name, day=0) for d in ok]
        f = run_all(data(ok, sts, rings=[dict(r, target_share=None) for r in RINGS], pilot_ring=""))
        self.assertEqual((overall(f), set(area_status(f).values())), ("on track", {"ok"}))
        f = run_all(data(ok + [dev("NR", group=None)], sts, rings=[dict(r, target_share=None) for r in RINGS], pilot_ring=""))
        self.assertEqual((overall(f), area_status(f)["Devices behind"]), ("attention", WARNING))
        f = run_all(data(ok + [dev("TD", category="Trading desktop")], sts, rings=[dict(r, target_share=None) for r in RINGS], pilot_ring=""))
        self.assertEqual((overall(f), area_status(f)["Composition"], area_status(f)["Failures"]), ("action needed", CRITICAL, "ok"))

    def test_demo_end_to_end_is_deterministic(self):
        hashes = []
        with tempfile.TemporaryDirectory() as t:
            for k in range(2):
                out = Path(t) / f"out{k}"
                self.assertEqual(cli.main(["demo", "--data", str(Path(t) / f"data{k}"), "--out", str(out)]), 0)
                self.assertEqual(sorted(p.name for p in out.iterdir()), sorted(cli.OUTPUTS))
                hashes.append({n: hashlib.sha1((out / n).read_bytes()).hexdigest() for n in cli.OUTPUTS}
                              | {n.name: hashlib.sha1(n.read_bytes()).hexdigest() for n in (Path(t) / f"data{k}").iterdir()})
            self.assertEqual(hashes[0], hashes[1])
            d = load(Path(t) / "data0")
            self.assertEqual(json.loads((Path(t) / "data0" / "settings.json").read_text(encoding="utf-8"))["as_of"], "2026-11-02 08:00")
        rv = review(d)
        f = run_all(d, rv)
        sm = summary(d, rv)
        self.assertEqual([x.severity for x in f], sorted((x.severity for x in f), key=ORDER.get))
        self.assertEqual(overall(f), "action needed")
        for c in ("RING-01", "RING-02", "RING-03", "RING-04", "RING-05", "DEV-01", "DEV-02", "DEV-03", "DEV-04", "DEV-05", "DEV-06", "DEV-07",
                  "FAIL-01", "FAIL-02", "FAIL-03", "FAIL-04", "COMP-01", "COMP-02", "COMP-03", "TRD-01", "TRD-03"):
            self.assertIn(c, {x.code for x in f})
        self.assertEqual((d.settings.organisation, sm["month"], sm["devices"], sm["no_ring"], sm["two_rings"], sm["vip_wrong"], sm["restart"]),
                         ("Contoso Markets", "2026-10", 1500, 40, 12, 60, 93))
        self.assertEqual(sm["paused"], ["WUfB Ring 3 - VIP and trading floor"])
        self.assertTrue(0.65 <= sm["current_share"] <= 0.72)
        g = {x["nxt"]: x for x in rv["gates"]}
        self.assertTrue(g["Ring 1 - Pilot"]["go"])
        self.assertFalse(g["Ring 2 - Broad"]["go"])
        self.assertTrue(0.65 <= g["Ring 2 - Broad"]["compliance"] < 0.8)
        self.assertEqual((g["Ring 3 - VIP and trading floor"]["state"], g["Ring 3 - VIP and trading floor"]["go"]), ("next", False))
        f1 = codes(f, "FAIL-01")[0]
        self.assertIn("HP EliteBook 840 G8: 38 of", f1.detail)
        self.assertIn("0X800F0922", f1.detail)
        self.assertEqual(codes(f, "DEV-03")[0].items, ["Frankfurt"])
        t14 = [x for _, x in sm["trend14"]]
        self.assertTrue(t14[0] > t14[1] > t14[2])

    def test_review_reports_missing_files(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(cli.main(["review", t, "--out", str(Path(t) / "o")]), 2)
            self.assertEqual(cli.main(["review", "--out", str(Path(t) / "o")]), 2)
            write(Path(t) / "devices.csv", ["deviceName"], [["PC1"]])
            self.assertEqual(cli.main(["review", t, "--out", str(Path(t) / "o")]), 2)
        _ = classify


if __name__ == "__main__":
    unittest.main()
