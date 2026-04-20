@echo off
title Maratona de Dados Blumenau - Ciencia de Dados
cls

echo ======================================================
echo   INICIANDO COLETA MENSAL DE IMOVEIS - BLUMENAU
echo ======================================================
echo.

:: 1. Entra na pasta do projeto
cd /d "C:\Users\jefer\Documents\Ciencia-de-dados\Preco-Imoveis\codigos_rodando\blumenau"

:: 2. Ativa o Ambiente Virtual (.venv)
:: Note que recuamos duas pastas (..\..) para chegar na raiz onde esta o .venv
echo [INFO] Ativando ambiente virtual...
call "C:\Users\jefer\Documents\Ciencia-de-dados\Preco-Imoveis\.venv\Scripts\activate.bat"

:: 3. Executa o orquestrador Python
echo [INFO] Rodando scripts de coleta e processamento...
uv run rodando_blumenau.py

:: 4. Sincronizacao com o GitHub
echo.
echo [INFO] Sincronizando resultados com o GitHub...
git add .
git commit -m "Update mensal Blumenau: %date%"
git push origin main

echo.
echo ======================================================
echo   PROCESSO CONCLUIDO COM SUCESSO!
echo ======================================================
pause