"""Command line: `demo` writes the fictional Contoso Markets exports to sample_data/ and builds the outputs; `review` runs on your own exports."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import report, simulate
from .checks import overall, pct, review, run_all, summary
from .model import load, parse_dt

OUTPUTS = ("report.html", "rollout-pack.md", "devices-behind.csv", "rings.csv", "gates.csv", "failures.csv", "composition.csv", "trend.csv",
           "actions.csv", "findings.csv")


def run(data: Path, out: Path, title: str, as_of: datetime | None = None) -> dict:
    d = load(data, as_of)
    rv = review(d)
    findings = run_all(d, rv)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.html").write_text(report.render_html(d, rv, findings, title), encoding="utf-8")
    (out / "rollout-pack.md").write_text(report.pack_md(d, rv, findings, title), encoding="utf-8")
    report.write_devices(d, rv, out / "devices-behind.csv")
    report.write_rings(d, rv, out / "rings.csv")
    report.write_gates(d, rv, out / "gates.csv")
    report.write_failures(d, rv, out / "failures.csv")
    report.write_composition(d, rv, out / "composition.csv")
    report.write_trend(d, rv, out / "trend.csv")
    report.write_actions(findings, out / "actions.csv")
    report.write_findings(findings, out / "findings.csv")
    sm = summary(d, rv)
    sm.update(overall=overall(findings), critical=sum(f.severity == "critical" for f in findings), warning=sum(f.severity == "warning" for f in findings))
    return sm


def _when(value: str) -> datetime:
    d = parse_dt(value)
    if not d:
        raise argparse.ArgumentTypeError(f"not a date (YYYY-MM-DD or 'YYYY-MM-DD HH:MM'): {value}")
    return d


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ringtrack", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    dm = sub.add_parser("demo", help="write the fictional exports to sample_data/ and build the outputs")
    dm.add_argument("--data", type=Path, default=Path("sample_data"))
    dm.add_argument("--out", type=Path, default=Path("output"))
    rv = sub.add_parser("review", help="build the outputs from your own exports")
    rv.add_argument("data", type=Path, nargs="?", help="folder with devices.csv, ring-policies.csv, releases.csv and the optional files")
    rv.add_argument("--data", dest="data_opt", type=Path, help="same as the positional folder")
    rv.add_argument("--out", type=Path, default=Path("output"))
    rv.add_argument("--title", default="Windows update rollout")
    rv.add_argument("--as-of", type=_when, help="reference date (default: settings.json, or now)")
    a = p.parse_args(argv)
    if a.cmd == "demo":
        simulate.write(a.data)
        sm = run(a.data, a.out, f"{simulate.ORG} · Windows update rollout, October 2026 (review of 2 November)")
    else:
        folder = a.data or a.data_opt
        if not folder:
            print("error: give the folder with the exports", file=sys.stderr)
            return 2
        try:
            sm = run(folder, a.out, a.title, a.as_of)
        except (FileNotFoundError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    print(f"{sm['overall'].upper()} · {sm['month']} ({sm['kb']}, day {sm['days']}): {sm['current']} of {sm['devices']} devices on the build "
          f"({pct(sm['current_share'])}) · behind {sm['behind']} (restart pending {sm['restart']}, failed {sm['failed']}, not checked in "
          f"{sm['stale']}, no ring {sm['no_ring']}) · in window {sm['window']} · paused rings {len(sm['paused'])} · next: {sm['next_gate'] or 'none'} · "
          f"{sm['critical']} critical, {sm['warning']} warnings")
    print(f"outputs in {a.out}/: {', '.join(OUTPUTS)}")
    return 0
