<#
.SYNOPSIS
    Read-only export of the Windows devices, the update ring policies and their groups from Microsoft Intune (Microsoft Graph), the update
    status from Windows Update for Business reports (Log Analytics) and, optionally, the software update deployments of Configuration
    Manager, written as the CSV files that ringtrack reads.

.DESCRIPTION
    Only read operations. Nothing is created, changed, assigned, paused or deleted, and no secret is written to disk.

    Microsoft Graph (Microsoft.Graph PowerShell SDK), delegated sign-in with read-only scopes:
      DeviceManagementManagedDevices.Read.All   managed devices
      DeviceManagementConfiguration.Read.All    update ring policies (device configurations) and their assignments
      GroupMember.Read.All                      the ring groups and their device members
      User.Read.All                             only with -IncludeUserProfile: department and office of the primary user
    If the device members of a group come back without their deviceId, add Device.Read.All (read-only) to -Scopes.

      - devices.csv:       Get-MgDeviceManagementManagedDevice, Windows devices: deviceName, id, azureADDeviceId, osVersion, model,
                           manufacturer, lastSyncDateTime, userPrincipalName, deviceCategoryDisplayName, managementAgent and
                           configurationManagerClientEnabledFeatures.windowsUpdateForBusiness (true: the Windows Update policies workload
                           is in Intune). groups: the ring groups (and ConfigMgr collections) the device is a member of. department and
                           site: from the primary user with -IncludeUserProfile (department, officeLocation), or fill them in yourself.
      - ring-policies.csv: Get-MgDeviceManagementDeviceConfiguration, only #microsoft.graph.windowsUpdateForBusinessConfiguration (the
                           update rings), with qualityUpdatesDeferralPeriodInDays, featureUpdatesDeferralPeriodInDays,
                           deadlineForQualityUpdatesInDays, deadlineForFeatureUpdatesInDays, deadlineGracePeriodInDays,
                           qualityUpdatesPaused, qualityUpdatesPauseStartDate, qualityUpdatesPauseExpiryDateTime, featureUpdatesPaused and
                           lastModifiedDateTime; assignedGroups from Get-MgDeviceManagementDeviceConfigurationAssignment (included groups).

    Windows Update for Business reports (-WorkspaceId, needs the Az.Accounts and Az.OperationalInsights modules and Log Analytics Reader
    on the workspace): one KQL query with Invoke-AzOperationalInsightsQuery over UCClientUpdateStatus (the latest record per device and
    update, quality and feature updates released in the last -TrendMonths months), UCUpdateAlert (active alerts: ErrorCode, AlertSubtype)
    and UCClient (LastWUScanTime), written as update-status.csv.

    Configuration Manager (optional, -SiteCode, on a machine with the console): the ConfigurationManager module, read-only cmdlets only.
    Get-CMSoftwareUpdateDeployment for the deployments whose name matches -DeploymentNameLike: one ring-policies.csv row per deployment
    (source ConfigMgr; quality deferral = days from Patch Tuesday to the available time; deadline = days from available to the
    enforcement deadline), its collection from Get-CMCollection and the members from Get-CMCollectionMember, which go into the groups
    column of devices.csv. Get-CMSoftwareUpdateDeploymentStatus is written to configmgr-deployment-status.csv for reference.

    Not exported: releases.csv (the builds, versions and known issues of Windows release health; see docs/data-format.md),
    incidents.csv (from your ITSM tool) and settings.json.

.PARAMETER RingGroupLike
    Wildcard for the Entra ID groups assigned to the update rings, used to fill the groups column of devices.csv (default: every group an
    update ring policy is assigned to).

.PARAMETER WorkspaceId
    The Log Analytics workspace (customer ID) of Windows Update for Business reports. Without it, update-status.csv is not written.

.PARAMETER TrendMonths
    How many months of update status to export (3 by default).

.PARAMETER SiteCode
    Configuration Manager site code, for the co-managed devices whose Windows Update workload is still in ConfigMgr.

.PARAMETER DeploymentNameLike
    Wildcard for the ConfigMgr software update deployments that act as rings (default 'SUM Ring*').

.PARAMETER IncludeUserProfile
    Read the department and office of each primary user (User.Read.All) for the department and site columns.

.EXAMPLE
    .\scripts\Export-UpdateRingData.ps1 -OutputFolder .\data -WorkspaceId 00000000-0000-0000-0000-000000000000 -IncludeUserProfile

.EXAMPLE
    .\scripts\Export-UpdateRingData.ps1 -OutputFolder .\data -WorkspaceId $ws -SiteCode CM1 -DeploymentNameLike 'SUM Ring*'
#>
[CmdletBinding()]
param(
    [string] $OutputFolder = '.\data',
    [string] $RingGroupLike = '*',
    [string] $WorkspaceId,
    [int] $TrendMonths = 3,
    [string] $SiteCode,
    [string] $DeploymentNameLike = 'SUM Ring*',
    [switch] $IncludeUserProfile,
    [string[]] $Scopes = @('DeviceManagementManagedDevices.Read.All', 'DeviceManagementConfiguration.Read.All', 'GroupMember.Read.All')
)

$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path $OutputFolder | Out-Null

function Write-Csv([object[]] $Rows, [string] $Name, [string[]] $Columns) {
    $path = Join-Path $OutputFolder $Name
    @($Rows) | Select-Object -Property $Columns | Export-Csv -Path $path -NoTypeInformation -Encoding utf8
    Write-Host ("{0,7} rows -> {1}" -f @($Rows).Count, $path)
}

function Get-PatchTuesday([datetime] $Day) {
    $first = Get-Date -Year $Day.Year -Month $Day.Month -Day 1 -Hour 0 -Minute 0 -Second 0
    $offset = (2 - [int] $first.DayOfWeek + 7) % 7          # the first Tuesday
    $first.AddDays($offset + 7)
}

if ($IncludeUserProfile) { $Scopes += 'User.Read.All' }
Import-Module Microsoft.Graph.Authentication, Microsoft.Graph.DeviceManagement, Microsoft.Graph.Groups
Connect-MgGraph -Scopes $Scopes -NoWelcome | Out-Null

# ---------------------------------------------------------------- update ring policies and their groups
$rings = Get-MgDeviceManagementDeviceConfiguration -All |
    Where-Object { $_.AdditionalProperties.'@odata.type' -eq '#microsoft.graph.windowsUpdateForBusinessConfiguration' }
$groupName = @{}
$policyRows = foreach ($p in $rings) {
    $a = $p.AdditionalProperties
    $targets = Get-MgDeviceManagementDeviceConfigurationAssignment -DeviceConfigurationId $p.Id -All |
        Where-Object { $_.Target.AdditionalProperties.'@odata.type' -eq '#microsoft.graph.groupAssignmentTarget' }
    $names = foreach ($t in $targets) {
        $gid = $t.Target.AdditionalProperties.groupId
        if (-not $groupName.ContainsKey($gid)) { $groupName[$gid] = (Get-MgGroup -GroupId $gid -Property displayName).DisplayName }
        $groupName[$gid]
    }
    [pscustomobject] @{
        displayName = $p.DisplayName; id = $p.Id; source = 'Intune'; assignedGroups = ($names | Sort-Object -Unique) -join ';'
        qualityUpdatesDeferralPeriodInDays = $a.qualityUpdatesDeferralPeriodInDays; featureUpdatesDeferralPeriodInDays = $a.featureUpdatesDeferralPeriodInDays
        deadlineForQualityUpdatesInDays = $a.deadlineForQualityUpdatesInDays; deadlineForFeatureUpdatesInDays = $a.deadlineForFeatureUpdatesInDays
        deadlineGracePeriodInDays = $a.deadlineGracePeriodInDays; qualityUpdatesPaused = $a.qualityUpdatesPaused
        qualityUpdatesPauseStartDate = $a.qualityUpdatesPauseStartDate; qualityUpdatesPauseExpiryDateTime = $a.qualityUpdatesPauseExpiryDateTime
        featureUpdatesPaused = $a.featureUpdatesPaused; lastModifiedDateTime = $p.LastModifiedDateTime
    }
}

# ---------------------------------------------------------------- ring group members (by Entra device ID)
$memberOf = @{}
foreach ($gid in @($groupName.Keys)) {
    if ($groupName[$gid] -notlike $RingGroupLike) { continue }
    foreach ($m in Get-MgGroupMember -GroupId $gid -All) {
        $devId = $m.AdditionalProperties.deviceId
        if ($devId) { $memberOf[$devId.ToLower()] = @($memberOf[$devId.ToLower()]) + $groupName[$gid] | Where-Object { $_ } }
    }
}

# ---------------------------------------------------------------- Configuration Manager deployments (optional, read-only)
$cmMembers = @{}
if ($SiteCode) {
    Import-Module (Join-Path (Split-Path $env:SMS_ADMIN_UI_PATH -Parent) 'ConfigurationManager.psd1')
    Push-Location "$($SiteCode):"
    try {
        $status = [System.Collections.Generic.List[object]]::new()
        foreach ($dep in Get-CMSoftwareUpdateDeployment | Where-Object AssignmentName -like $DeploymentNameLike) {
            $coll = Get-CMCollection -Id $dep.TargetCollectionID
            foreach ($m in Get-CMCollectionMember -CollectionId $dep.TargetCollectionID) { $cmMembers[$m.Name.ToLower()] = @($cmMembers[$m.Name.ToLower()]) + $coll.Name | Where-Object { $_ } }
            $pt = Get-PatchTuesday $dep.StartTime
            $policyRows = @($policyRows) + [pscustomobject] @{
                displayName = $dep.AssignmentName; id = $dep.AssignmentUniqueID; source = 'ConfigMgr'; assignedGroups = $coll.Name
                qualityUpdatesDeferralPeriodInDays = [int] ($dep.StartTime.Date - $pt.Date).TotalDays
                featureUpdatesDeferralPeriodInDays = ''; deadlineForQualityUpdatesInDays = [int] ($dep.EnforcementDeadline.Date - $dep.StartTime.Date).TotalDays
                deadlineForFeatureUpdatesInDays = ''; deadlineGracePeriodInDays = ''; qualityUpdatesPaused = $false; qualityUpdatesPauseStartDate = ''
                qualityUpdatesPauseExpiryDateTime = ''; featureUpdatesPaused = $false; lastModifiedDateTime = $dep.LastModificationTime
            }
            foreach ($s in Get-CMSoftwareUpdateDeploymentStatus -InputObject $dep) { $status.Add($s) }
        }
        $status | Export-Csv -Path (Join-Path $OutputFolder 'configmgr-deployment-status.csv') -NoTypeInformation -Encoding utf8
    } finally { Pop-Location }
}
Write-Csv $policyRows 'ring-policies.csv' @('displayName', 'id', 'source', 'assignedGroups', 'qualityUpdatesDeferralPeriodInDays',
    'featureUpdatesDeferralPeriodInDays', 'deadlineForQualityUpdatesInDays', 'deadlineForFeatureUpdatesInDays', 'deadlineGracePeriodInDays',
    'qualityUpdatesPaused', 'qualityUpdatesPauseStartDate', 'qualityUpdatesPauseExpiryDateTime', 'featureUpdatesPaused', 'lastModifiedDateTime')

# ---------------------------------------------------------------- managed devices
$props = 'deviceName', 'id', 'azureADDeviceId', 'osVersion', 'model', 'manufacturer', 'lastSyncDateTime', 'userPrincipalName',
         'deviceCategoryDisplayName', 'managementAgent', 'configurationManagerClientEnabledFeatures', 'operatingSystem'
$devices = Get-MgDeviceManagementManagedDevice -All -Filter "operatingSystem eq 'Windows'" -Property $props
$profileOf = @{}
$devRows = foreach ($d in $devices) {
    $u = $null
    if ($IncludeUserProfile -and $d.UserPrincipalName) {
        if (-not $profileOf.ContainsKey($d.UserPrincipalName)) {
            $profileOf[$d.UserPrincipalName] = Get-MgUser -UserId $d.UserPrincipalName -Property department, officeLocation -ErrorAction SilentlyContinue
        }
        $u = $profileOf[$d.UserPrincipalName]
    }
    $groups = @($memberOf["$($d.AzureAdDeviceId)".ToLower()]) + @($cmMembers["$($d.DeviceName)".ToLower()]) | Where-Object { $_ } | Sort-Object -Unique
    [pscustomobject] @{
        deviceName = $d.DeviceName; id = $d.Id; azureADDeviceId = $d.AzureAdDeviceId; osVersion = $d.OsVersion; model = $d.Model
        manufacturer = $d.Manufacturer; lastSyncDateTime = if ($d.LastSyncDateTime) { $d.LastSyncDateTime.ToString('s') } else { '' }; userPrincipalName = $d.UserPrincipalName
        department = $u.Department; site = $u.OfficeLocation; deviceCategoryDisplayName = $d.DeviceCategoryDisplayName
        managementAgent = $d.ManagementAgent
        'configurationManagerClientEnabledFeatures.windowsUpdateForBusiness' = $d.ConfigurationManagerClientEnabledFeatures.WindowsUpdateForBusiness
        groups = $groups -join ';'
    }
}
Write-Csv $devRows 'devices.csv' @('deviceName', 'id', 'azureADDeviceId', 'osVersion', 'model', 'manufacturer', 'lastSyncDateTime',
    'userPrincipalName', 'department', 'site', 'deviceCategoryDisplayName', 'managementAgent',
    'configurationManagerClientEnabledFeatures.windowsUpdateForBusiness', 'groups')

# ---------------------------------------------------------------- Windows Update for Business reports (Log Analytics)
if ($WorkspaceId) {
    Import-Module Az.Accounts, Az.OperationalInsights
    if (-not (Get-AzContext)) { Connect-AzAccount | Out-Null }
    $kql = @"
let since = startofmonth(now(), -$TrendMonths);
let alerts = UCUpdateAlert
    | where TimeGenerated > ago(2d) and AlertStatus == "Active"
    | summarize arg_max(TimeGenerated, ErrorCode, AlertSubtype) by AzureADDeviceId, UpdateId;
let scans = UCClient
    | where TimeGenerated > ago(2d)
    | summarize arg_max(TimeGenerated, LastWUScanTime) by AzureADDeviceId;
UCClientUpdateStatus
| where TimeGenerated > ago(2d) and UpdateReleaseTime >= since
| where UpdateCategory in ("WindowsQualityUpdate", "WindowsFeatureUpdate")
| summarize arg_max(TimeGenerated, *) by AzureADDeviceId, UpdateId
| join kind=leftouter alerts on AzureADDeviceId, UpdateId
| join kind=leftouter scans on AzureADDeviceId
| project DeviceName, AzureADDeviceId, UpdateCategory, UpdateReleaseTime, TargetVersion, TargetBuild, TargetKBNumber, ClientState,
          ClientSubstate, RestartRequiredTime, UpdateInstalledTime, ErrorCode, AlertSubtype, LastWUScanTime
"@
    $res = Invoke-AzOperationalInsightsQuery -WorkspaceId $WorkspaceId -Query $kql -Wait 300
    $rows = [System.Linq.Enumerable]::ToArray($res.Results)
    Write-Csv $rows 'update-status.csv' @('DeviceName', 'AzureADDeviceId', 'UpdateCategory', 'UpdateReleaseTime', 'TargetVersion', 'TargetBuild',
        'TargetKBNumber', 'ClientState', 'ClientSubstate', 'RestartRequiredTime', 'UpdateInstalledTime', 'ErrorCode', 'AlertSubtype', 'LastWUScanTime')
} else {
    Write-Warning 'No -WorkspaceId: update-status.csv not written (failures, restarts and the trend need it).'
}

Write-Host "Done. Add releases.csv (builds, versions and known issues from Windows release health), incidents.csv if you tag incidents to"
Write-Host "updates, check settings.json (rings, gates), then run: python -m ringtrack review $OutputFolder"
