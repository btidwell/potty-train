# Deploy the site for the IPv4 address this machine is using right now.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$ip = (Invoke-RestMethod "https://checkip.amazonaws.com").Trim()
if (-not $ip) { throw "Could not read the public IP." }
Write-Host "Allowing $ip/32"

Push-Location (Join-Path $root "frontend")
npm ci
npm run build
Pop-Location

Push-Location (Join-Path $root "infra")
python -m pip install -r requirements.txt
npx aws-cdk deploy --require-approval broadening -c "allowedCidrs=$ip/32"
Pop-Location
