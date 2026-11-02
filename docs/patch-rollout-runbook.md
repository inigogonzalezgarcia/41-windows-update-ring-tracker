# Patch rollout runbook

One monthly cycle around Patch Tuesday (the second Tuesday), with a short check before every ring promotion and a **monthly patch meeting** (or the CAB item) about three weeks after Patch Tuesday, before the late ring. The tool only reads exports; pauses, promotions and group changes are made in Intune or Configuration Manager as usual, under the change process.

## The ring design it expects

| Ring | Who | Deferral | Deadline + grace | Gate before the next ring |
|---|---|---|---|---|
| Ring 0 - IT | Endpoint engineering and service desk devices | 0 | 2 + 1 | 90% on the build, no P1/P2 |
| Ring 1 - Pilot | A sample of every department, site and model (not only IT) | 3 | 3 + 2 | 90%, failures under 3%, no blocking known issue |
| Ring 2 - Broad | Everyone else | 10 | 5 + 2 | 90%, failures under 3%, no open P1/P2, no issue that blocks the late ring |
| Ring 3 - VIP and trading floor | Trading desktops and executives | 21 | 5 + 2 | – |

Adjust the numbers in `settings.json` (`rings`). Whatever they are, the point is that each ring is only offered the update after the previous one has proved it, and that the trading floor gets it last, on a known date, outside market hours.

## Monthly cycle

| When | What | From the outputs |
|---|---|---|
| Patch Tuesday | Copy the month's builds and KBs from Windows release health into `releases.csv`; read the known issues and decide which rings each one blocks (`blocks`) | – |
| Day 1 to 3 | Ring 0 installs. Check failures by code and the first incidents | `failures.csv`, report section 4 |
| Before each promotion | Run the export and the review; read the gate. On NO-GO, pause the next ring or move its deferral, and record the decision | `gates.csv`, pack section 2 |
| Day 14 | Broad ring past its deadline: chase restarts, failures and devices not checking in by site | `devices-behind.csv` by site, pack section 4 |
| Day 18 to 21 | Monthly patch meeting (below), then the decision on the late ring | `rollout-pack.md` |
| End of month | Ring composition and sizes, policies that drift, feature updates and end of servicing | Pack sections 6 and 7 |

## Export and review

1. Export (read-only):
   ```powershell
   .\scripts\Export-UpdateRingData.ps1 -OutputFolder .\data -WorkspaceId <workspace-id> -IncludeUserProfile
   ```
   Add `-SiteCode <code>` when co-managed devices still take Windows updates from Configuration Manager.
2. Check `releases.csv` (the month's builds and the known issues), `incidents.csv` (the incidents tagged to the update) and `settings.json` (`as_of`, the rings, the gates).
3. Build the outputs:
   ```bash
   python -m ringtrack review data/ --title "Windows update rollout · October 2026"
   ```

## Monthly patch meeting (30 minutes)

| Minutes | Topic | From the pack | Who |
|---|---|---|---|
| 5 | Status by ring: on the build, behind, in window | Headlines, 1 | Endpoint engineering |
| 10 | Go/no-go for the next ring: each gate condition, the incidents and the known issues. Decide: promote, pause, move the deferral | 2, 3, 9 | Endpoint engineering, service owner of the late ring, change manager |
| 5 | Devices to chase by site, with the local IT owner and a date | 4 | Site IT leads |
| 5 | Failure codes, models to fix, repeat offenders | 5 | Endpoint engineering |
| 5 | Ring composition, end of servicing, trend | 6, 7, 8 | Head of end user computing |

Record the decision in the pack (*Decision*, *Decided by*) and in the change, and keep each month's folder (exports, pack, CSVs) as evidence for audits.

## How to read it

- **A gate is a decision, not a date.** The deferral says when a ring *can* be offered the update; the gate says whether it *should*. A ring promoted below the gate (RING-02) is a decision nobody took.
- **A paused ring is a clock.** Intune pauses quality updates for 35 days. A pause set after a bad update and then forgotten leaves the ring a month or two behind, and when it expires the update arrives with no one watching.
- **The late ring is only late for the devices in it.** Trading desktops in the broad ring get the update ten days after Patch Tuesday, in the middle of the trading week, whatever the late ring says.
- **A pilot of IT staff tests IT's apps.** If the pilot has no trading, finance or operations devices, and none of the broad ring's desktop models, it proves very little about them.
- **A whole site going quiet is the network.** Fifty devices that stopped checking in on the same day are a VPN, proxy or certificate problem, not fifty users.
- **One error code on one model is a baseline problem.** Fix the firmware or driver of the model once, instead of repairing devices one by one.
- **Restart pending is the commonest reason to be behind.** The update is installed and does nothing until the device restarts; the deadline and grace only work if devices are on long enough to apply them.
- **Two rings is no ring.** When two update ring policies apply to a device, the conflicting settings are not applied.
- **The trend is the real KPI.** The share on the build at day 14 and 21, month after month, says whether the process works; a single good month says little.
