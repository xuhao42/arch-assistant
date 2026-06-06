param(
    # Root 指向项目根目录，默认根据脚本所在目录向上一级推导。
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    # Prompt 是验收演示使用的典型需求，可在命令行覆盖。
    [string]$Prompt = "开发银行核心交易系统，需要处理转账、存款、贷款等业务，对数据一致性和审计追踪有极高要求，支持日均百万笔交易。",
    # SessionId 使用 smoke_ 前缀，避免 Agent Runtime 把验收请求写入历史学习案例库。
    [string]$SessionId = ("smoke_acceptance_demo_" + [guid]::NewGuid().ToString("N")),
    # ForceBuild 会强制重新构建前端；默认仅在 dist/index.html 缺失时构建。
    [switch]$ForceBuild,
    # KeepServices 会保留本脚本启动的四个服务，便于现场继续打开浏览器演示。
    [switch]$KeepServices,
    # RunBatch 会在冒烟通过后运行 python run_tests.py；耗时较长，默认关闭。
    [switch]$RunBatch
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Import-DotEnv {
    <#
    读取项目 .env 并注入当前进程，供四个临时 uvicorn 服务继承。
    这里保持简单解析，适配 KEY=VALUE 形式；空行和注释行会被跳过。
    #>
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "缺少 .env 文件：$Path"
    }
    Get-Content -LiteralPath $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            return
        }
        $name, $value = $line.Split("=", 2)
        $name = $name.Trim()
        $value = $value.Trim().Trim('"').Trim("'")
        if ($name) {
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

function Test-PortBusy {
    param([int[]]$Ports)
    Get-NetTCPConnection -LocalPort $Ports -ErrorAction SilentlyContinue |
        Where-Object { $_.State -eq "Listen" -or $_.State -eq "Established" } |
        Select-Object LocalPort, State, OwningProcess
}

function Wait-Health {
    <#
    轮询一个服务的 /health，直到返回成功或超时。
    返回健康检查响应体，便于最终汇总展示。
    #>
    param(
        [string]$Name,
        [int]$Port,
        [int]$Retries = 30
    )
    for ($i = 0; $i -lt $Retries; $i++) {
        try {
            $body = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 3
            return [PSCustomObject]@{
                Name = $Name
                Port = $Port
                Healthy = $true
                Body = $body
            }
        } catch {
            Start-Sleep -Milliseconds 700
        }
    }
    return [PSCustomObject]@{
        Name = $Name
        Port = $Port
        Healthy = $false
        Body = $null
    }
}

function Start-AcceptanceService {
    <#
    启动一个验收用微服务进程，stdout/stderr 写入 logs/acceptance。
    返回进程信息，脚本结束时可按 PID 精确清理本次启动的服务。
    #>
    param(
        [string]$Name,
        [string]$WorkingDirectory,
        [int]$Port,
        [string]$Module,
        [string]$Python,
        [string]$LogDir
    )

    $outLogPath = Join-Path $LogDir "$Name.out.log"
    $errLogPath = Join-Path $LogDir "$Name.err.log"
    $process = Start-Process -FilePath $Python `
        -ArgumentList "-m", "uvicorn", $Module, "--host", "127.0.0.1", "--port", "$Port" `
        -WorkingDirectory $WorkingDirectory `
        -RedirectStandardOutput $outLogPath `
        -RedirectStandardError $errLogPath `
        -WindowStyle Hidden `
        -PassThru

    [PSCustomObject]@{
        Name = $Name
        Port = $Port
        Pid  = $process.Id
        Out  = $outLogPath
        Err  = $errLogPath
    }
}

function Invoke-JsonPostUtf8 {
    <#
    Windows PowerShell 5.1 对未显式 charset 的 JSON 响应可能按系统编码解码。
    这里直接读取响应原始字节并按 UTF-8 转成文本，确保中文候选架构名不乱码。
    #>
    param(
        [string]$Uri,
        [string]$Body,
        [int]$TimeoutSec = 180
    )
    $response = Invoke-WebRequest `
        -Uri $Uri `
        -Method Post `
        -Body $Body `
        -ContentType "application/json; charset=utf-8" `
        -TimeoutSec $TimeoutSec
    $stream = $response.RawContentStream
    if ($stream.CanSeek) {
        $stream.Position = 0
    }
    $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8)
    $jsonText = $reader.ReadToEnd()
    return $jsonText | ConvertFrom-Json
}

$Root = (Resolve-Path $Root).Path
$python = Join-Path $Root ".venv-win\Scripts\python.exe"
$frontendIndex = Join-Path $Root "frontend\dist\index.html"
$logDir = Join-Path $Root "logs\acceptance"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resultPath = Join-Path $logDir "acceptance-result-$timestamp.json"

$services = @(
    @{ Name = "llm-router"; WorkingDirectory = (Join-Path $Root "apps\llm-router"); Port = 8002; Module = "llm_router.main:app" },
    @{ Name = "agent-runtime"; WorkingDirectory = (Join-Path $Root "apps\agent-runtime"); Port = 8003; Module = "agent_runtime.main:app" },
    @{ Name = "orchestration-engine"; WorkingDirectory = (Join-Path $Root "apps\orchestration-engine"); Port = 8001; Module = "orchestration_engine.main:app" },
    @{ Name = "api-gateway"; WorkingDirectory = (Join-Path $Root "apps\api-gateway"); Port = 3000; Module = "api_gateway.main:app" }
)

$started = @()
$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()

try {
    Write-Step "1/7 前置检查"
    if (-not (Test-Path -LiteralPath $python)) {
        throw "缺少 Windows 虚拟环境：$python，请先运行 python -m venv .venv-win 并安装依赖。"
    }
    Import-DotEnv -Path (Join-Path $Root ".env")
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    Write-Host "虚拟环境：$python"
    Write-Host "日志目录：$logDir"

    Write-Step "2/7 前端构建检查"
    if ($ForceBuild -or -not (Test-Path -LiteralPath $frontendIndex)) {
        Write-Host "开始构建 frontend/dist ..."
        Push-Location (Join-Path $Root "frontend")
        try {
            npm run build
        } finally {
            Pop-Location
        }
    } else {
        Write-Host "已存在：$frontendIndex"
    }

    Write-Step "3/7 端口检查与服务启动"
    $ports = $services | ForEach-Object { $_.Port }
    $busy = @(Test-PortBusy -Ports $ports)
    if ($busy.Count -gt 0) {
        $busyText = $busy | Format-Table -AutoSize | Out-String
        throw "验收端口已被占用，请先停止旧服务后重试：`n$busyText"
    }

    $env:LLM_ROUTER_HOST = "http://127.0.0.1:8002"
    $env:AGENT_RUNTIME_HOST = "http://127.0.0.1:8003"
    $env:ORCHESTRATION_HOST = "http://127.0.0.1:8001"
    $env:FRONTEND_DIST = Join-Path $Root "frontend\dist"

    foreach ($service in $services) {
        $proc = Start-AcceptanceService @service -Python $python -LogDir $logDir
        $started += $proc
        Write-Host ("启动 {0} :{1} PID={2}" -f $proc.Name, $proc.Port, $proc.Pid)
        Start-Sleep -Milliseconds 800
    }

    Write-Step "4/7 健康检查"
    $health = @()
    foreach ($service in $services) {
        $item = Wait-Health -Name $service.Name -Port $service.Port
        $health += $item
        if (-not $item.Healthy) {
            throw "$($service.Name) 健康检查失败，请查看日志：$(Join-Path $logDir ($service.Name + '.err.log'))"
        }
        Write-Host ("{0}:{1} healthy" -f $item.Name, $item.Port)
    }

    Write-Step "5/7 首页访问检查"
    $homeResponse = Invoke-WebRequest -Uri "http://127.0.0.1:3000/" -TimeoutSec 10
    $title = ""
    if ($homeResponse.Content -match '<title>(.*?)</title>') {
        $title = $Matches[1]
    }
    Write-Host "首页状态：$($homeResponse.StatusCode)"
    Write-Host "页面标题：$title"

    Write-Step "6/7 API 冒烟分析"
    $payload = @{
        prompt = $Prompt
        session_id = $SessionId
    } | ConvertTo-Json -Compress
    $analysis = Invoke-JsonPostUtf8 `
        -Uri "http://127.0.0.1:3000/api/v1/analyze" `
        -Body $payload `
        -TimeoutSec 180

    $candidateCount = @($analysis.candidates).Count
    $topCandidate = if ($candidateCount -gt 0) { $analysis.candidates[0].name } else { "" }
    if ($candidateCount -lt 1 -or -not $analysis.report -or -not $analysis.topology) {
        throw "API 冒烟结果不完整：candidateCount=$candidateCount, hasReport=$([bool]$analysis.report), hasTopology=$([bool]$analysis.topology)"
    }
    Write-Host "候选架构数：$candidateCount"
    Write-Host "首选架构：$topCandidate"
    Write-Host "包含报告：$([bool]$analysis.report)"
    Write-Host "包含拓扑：$([bool]$analysis.topology)"

    $batchSummary = $null
    if ($RunBatch) {
        Write-Step "7/7 批量测试"
        Push-Location $Root
        try {
            & $python run_tests.py
            $batchResultPath = Join-Path $Root "test_results.json"
            if (Test-Path -LiteralPath $batchResultPath) {
                $batchSummary = Get-Content -LiteralPath $batchResultPath -Encoding utf8 | ConvertFrom-Json
            }
        } finally {
            Pop-Location
        }
    } else {
        Write-Step "7/7 跳过批量测试"
        Write-Host "如需完整批量验收，请重新运行并追加 -RunBatch。"
    }

    $stopwatch.Stop()
    $summary = [PSCustomObject]@{
        ok = $true
        elapsedSeconds = [math]::Round($stopwatch.Elapsed.TotalSeconds, 1)
        root = $Root
        url = "http://127.0.0.1:3000/"
        sessionId = $SessionId
        home = [PSCustomObject]@{
            status = $homeResponse.StatusCode
            title = $title
        }
        health = $health
        analysis = [PSCustomObject]@{
            candidateCount = $candidateCount
            topCandidate = $topCandidate
            cached = $analysis.cached
            hasReport = [bool]$analysis.report
            hasTopology = [bool]$analysis.topology
        }
        runBatch = [bool]$RunBatch
        batchSummary = $batchSummary
        services = $started
        logs = $logDir
    }
    $summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $resultPath -Encoding utf8

    Write-Host ""
    Write-Host "验收冒烟通过。" -ForegroundColor Green
    Write-Host "结果文件：$resultPath"
    Write-Host "总耗时：$($summary.elapsedSeconds) 秒"
    if ($KeepServices) {
        Write-Host "服务已保留，可打开 http://127.0.0.1:3000/ 继续展示。"
    }
} finally {
    if (-not $KeepServices) {
        foreach ($item in $started) {
            try {
                Stop-Process -Id $item.Pid -Force -ErrorAction SilentlyContinue
            } catch {
                Write-Warning "停止 $($item.Name) 失败：$($_.Exception.Message)"
            }
        }
    }
}



