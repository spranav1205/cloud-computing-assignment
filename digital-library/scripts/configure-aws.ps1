param(
    [Parameter(Mandatory = $true)][string]$ImagesFile,
    [string]$OutputsFile = '',
    [string]$ManifestDirectory = (Join-Path (Split-Path -Parent $PSScriptRoot) 'k8s')
)

# Local file preparation only: no apply, publish, secret creation, or cluster calls.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$images = Get-Content -LiteralPath $ImagesFile -Raw | ConvertFrom-Json
if ($OutputsFile) {
    $outputs = Get-Content -LiteralPath $OutputsFile -Raw | ConvertFrom-Json
} else {
    $outputJson = & terraform "-chdir=$projectRoot/infra" output -json
    if ($LASTEXITCODE -ne 0) { throw 'Terraform outputs are unavailable; wait for the infrastructure apply to finish.' }
    $outputs = $outputJson | ConvertFrom-Json
}
$catalog = $outputs.catalog.value
$notification = $outputs.event_driven_notification.value
$repositories = $outputs.image_repositories.value
$services = @('member', 'catalog', 'reservation', 'notification', 'fine', 'lending', 'availability', 'frontend')
$registry = [regex]::Match([string]$repositories.member, '^([0-9]{12})\.dkr\.ecr\.([a-z0-9-]+)\.amazonaws\.com/')
if (!$registry.Success) { throw 'Missing or invalid image_repositories Terraform output.' }
$account = $registry.Groups[1].Value
$region = $registry.Groups[2].Value
foreach ($role in @($catalog.role_arn, $notification.api_role_arn, $outputs.fluent_bit_role_arn.value)) {
    if (!$role -or $role -notmatch "^arn:aws:iam::${account}:role/" -or $role -match 'REPLACE') {
        throw 'Missing IAM outputs. Apply the notification API role along with the rest of the infrastructure first.'
    }
}
foreach ($value in @($catalog.bucket_name, $catalog.books_table_name, $catalog.copies_table_name, $notification.queue_url)) {
    if (!$value -or $value -match 'replace-with') { throw 'Missing storage or SQS Terraform output.' }
}

function Set-YamlValue {
    param([string]$Content, [string]$Key, [string]$Value)
    $pattern = '(?m)^([ \t]*' + [regex]::Escape($Key) + ':)[^\r\n]*'
    if (![regex]::IsMatch($Content, $pattern)) { throw "Manifest key not found: $Key" }
    $encoded = ConvertTo-Json -InputObject $Value -Compress
    return [regex]::Replace($Content, $pattern, { param($match) $match.Groups[1].Value + ' ' + $encoded })
}

# Validate and stage every replacement before changing any manifest.
$prepared = [ordered]@{}
foreach ($service in $services) {
    $repository = [string]$repositories.$service
    $reference = [string]$images.$service
    if (!$repository.StartsWith($registry.Value) -or $reference -notmatch ('^' + [regex]::Escape($repository) + '@sha256:[a-f0-9]{64}$')) {
        throw "Missing or mismatched published image digest for $service. Use the report from publish-images.ps1."
    }
    $path = Join-Path $ManifestDirectory "$service.yaml"
    $content = Get-Content -LiteralPath $path -Raw
    $prepared[$path] = Set-YamlValue $content 'image' $reference
}
$path = Join-Path $ManifestDirectory 'catalog.yaml'
foreach ($entry in @{
    'eks.amazonaws.com/role-arn' = $catalog.role_arn
    'AWS_REGION' = $region
    'BOOKS_TABLE' = $catalog.books_table_name
    'COPIES_TABLE' = $catalog.copies_table_name
    'COVERS_BUCKET' = $catalog.bucket_name
}.GetEnumerator()) {
    $prepared[$path] = Set-YamlValue $prepared[$path] $entry.Key $entry.Value
}
$path = Join-Path $ManifestDirectory 'notification.yaml'
$prepared[$path] = Set-YamlValue $prepared[$path] 'eks.amazonaws.com/role-arn' $notification.api_role_arn
$prepared[$path] = Set-YamlValue $prepared[$path] 'AWS_REGION' $region
$prepared[$path] = Set-YamlValue $prepared[$path] 'NOTIFICATION_QUEUE_URL' $notification.queue_url
$path = Join-Path $ManifestDirectory 'platform/fluent-bit.yaml'
$content = Get-Content -LiteralPath $path -Raw
$prepared[$path] = Set-YamlValue $content 'eks.amazonaws.com/role-arn' $outputs.fluent_bit_role_arn.value
$prepared[$path] = Set-YamlValue $prepared[$path] 'value' $region

foreach ($path in $prepared.Keys) {
    [System.IO.File]::WriteAllText($path, $prepared[$path], [System.Text.UTF8Encoding]::new($false))
}
Write-Host 'Updated local Kubernetes images and AWS settings. Review the diff, then commit for Argo CD.'
Write-Host 'Database roles/Secrets, rds-ca, Argo CD, and the ALB controller must exist before sync; see DEPLOY.md.'
