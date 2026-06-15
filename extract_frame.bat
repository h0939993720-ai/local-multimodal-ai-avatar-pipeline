@echo off
chcp 437 >nul
title Extract Source Frame

echo ========================================
echo  Extract Source Frame Tool
echo ========================================
echo.
echo [1] Extract (default time)
echo [2] Preview multiple frames
echo [3] Extract at specific time
echo.
set /p choice=Enter option (1, 2 or 3): 

cd /d C:\Users\USER\Desktop\project
call venv312\Scripts\activate

if "%choice%"=="2" (
    echo.
    echo Extracting preview frames...
    python extract_source_frame.py --preview
    echo.
    explorer C:\Users\USER\Desktop\project\static\avatar\preview_frames
    echo.
    echo After choosing a frame, update EXTRACT_TIME in extract_source_frame.py
    echo Then run this bat again and choose [1]
    goto end
)

if "%choice%"=="3" (
    echo.
    set /p timecode=Enter time (e.g. 00:00:20): 
    echo.
    echo Extracting frame at %timecode%...
    ffmpeg -y -ss %timecode% ^
        -i "C:\Users\USER\Desktop\project\static\avatar\master_drive.mp4" ^
        -frames:v 1 -q:v 1 -vf "scale=512:309" ^
        "C:\Users\USER\Desktop\project\static\avatar\master.jpg"
    if %errorlevel%==0 (
        echo Done: master.jpg updated
    ) else (
        echo Failed. Check if master_drive.mp4 exists.
    )
    goto end
)

echo.
echo Extracting at default time...
python extract_source_frame.py

:end
echo.
pause