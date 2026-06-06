@echo off
rem Windows CMD 包装入口：调用 PowerShell 验收冒烟脚本。
setlocal
set "ROOT=%~dp0.."
powershell -ExecutionPolicy Bypass -File "%ROOT%\scripts\acceptance-demo-windows.ps1" %*
