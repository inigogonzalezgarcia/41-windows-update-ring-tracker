# Data format

Put the files in one folder and run `python -m ringtrack review <folder>`. `devices.csv`, `ring-policies.csv` and `releases.csv` are required; `update-status.csv` adds the failures, restarts, gates and trend, and `incidents.csv` adds the incidents. Comma, semicolon or tab separated, UTF-8. Column names are matched loosely (case, accents and punctuation are ignored), and the alternatives below are accepted. Dates as ISO 8601 (`2026-11-01T22:10:05Z`), `yyyy-MM-dd HH:mm`, `dd/mm/yyyy` or `MM/dd/yyyy`; the time zone suffix is ignored.

`scripts/Export-UpdateRingData.ps1` writes `devices.csv` and `ring-policies.csv` from Microsoft Graph, `update-status.csv` from Windows Update for Business reports in Log Analytics, and the ConfigMgr deployments when you give it a site code.

## How the month, rings and gates are worked out

| Step | Rule |
|---|---|
| Update month | `month` in settings.json, or the month of the latest Patch Tuesday (`B`) build in releases.csv released on or before the reference date |
| Expected build | For each Windows 11 build number (26100 = 24H2, 26200 = 25H2…), the revision of that month's `B` release. A device is **on the build** when the revision in its `osVersion` is that or later, so the month's out-of-band (`OOB`) and preview (`D`) updates count |
| Ring of a device | The rings of the policies assigned to any of its `groups`. A co-managed device with `windowsUpdateForBusiness` false (the workload is in ConfigMgr) takes only the ConfigMgr deployments; true, only the Intune rings. In two rings it is counted in the earliest and flagged (DEV-05) |
| Ring of a policy | The `ring` column, or the first ring in settings.json whose `match` (regular expression) matches the policy name, or the policy name itself |
| Offer, deadline, grace | Offer = Patch Tuesday + `qualityUpdatesDeferralPeriodInDays`; when the policy was paused before the offer, the pause expiry. Deadline = offer + `deadlineForQualityUpdatesInDays`; grace end = deadline + `deadlineGracePeriodInDays`. Each device uses its own policy; the ring timeline uses the policy with most devices |
| Reason a device is not on the build | In this order: version not serviced (no expected build), no ring, ring paused, not checked in (`lastSyncDateTime` older than `stale_days`), failed (error code and not installed), not offered yet, in window (before its grace end), restart pending, past deadline. The first two of the last four are **not behind** |
| Ring compliance at a date | Devices of the ring with `UpdateInstalledTime` before that date; at the reference date also those on the build without an install time |
| Gate between two rings | On the offer date of the next ring: the previous ring at `gate_compliance` or more, failing (current error state) at most `gate_failure_max`, offered at least `gate_min_soak_days` days before, no open incident of priority `gate_incident_max_priority` or higher on the month's KBs in that ring or earlier ones, and no open known issue whose `blocks` names the next ring (or `all`). Past offer dates use the install times; future ones use today's numbers |
| Trend | For each of the last `trend_months` months: the devices with a quality record for that month's release, and the share with `UpdateInstalledTime` within 7, 14 and 21 days of Patch Tuesday (blank until the day is reached) |

## devices.csv

Intune managed devices (`GET /deviceManagement/managedDevices`, Windows only), one row per device.

| Column | Also accepted | Notes |
|---|---|---|
| deviceName | device name, computer name | Joined with the status file when there is no `azureADDeviceId` |
| id | intune device id | Shown |
| azureADDeviceId | entra device id | Joins with `AzureADDeviceId` of the reports and with the group members' `deviceId` |
| osVersion | os build | `10.0.26200.9711`: build 26200, revision 9711 |
| model, manufacturer | oem | FAIL-01 groups failures by model; COMP-02 compares the models of the pilot and the broad ring |
| lastSyncDateTime | last check in | Not checked in after `stale_days` (DEV-03) |
| userPrincipalName | primary user | For chasing |
| department, site | officeLocation, location | From the primary user's profile (`-IncludeUserProfile`) or your own data; site owners come from `site_owners` |
| deviceCategoryDisplayName | device category | `vip_match` (default `trading desktop`) is matched against it and the department for COMP-01 |
| managementAgent | | `configurationManagerClientMdm` for co-managed devices; shown |
| configurationManagerClientEnabledFeatures.windowsUpdateForBusiness | windowsUpdateForBusiness | Co-management: `true` when Intune manages Windows Update, `false` when ConfigMgr does; empty when not co-managed |
| groups | collections, memberOf | The ring groups (Entra ID) and ConfigMgr collections, separated by `;` |

## ring-policies.csv

The update rings (`deviceConfigurations` of type `#microsoft.graph.windowsUpdateForBusinessConfiguration`) and, for co-managed devices, the ConfigMgr software update deployments, one row per policy.

| Column | Also accepted | Notes |
|---|---|---|
| displayName | policy, deployment name | |
| ring | | Optional; otherwise matched with `rings[].match` |
| source | | `Intune` or `ConfigMgr` |
| assignedGroups | groups, target collection | Included groups or the target collection, separated by `;` |
| qualityUpdatesDeferralPeriodInDays | available after days | ConfigMgr: days from Patch Tuesday to the available time |
| featureUpdatesDeferralPeriodInDays | | Compared with the standard |
| deadlineForQualityUpdatesInDays | deadline days | ConfigMgr: days from available to the enforcement deadline |
| deadlineForFeatureUpdatesInDays | | Shown |
| deadlineGracePeriodInDays | grace | Empty for ConfigMgr (read as 0) |
| qualityUpdatesPaused, qualityUpdatesPauseStartDate, qualityUpdatesPauseExpiryDateTime | paused, pause start, pause expiry | Intune pauses a ring for 35 days; the expiry is start + 35 days when missing (RING-03) |
| featureUpdatesPaused, lastModifiedDateTime | | Shown |

Each policy is compared with its ring's standard in settings.json (`quality_deferral_days`, `deadline_days`, `grace_days`, `feature_deferral_days`): any difference is RING-04.

## update-status.csv

Windows Update for Business reports in Log Analytics: `UCClientUpdateStatus` (one record per device and update, the latest snapshot), with `ErrorCode` and `AlertSubtype` from the active `UCUpdateAlert` of the same device and update, and `LastWUScanTime` from `UCClient`. The exporter's KQL query produces exactly these columns. A ConfigMgr or other export works with the same columns.

| Column | Also accepted | Notes |
|---|---|---|
| DeviceName, AzureADDeviceId | device name | Joined with devices.csv by Entra device ID, otherwise by name |
| UpdateCategory | category | `WindowsQualityUpdate` or `WindowsFeatureUpdate` |
| UpdateReleaseTime | release date | Its month places the record in the trend |
| TargetVersion, TargetBuild, TargetKBNumber | target kb | Shown; the feature update target version in DEV-07 |
| ClientState, ClientSubstate | state, substate | `Installed`, `Installing`, `Offering`, `OnHold`…; a substate containing `Restart` or `Reboot` is a pending restart |
| RestartRequiredTime | | Shown in devices-behind.csv |
| UpdateInstalledTime | installed | Used for the gates, the trend and the median days to install |
| ErrorCode | error | Hex (`0x800f0922`) or signed decimal (`-2146498270`); normalised to `0X800F0922` |
| AlertSubtype | alert | `SafeguardHold` on a feature update record is DEV-07 |
| LastWUScanTime | last scan | Shown |

## releases.csv

Copied from [Windows release health](https://learn.microsoft.com/windows/release-health/windows11-release-information) and the known issues page of each version. One row per build, version or known issue, told apart by `kind`.

| kind | Columns used |
|---|---|
| `build` | `month` (`2026-10`), `version` (`25H2`), `build` (`26200.9711`), `kb`, `release_date`, `update_type` (`B` for Patch Tuesday, `OOB`, `D`) |
| `version` | `version`, `build` (the build number, `26200`), `end_of_servicing` (Enterprise and Education) for DEV-06 |
| `issue` | `title`, `version` (affected, `;`), `kb` (originating), `status` (`Mitigated`, `Resolved`…), `opened`, `resolved`, `blocks` (the rings your team decided must not be promoted while it is open, or `all`) |

The demo has the real builds and KBs of July to October 2026, the versions with their end of servicing, and four known issues as published on 2 November 2026.

## incidents.csv

Optional. Incidents your service desk tagged to an update.

| Column | Also accepted | Notes |
|---|---|---|
| number | incident, key | |
| short_description | summary | |
| priority | | `2 - High` or `2` |
| opened_at, resolved_at | opened, resolved | Open at a date when not resolved before it |
| kb | related update | Matched with the KBs of the month (FAIL-04 and the gates) |
| ring | update ring | The ring where it happened; empty counts for every ring |
| devices, rollback | affected devices, rolled back | Shown; a rollback makes FAIL-04 critical |

## settings.json

| Key | Default | Use |
|---|---|---|
| organisation, as_of, month | | Title, reference date (`--as-of` overrides) and update month (empty: the latest) |
| rings | | `[{name, order, match, quality_deferral_days, deadline_days, grace_days, feature_deferral_days, target_share, late}]`: the ring standard, order and target size |
| pilot_ring, broad_ring, vip_ring | | The rings compared by COMP-01 and COMP-02 |
| feature_target | | The target version, shown |
| gate_compliance, gate_failure_max, gate_min_soak_days, gate_incident_max_priority | 0.9, 0.03, 2, 2 | The gate between rings |
| ring_late_days | 2 | RING-01 is critical when the ring is below the gate more than this many days after its grace end |
| stale_days, site_stale_share | 7, 0.15 | DEV-03, critical for a site when this share of its devices has not checked in |
| chase_critical_count | 50 | DEV-01 and DEV-02 are critical from this many devices |
| pause_warning_days, pause_critical_days | 14, 28 | RING-03 |
| vip_match | `trading desktop` | Regular expression on the device category or department |
| pilot_max_department_share, pilot_model_coverage_min, ring_size_tolerance | 0.5, 0.8, 0.4 | COMP-02 and COMP-03 |
| trend_months, trend_days, trend_targets | 3, [7, 14, 21], {7: 0.6, 14: 0.85, 21: 0.95} | TRD-01; set the targets to what your ring design allows |
| failure_cluster_min, model_failure_share_min | 5, 0.2 | FAIL-01: a model with at least this many failures, this share of its devices failing, and 60% of the code's failures |
| eos_warning_days, eos_critical_days | 60, 30 | DEV-06 |
| site_owners | | Site → local team, in the pack and devices-behind.csv |
| error_codes | | Extra error code descriptions (`{"0X80240022": "…"}`) |
| owners | | Owner per area: rings, devices, failures, composition, trend |

## Outputs

| File | Columns |
|---|---|
| devices-behind.csv | Every device not on the build: name, user, site and owner, department, category, model, ring, policy, osVersion, version, expected build, reason, behind (yes/no), error code and meaning, restart pending since, last sync, last scan, days past grace, flags (two rings, non-standard policy, safeguard hold), action |
| rings.csv | Ring, order, policies, devices, share and target, deferral, deadline, grace, paused, offer, deadline and grace end dates, on the build, compliance, behind by reason, in window, median days to install, verdict, issues |
| gates.csv | From and to ring, offer date, state (promoted, next, later), compliance, failure rate, soak days, incidents, known issues, result, reasons |
| failures.csv | Month, update category, error code and meaning, devices, top model with its devices and failure share, sites, rings, verdict |
| composition.csv | Ring, dimension (department, site, model, category, version), value, devices, share of the ring and of the broad ring |
| trend.csv | Month, release date, ring (or All), devices, installed, share by day 7, 14 and 21, median days to install |
| actions.csv, findings.csv | The findings with owner and next step |
