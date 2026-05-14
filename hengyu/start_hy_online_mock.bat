@echo off
cd /d "%~dp0HY_Online"
call conda activate ftapi
python start.py
pause