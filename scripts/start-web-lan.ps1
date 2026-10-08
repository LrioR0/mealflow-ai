$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $root 'apps\web')

npm run dev -- --host 0.0.0.0
