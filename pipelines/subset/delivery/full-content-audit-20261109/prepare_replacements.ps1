$ErrorActionPreference='Stop'
$workspace='C:\Users\eduar\Desktop\HACKATON'
$sources=Get-Content -LiteralPath "$workspace\data\subset-sources.json" -Raw | ConvertFrom-Json
$raw='G:\.shortcut-targets-by-id\1lo5XQFqwWZ4oV915bOgMLt9KPW0IeTv4\Hackathon-Kavak-OpenAI-Primero\DATA\Listings\RAW'
$localSelection=Join-Path $workspace 'tasks\raw-content-audit\current-selection'
foreach($domain in @('food','fragrance')) {
 foreach($number in 1..3) {
  $dest=Join-Path $localSelection "$domain\subset-$number"
  New-Item -ItemType Directory -Path $dest -Force | Out-Null
  Copy-Item -LiteralPath (Join-Path $raw "$domain\subset-$number\selection.parquet") -Destination (Join-Path $dest 'selection.parquet')
 }
}
$mounts=@('--mount',"type=bind,source=$workspace,target=/hackaton,readonly",
          '--mount',"type=bind,source=$workspace\tasks\raw-content-audit,target=/audit-output",
          '--mount',"type=bind,source=$localSelection,target=/current-raw,readonly")
foreach($domain in @('food','fragrance')) {
 foreach($field in @('silver','native_bridge','legacy_bridge')) {
  $path=(Resolve-Path -LiteralPath $sources.domains.$domain.$field).Path
  $mounts+=@('--mount',"type=bind,source=$path,target=/inputs/$domain-$field.parquet,readonly")
 }
}
docker run --rm --network none -e PYTHONDONTWRITEBYTECODE=1 @mounts m4r:b030afac47d1 python /hackaton/tasks/raw-content-audit/prepare_replacements.py
if($LASTEXITCODE -ne 0){throw "Candidate preparation failed ($LASTEXITCODE)"}
