@echo off
title Prepare Driving Video Tool
echo ===================================================
echo   [專題自動化] 正在執行 YouTube 驅動影片下載與 FFmpeg 裁切...
echo ===================================================
:: 強制切換到批次檔所在的目錄
cd /d "%~dp0"

:: 自動偵測並掛載虛擬環境
if exist venv\Scripts\activate.bat (
    echo [狀態] 偵測到當前目錄 venv，正在掛載...
    call venv\Scripts\activate.bat
) else if exist ..\LivePortrait-main\venv\Scripts\activate.bat (
    echo [狀態] 偵測到上層 LivePortrait 目錄 venv，正在掛載...
    call ..\LivePortrait-main\venv\Scripts\activate.bat
) else (
    echo [提示] 未找到環境安裝路徑，將嘗試使用系統預設 Python 執行...
)

echo [狀態] 開始執行預處理流程...
python prepare_driving_video.py
echo ===================================================
echo   處理完成！請至 static/avatar/ 確認 master_drive.mp4
echo ===================================================
pause