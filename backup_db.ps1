$proj = "G:\임시\app\Test20260116\naver_land"   # ← 여기를 명햇님 실제 폴더 경로로 바꾸기
Set-Location $proj

if (!(Test-Path ".\backup")) { New-Item -ItemType Directory -Path ".\backup" | Out-Null }

$ts = Get-Date -Format "yyyyMMdd_HHmm"
Copy-Item ".\naver_land.db" ".\backup\naver_land_$ts.db"
