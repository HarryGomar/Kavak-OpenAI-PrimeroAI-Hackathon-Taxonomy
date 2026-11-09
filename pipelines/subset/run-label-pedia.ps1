param(
    [ValidateSet('food','fragrance','both')][string]$Domain = 'both',
    [string]$Sources = '',
    [string]$Subsets = '',
    [string]$Out = '',
    [string]$Image = 'm4r:b030afac47d1'
)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
if (-not $Sources) { $Sources = Join-Path $workspace 'data\subset-sources.json' }
if (-not $Subsets) { $Subsets = Join-Path $workspace 'data\subsets\pedia-4500-outside-500-v3-content-checked' }
if (-not $Out) { $Out = Join-Path $workspace 'data\subsets\pedia-gold-from-silver-v1' }
if (Test-Path -LiteralPath $Out) { throw "Output exists: $Out. Choose a new -Out." }
$sourceConfig = Get-Content -LiteralPath $Sources -Raw | ConvertFrom-Json
$dockerSources = @{ pedia_root = '/pedia'; domains = @{} }
$mounts = @('--mount', "type=bind,source=$PSScriptRoot,target=/subset,readonly",
            '--mount', "type=bind,source=$((Resolve-Path -LiteralPath $Subsets).Path),target=/raw,readonly",
            '--mount', "type=bind,source=$($sourceConfig.pedia_root),target=/pedia,readonly")
$domains = if ($Domain -eq 'both') { @('food','fragrance') } else { @($Domain) }
foreach ($sourceDomain in $domains) {
    $entry = $sourceConfig.domains.$sourceDomain
    $target = "/inputs/$sourceDomain-legacy.parquet"
    $file = (Resolve-Path -LiteralPath $entry.legacy_bridge).Path
    $mounts += @('--mount', "type=bind,source=$file,target=$target,readonly")
    $dockerSources.domains[$sourceDomain] = @{ legacy_bridge = $target; legacy_bridge_sha256 = $entry.legacy_bridge_sha256 }
}
$record = Join-Path $workspace ("tasks\pedia-label-run-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $record | Out-Null
$dockerConfig = Join-Path $record 'sources.json'
$dockerSources | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $dockerConfig -Encoding UTF8
$outParent = Split-Path -Parent $Out
New-Item -ItemType Directory -Path $outParent -Force | Out-Null
$mounts += @('--mount', "type=bind,source=$dockerConfig,target=/inputs/sources.json,readonly",
             '--mount', "type=bind,source=$outParent,target=/output")
docker run --rm --network none -e PYTHONDONTWRITEBYTECODE=1 @mounts $Image python /subset/label_pedia.py `
    --sources /inputs/sources.json --subsets /raw --out "/output/$(Split-Path -Leaf $Out)" --domain $Domain
if ($LASTEXITCODE -ne 0) { throw "Pedia labeling exited $LASTEXITCODE; partial output retained at $Out" }
Write-Output "Parallel Pedia Gold Parquets: $Out"
Write-Output "Run configuration: $dockerConfig"
