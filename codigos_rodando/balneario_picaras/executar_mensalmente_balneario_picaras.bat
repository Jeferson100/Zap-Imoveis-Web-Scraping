@echo off
title Maratona de Dados Balneario Picaras - Ciencia de Dados
cls

echo ======================================================
echo   INICIANDO COLETA MENSAL DE IMOVEIS - BALNEARIO PICARAS
echo ======================================================
echo.

:: 1. Entra na pasta do projeto
cd /d "C:\Users\jefer\Documents\Ciencia-de-dados\Preco-Imoveis\codigos_rodando\balneario_picaras"

:: 2. Ativa o Ambiente Virtual (.venv)
:: Note que recuamos duas pastas (..\..) para chegar na raiz onde esta o .venv
echo [INFO] Ativando ambiente virtual...
call "C:\Users\jefer\Documents\Ciencia-de-dados\Preco-Imoveis\.venv\Scripts\activate.bat"

:: 3. Executa o orquestrador Python
echo [INFO] Rodando scripts de coleta e processamento...
uv run rodando_balneario_picaras.py

:: 4. Sincronizacao com o GitHub
echo.
echo [INFO] Sincronizando resultados com o GitHub...
git add .
git commit -m "Update mensal Balneario Picaras: %date%"
git push origin main

echo.
echo ======================================================
echo   PROCESSO CONCLUIDO COM SUCESSO!
echo ======================================================
pause