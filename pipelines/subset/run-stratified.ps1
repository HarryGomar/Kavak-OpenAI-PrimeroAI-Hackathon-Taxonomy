param(
    [int[]]$Seeds = @(73,97),
    [ValidateSet('food','fragrance','both')][string]$Domain = 'both',
    [string]$Image = 'm4r:b030afac47d1',
    [string]$Sources = '',
    [string]$GoldSources = '',
    [string[]]$ExcludeRoot = @(),
    [string]$Out = '',
    [switch]$PlanOnly
)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
if (-not $Sources) { $Sources = Join-Path $workspace 'data\subset-sources.json' }
if (-not $GoldSources) { $GoldSources = Join-Path $workspace 'data\gold-sources.json' }
if (-not $ExcludeRoot) { $ExcludeRoot = @(Join-Path $workspace 'data\subsets') }
if (-not $Out) { $Out = Join-Path $workspace 'data\subsets\stratified-n5000' }
if (Test-Path -LiteralPath $Out) { throw "Output already exists: $Out. Set -Out to a new directory." }
if (($Seeds | Select-Object -Unique).Count -ne $Seeds.Count) { throw 'Seeds must be distinct.' }
$sourceConfig = Get-Content -LiteralPath $Sources -Raw | ConvertFrom-Json
$goldConfig = Get-Content -LiteralPath $GoldSources -Raw | ConvertFrom-Json
$dockerSources = @{ pedia_root = '/pedia'; domains = @{} }
$dockerGold = @{ domains = @{} }
$mounts = @('--mount', "type=bind,source=$PSScriptRoot,target=/subset,readonly",
            '--mount', "type=bind,source=$($sourceConfig.pedia_root),target=/pedia,readonly")
$domains = if ($Domain -eq 'both') { @('food','fragrance') } else { @($Domain) }
foreach ($sourceDomain in $domains) {
    $entry = $sourceConfig.domains.$sourceDomain
    $dockerSources.domains[$sourceDomain] = @{
        legacy_bridge_sha256 = $entry.legacy_bridge_sha256
        original_silver = $entry.silver
        silver_snapshot = $entry.silver_snapshot
    }
    foreach ($field in @('silver','native_bridge','legacy_bridge')) {
        $file = (Resolve-Path -LiteralPath $entry.$field).Path
        $target = "/inputs/$sourceDomain-$field.parquet"
        $mounts += @('--mount', "type=bind,source=$file,target=$target,readonly")
        $dockerSources.domains[$sourceDomain][$field] = $target
    }
    $gold = $goldConfig.domains.$sourceDomain
    $dockerEntry = @{ gold_release = $gold.release; views = @{} }
    foreach ($property in $gold.views.PSObject.Properties) {
        $viewName = $property.Name
        $viewFiles = @{ labels_sha256 = $property.Value.labels_sha256 }
        foreach ($field in @('labels','assignments','members','products')) {
            if (-not $property.Value.$field) { continue }
            $file = (Resolve-Path -LiteralPath $property.Value.$field).Path
            $target = "/gold/$sourceDomain/$viewName/$field.parquet"
            $mounts += @('--mount', "type=bind,source=$file,target=$target,readonly")
            $viewFiles[$field] = $target
        }
        $dockerEntry.views[$viewName] = $viewFiles
    }
    if ($dockerEntry.views.Count -eq 0) { throw "No Gold views configured for $sourceDomain" }
    $dockerGold.domains[$sourceDomain] = $dockerEntry
}
$outName = Split-Path -Leaf $Out
$arguments = @('--sources','/inputs/sources.json','--gold-sources','/inputs/gold-sources.json',
               '--out',"/output/$outName",'--domain',$Domain,'--seeds')
$arguments += @($Seeds | ForEach-Object { "$_" })
$index = 0
foreach ($root in $ExcludeRoot) {
    $directory = Get-Item -LiteralPath $root
    if (-not $directory.PSIsContainer) { throw "Exclusion root must be a directory: $root" }
    $target = "/existing/$index"
    $mounts += @('--mount', "type=bind,source=$($directory.FullName),target=$target,readonly")
    $arguments += @('--exclude-root',$target)
    $index++
}
$runRecord = Join-Path $workspace ("tasks\stratified-run-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $runRecord | Out-Null
$dockerConfig = Join-Path $runRecord 'sources.json'
$dockerGoldConfig = Join-Path $runRecord 'gold-sources.json'
$dockerSources | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $dockerConfig -Encoding UTF8
$dockerGold | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $dockerGoldConfig -Encoding UTF8
# Mount the parent so the extractor can refuse an existing output directory.
$outParent = Split-Path -Parent $Out
New-Item -ItemType Directory -Path $outParent -Force | Out-Null
$mounts += @('--mount', "type=bind,source=$dockerConfig,target=/inputs/sources.json,readonly",
             '--mount', "type=bind,source=$dockerGoldConfig,target=/inputs/gold-sources.json,readonly",
             '--mount', "type=bind,source=$outParent,target=/output")
if ($PlanOnly) { $arguments += '--plan-only' }
docker run --rm --network none -e PYTHONDONTWRITEBYTECODE=1 @mounts $Image python /subset/stratified.py @arguments
if ($LASTEXITCODE -ne 0) { throw "Stratified extractor exited $LASTEXITCODE; partial output preserved at $Out" }
Write-Output "Run configuration: $runRecord"
if (-not $PlanOnly) { Write-Output "Stratified Silver subsets: $Out" }
