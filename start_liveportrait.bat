@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
title LivePortrait Server
echo ========================================
echo  LivePortrait Server
echo  Port: 7861
echo ========================================
cd /d C:\Users\USER\Desktop\LivePortrait-main
call venv\Scripts\activate
cd /d C:\Users\USER\Desktop\project
python liveportrait_server.py
pause
