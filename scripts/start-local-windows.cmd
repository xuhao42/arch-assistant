@echo off
rem Windows CMD 本地启动脚本：打开四个服务窗口，适合不使用 PowerShell 时演示。
setlocal
set "ROOT=%~dp0.."
cd /d "%ROOT%"

rem 确认项目虚拟环境存在，否则服务依赖无法导入。
if not exist "%ROOT%\.venv-win\Scripts\python.exe" (
  echo Missing .venv-win. Run: python -m venv .venv-win
  exit /b 1
)

rem 简单读取 .env，把键值注入当前 cmd 进程，供后续 start 命令继承。
if exist "%ROOT%\.env" (
  for /f "usebackq tokens=1,* delims==" %%A in ("%ROOT%\.env") do (
    if not "%%A"=="" if not "%%A:~0,1%"=="#" set "%%A=%%B"
  )
)

rem 固定本地服务互联地址，确保四个窗口之间通过 127.0.0.1 通信。
set "LLM_ROUTER_HOST=http://127.0.0.1:8002"
set "AGENT_RUNTIME_HOST=http://127.0.0.1:8003"
set "ORCHESTRATION_HOST=http://127.0.0.1:8001"
set "FRONTEND_DIST=%ROOT%\frontend\dist"

rem 分别启动四个微服务窗口：LLM Router、Agent Runtime、编排引擎、API Gateway。
start "arch-llm-router" cmd /k "cd /d "%ROOT%\apps\llm-router" && "%ROOT%\.venv-win\Scripts\python.exe" -m uvicorn llm_router.main:app --host 127.0.0.1 --port 8002"
start "arch-agent-runtime" cmd /k "cd /d "%ROOT%\apps\agent-runtime" && "%ROOT%\.venv-win\Scripts\python.exe" -m uvicorn agent_runtime.main:app --host 127.0.0.1 --port 8003"
start "arch-orchestration" cmd /k "cd /d "%ROOT%\apps\orchestration-engine" && "%ROOT%\.venv-win\Scripts\python.exe" -m uvicorn orchestration_engine.main:app --host 127.0.0.1 --port 8001"
start "arch-api-gateway" cmd /k "cd /d "%ROOT%\apps\api-gateway" && "%ROOT%\.venv-win\Scripts\python.exe" -m uvicorn api_gateway.main:app --host 127.0.0.1 --port 3000"

echo Started local service windows.
echo Open http://127.0.0.1:3000/
