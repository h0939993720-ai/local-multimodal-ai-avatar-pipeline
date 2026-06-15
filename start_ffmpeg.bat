@echo off
title FFmpeg Server
 
echo ========================================
echo  FFmpeg Server - Port 7862
echo ========================================
 
cd /d C:\Users\USER\Desktop\project
 
:: Use system Python explicitly (not venv) to avoid FFmpeg 4.2 conflict
C:\Users\USER\AppData\Local\Programs\Python\Python312\python.exe ffmpeg_server.py
 
pause
 