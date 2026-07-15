@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python init_sqlite.py
python mcp_server.py
