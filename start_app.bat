@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
title 星雲大師法語問答系統
echo ========================================
echo  星雲大師法語問答系統
echo  Port: 8080
echo  網址: http://localhost:8080
echo ========================================
cd /d C:\Users\USER\Desktop\project
call venv312\Scripts\activate
python app.py
pause
