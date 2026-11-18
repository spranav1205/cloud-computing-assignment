param(
    [string]$Profile = 'default',
    [string]$Tag = ''
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$services = @('member', 'catalog', 'reservation', 'notification', 'fine', 'lending', 'availability', 'frontend')

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed with exit code $LASTEXITCODE" }
}

Push-Location $projectRoot
$previousProfile = $env:AWS_PROFILE
try {
    $env:AWS_PROFILE = $Profile
    $identity = (Invoke-Checked -Program aws -Arguments @('sts', 'get-caller-identity', '--output', 'json', '--no-cli-pager')) | ConvertFrom-Json
    if ($identity.Arn.EndsWith(':root')) { throw 'Use an IAM user or role, not the root account.' }
    $repositories = (Invoke-Checked -Program terraform -Arguments @('-chdir=infra', 'output', '-json', 'image_repositories')) | ConvertFrom-Json
    foreach ($service in $services) {
        $repository = $repositories.$service
        if (!$repository -or $repository -notmatch '^([0-9]{12})\.dkr\.ecr\.([a-z0-9-]+)\.amazonaws\.com/') {
            throw "Missing ECR output for $service. Apply the reviewed Terraform configuration first."
        }
        if ($Matches[1] -ne $identity.Account) { throw 'ECR outputs belong to another AWS account.' }
        if ($service -eq 'member') {
            $registry = $repository.Split('/')[0]
            $region = $Matches[2]
        }
        if ($repository.Split('/')[0] -ne $registry) { throw 'All images must use the same account and region.' }
    }
    $dockerOS = Invoke-Checked -Program docker -Arguments @('info', '--format', '{{.OSType}}')
    if ($dockerOS -ne 'linux') { throw 'Start Docker Desktop with Linux containers.' }
    if (!$Tag) {
        $revision = Invoke-Checked -Program git -Arguments @('rev-parse', '--short=12', 'HEAD')
        $Tag = "$revision-$([DateTime]::UtcNow.ToString('yyyyMMddHHmmss'))"
    }
    if ($Tag -notmatch '^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$') { throw 'Invalid Docker image tag.' }
    $password = Invoke-Checked -Program aws -Arguments @('ecr', 'get-login-password', '--region', $region, '--no-cli-pager')
    $password | & docker login --username AWS --password-stdin $registry
    if ($LASTEXITCODE -ne 0) { throw 'ECR login failed.' }
    $password = $null

    $published = [ordered]@{}
    $reportDir = Join-Path $projectRoot '.local'
    New-Item -ItemType Directory -Force -Path $reportDir | Out-Null
    $report = Join-Path $reportDir "images-$Tag.json"
    foreach ($service in $services) {
        $context = if ($service -eq 'frontend') { 'frontend' } else { "services/$service" }
        $repository = $repositories.$service
        $image = "${repository}:$Tag"
        Invoke-Checked -Program docker -Arguments @('build', '--platform', 'linux/amd64', '-t', $image, $context)
        Invoke-Checked -Program docker -Arguments @('push', $image)
        $name = $repository.Substring($registry.Length + 1)
        $digest = Invoke-Checked -Program aws -Arguments @('ecr', 'describe-images', '--repository-name', $name, '--image-ids', "imageTag=$Tag", '--region', $region, '--query', 'imageDetails[0].imageDigest', '--output', 'text', '--no-cli-pager')
        if ($digest -notmatch '^sha256:[a-f0-9]{64}$') { throw "Invalid image digest returned for $service" }
        $published[$service] = "${repository}@$digest"
        [System.IO.File]::WriteAllText($report, ($published | ConvertTo-Json), [System.Text.UTF8Encoding]::new($false))
        Write-Host "Published $service -> $($published[$service])"
    }
    Write-Host "Image references saved to $report"
    Write-Host 'Update the Kubernetes image references in Git; Argo CD performs the deployment.'
}
finally {
    $env:AWS_PROFILE = $previousProfile
    Pop-Location
}
