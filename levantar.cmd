@echo off
REM Doble clic para levantar todo (API, worker de ingesta y panel).
REM Llama al script de PowerShell saltandose la politica de ejecucion, que en Windows viene
REM restringida por defecto y haria fallar el arranque con un error que no explica nada.
title Contratacion publica - levantando
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0levantar.ps1" %*
echo.
pause
