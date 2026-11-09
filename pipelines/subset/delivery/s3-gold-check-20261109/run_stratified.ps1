param([switch]$PlanOnly)
$ErrorActionPreference = 'Stop'
$workspace = 'C:\Users\eduar\Desktop\HACKATON'
$sources = Get-Content -LiteralPath "$workspace\data\subset-sources.json" -Raw | ConvertFrom-Json
$mounts = @('--mount', "type=bind,source=$workspace,target=/hackaton",
    '--mount', 'type=bind,source=C:\Users\eduar\Desktop\M4M\04_Retail\M4R_REAL\data\5-view-2467,target=/five,readonly')
foreach ($domain in @('food','fragrance')) {
    foreach ($field in @('silver','native_bridge','legacy_bridge')) {
        $sourceFile = (Resolve-Path -LiteralPath $sources.domains.$domain.$field).Path
        $mounts += @('--mount', "type=bind,source=$sourceFile,target=/inputs/$domain-$field.parquet,readonly")
    }
}
$extra = @()
if ($PlanOnly) { $extra += '--plan-only' }
docker run --rm --network none -e PYTHONDONTWRITEBYTECODE=1 @mounts m4r:b030afac47d1 python /hackaton/tasks/s3-gold-check-20261109/make_stratified_subsets.py @extra
if ($LASTEXITCODE -ne 0) { throw "Subset extraction exited $LASTEXITCODE" }
