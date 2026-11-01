@echo off
REM 把本機改好的 pipeline.sh（跟同目錄其他 comic-video 腳本）推到 Spark 的 ~/h3-bench/comic-video/。
REM IP 跟 SSH 使用者沿用本專案既有慣例（見 spark-baseline-2026-10-28.md）。
set DGX_HOST=100.89.149.50
set SSH_USER=funsteam
set REMOTE_DIR=~/h3-bench/comic-video

echo ===================================================
echo  部署 pipeline.sh → %SSH_USER%@%DGX_HOST%:%REMOTE_DIR%
echo ===================================================

scp "%~dp0pipeline.sh" %SSH_USER%@%DGX_HOST%:%REMOTE_DIR%/pipeline.sh
if errorlevel 1 (
    echo [ERROR] scp 失敗，中止。
    pause
    exit /b 1
)

ssh %SSH_USER%@%DGX_HOST% "chmod +x %REMOTE_DIR%/pipeline.sh"
if errorlevel 1 (
    echo [ERROR] chmod 失敗，請手動檢查。
    pause
    exit /b 1
)

echo.
echo 完成。下次在 Spark 上 setsid nohup bash pipeline.sh ^<篇目^> 就是新版。
pause
