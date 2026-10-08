$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
  throw "找不到虚拟环境 Python: $python"
}

$env:PYTHONPATH = Join-Path $root 'apps\api'
Push-Location (Join-Path $root 'apps\api')
try {
  # alembic.ini 的相对路径以 apps/api 为基准，但数据库仍使用仓库根目录 data/local。
  $env:DATABASE_URL = 'sqlite:///../../data/local/mealflow.sqlite3'
  & $python -m alembic upgrade head
  if ($LASTEXITCODE -ne 0) { throw "数据库迁移失败；API 未启动。请先处理上方迁移错误。" }
} finally {
  Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
  Pop-Location
}
& $python -m uvicorn app.main:app --reload --app-dir (Join-Path $root 'apps\api') --host 0.0.0.0 --port 8000
