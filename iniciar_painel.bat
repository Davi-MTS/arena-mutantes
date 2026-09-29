@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Arena - Mutante vs. Cacador
echo.
echo   Preparando a Arena...
echo.
REM Garante que o Ollama esta rodando (ignora erro se ja estiver)
where ollama >nul 2>nul && (start "" /b ollama serve >nul 2>nul)
REM Pre-carrega o modelo na GPU para a primeira jogada nao demorar
python -c "import ollama; ollama.generate(model='qwen2.5-coder:7b', prompt='', keep_alive='60m')" 2>nul
python painel.py
pause
