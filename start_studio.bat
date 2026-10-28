@echo off
title MiniMax H3 Colab Studio
echo ============================================================
echo Starting MiniMax H3 Colab Studio...
echo ============================================================
cd /d "%~dp0"
if not defined H3_LLM_BASE_URL set H3_LLM_BASE_URL=http://100.89.149.50:8002/v1
python app.py
pause
