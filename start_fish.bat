@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
title Fish Speech Server
echo ========================================
echo  Fish Speech Server
echo  Port: 7860
echo ========================================
cd /d C:\Users\USER\Desktop\fish-speech
call venv_fish\Scripts\activate
python fish_server.py
pause
