@echo off
:: 設定編碼為 UTF-8
chcp 65001 >nul
set PYTHONUTF8=1

:: 切換到你的專案目錄
cd /d "C:\Users\USER\Desktop\fish-speech"

:: 啟動虛擬環境 (venv_fish)
call venv_fish\Scripts\activate

:: 保持視窗開啟，讓你可以輸入指令
cmd /k
