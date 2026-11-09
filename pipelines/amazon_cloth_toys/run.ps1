param(
    [string]$Inputs = '',
    [string]$Out = '',
    [string]$M4RRepo = '',
    [string]$Template = '',
    [string]$Domains = 'clothing,footwear,games',
    [string]$Image = 'm4r:b030afac47d1',
    [int]$Limit = 0
)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$configPath = Join-Path $workspace 'data\subset-sources.json'
$sources = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
if (-not $Template) { $Template = $sources.domains.food.silver }
$Template = (Resolve-Path -LiteralPath $Template).Path
if (-not $M4RRepo) {
    $candidate = Split-Path -Parent $Template
    while ($candidate -and -not (Test-Path -LiteralPath (Join-Path $candidate 'repo\pyproject.toml'))) {
        $candidate = Split-Path -Parent $candidate
    }
    if (-not $candidate) { throw 'Cannot locate M4R repo from template path; pass -M4RRepo.' }
    $M4RRepo = Join-Path $candidate 'repo'
}
$M4RRepo = (Resolve-Path -LiteralPath $M4RRepo).Path
if (-not $Inputs) { $Inputs = Join-Path $workspace 'data\different_lines\garments-footwear-filtered' }
$Inputs = (Resolve-Path -LiteralPath $Inputs).Path
if (-not $Out) { $Out = Join-Path $workspace 'data\different_lines\silver' }
if (Test-Path -LiteralPath $Out) { throw "Output exists: $Out. Use a new -Out directory." }
if ($Limit -lt 0) { throw 'Limit must be nonnegative.' }
$rawSource = Join-Path $workspace 'data\different_lines\amazon.parquet'
$commit = git -C $M4RRepo rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw 'Cannot read M4R revision.' }
$config = @{
    template = '/inputs/food-template.parquet'; original_template = $Template
    template_sha256 = (Get-FileHash -LiteralPath $Template -Algorithm SHA256).Hash.ToLowerInvariant()
    raw_source = '/inputs/amazon.parquet'; m4r_commit = $commit; domains = @{}
}
$mounts = @('--mount', "type=bind,source=$PSScriptRoot,target=/pipeline,readonly",
            '--mount', "type=bind,source=$M4RRepo,target=/m4r,readonly",
            '--mount', "type=bind,source=$Template,target=/inputs/food-template.parquet,readonly",
            '--mount', "type=bind,source=$rawSource,target=/inputs/amazon.parquet,readonly")
$selectedDomains = @($Domains.Split(',') | ForEach-Object { $_.Trim() })
if (-not $selectedDomains.Count -or @($selectedDomains | Where-Object { $_ -notin @('clothing','games','footwear') }).Count) {
    throw 'Domains must be a comma-separated list of clothing, games, footwear.'
}
foreach ($domain in $selectedDomains) {
    $inputFile = (Resolve-Path -LiteralPath (Join-Path $Inputs "$domain\${domain}_listings.parquet")).Path
    $target = "/inputs/$domain.parquet"
    $mounts += @('--mount', "type=bind,source=$inputFile,target=$target,readonly")
    $config.domains[$domain] = @{ path = $target; original_path = $inputFile }
    $selectionManifest = Join-Path $Inputs "$domain\manifest.json"
    if (Test-Path -LiteralPath $selectionManifest) {
        $config.domains[$domain].selection_manifest = Get-Content -LiteralPath $selectionManifest -Raw | ConvertFrom-Json
        $config.domains[$domain].selection_manifest_sha256 = (Get-FileHash -LiteralPath $selectionManifest -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
$taskRecord = Join-Path $workspace ('tasks\amazon-cloth-toys-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $taskRecord | Out-Null
$dockerConfig = Join-Path $taskRecord 'config.json'
$config | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $dockerConfig -Encoding UTF8
$outParent = Split-Path -Parent $Out
New-Item -ItemType Directory -Path $outParent -Force | Out-Null
$outName = Split-Path -Leaf $Out
$mounts += @('--mount', "type=bind,source=$dockerConfig,target=/inputs/config.json,readonly",
             '--mount', "type=bind,source=$outParent,target=/output")
docker run --rm --network none -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/m4r/pipelines:/m4r/src `
    @mounts $Image python /pipeline/parse.py --config /inputs/config.json --out "/output/$outName" --limit $Limit
if ($LASTEXITCODE -ne 0) { throw "Parsing failed ($LASTEXITCODE); partial artifacts retained at $Out." }
Write-Output "Amazon clothing/toys Silver format: $Out"
