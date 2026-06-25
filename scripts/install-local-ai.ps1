$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$ServerPath = Join-Path $Root 'server.py'
$ConfigPath = Join-Path $Root 'config.json'

Write-Host 'Installing Ollama...'
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    winget install --id Ollama.Ollama -e --accept-package-agreements --accept-source-agreements
}

$ollamaExe = (Get-Command ollama -ErrorAction SilentlyContinue).Source
if (-not $ollamaExe) {
    $candidate = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
    if (Test-Path $candidate) { $ollamaExe = $candidate }
}
if (-not $ollamaExe) { throw 'Ollama was installed but ollama.exe is not available yet. Restart PowerShell and run this script again.' }

Write-Host 'Downloading Qwen3 8B...'
& $ollamaExe pull qwen3:8b

if (-not (Test-Path $ConfigPath)) {
    Copy-Item (Join-Path $Root 'config.example.json') $ConfigPath
}
$config = Get-Content $ConfigPath -Raw | ConvertFrom-Json
$config.ai_provider = 'ollama'
if (-not ($config.PSObject.Properties.Name -contains 'ollama_base_url')) { $config | Add-Member ollama_base_url 'http://127.0.0.1:11434' }
else { $config.ollama_base_url = 'http://127.0.0.1:11434' }
if (-not ($config.PSObject.Properties.Name -contains 'ollama_model')) { $config | Add-Member ollama_model 'qwen3:8b' }
else { $config.ollama_model = 'qwen3:8b' }
if (-not ($config.PSObject.Properties.Name -contains 'ollama_timeout_seconds')) { $config | Add-Member ollama_timeout_seconds 120 }
else { $config.ollama_timeout_seconds = 120 }
$config | ConvertTo-Json -Depth 20 | Set-Content $ConfigPath -Encoding UTF8

$server = Get-Content $ServerPath -Raw
if ($server -notmatch 'from ollama_provider import OllamaProvider') {
    $server = $server.Replace('import screen_capture', "import screen_capture`r`nfrom ollama_provider import OllamaProvider")
}
if ($server -notmatch 'OLLAMA_BASE_URL =') {
    $needle = 'CODEX_TIMEOUT = int(config.get("codex_timeout_seconds", 90))'
    $replacement = @'
CODEX_TIMEOUT = int(config.get("codex_timeout_seconds", 90))
OLLAMA_BASE_URL = config.get("ollama_base_url", "http://127.0.0.1:11434")
OLLAMA_MODEL = config.get("ollama_model", "qwen3:8b")
OLLAMA_TIMEOUT = int(config.get("ollama_timeout_seconds", 120))
'@
    $server = $server.Replace($needle, $replacement.TrimEnd())
}
if ($server -notmatch 'ollama = OllamaProvider') {
    $needle = 'ai = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL) if AI_PROVIDER == "openai" else None'
    $replacement = @'
ai = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL) if AI_PROVIDER == "openai" else None
ollama = OllamaProvider(OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT) if AI_PROVIDER == "ollama" else None
'@
    $server = $server.Replace($needle, $replacement.TrimEnd())
}
$old = @'
async def generate_reply(messages: list, instructions: str, max_output_tokens: int = 400) -> str:
    if AI_PROVIDER == "codex_cli":
        return await generate_reply_with_codex(messages, instructions)

    if not ai:
        raise RuntimeError(f"Unbekannter ai_provider: {AI_PROVIDER}")
'@
$new = @'
async def generate_reply(messages: list, instructions: str, max_output_tokens: int = 400) -> str:
    if AI_PROVIDER == "codex_cli":
        return await generate_reply_with_codex(messages, instructions)

    if AI_PROVIDER == "ollama":
        if not ollama:
            raise RuntimeError("Ollama-Provider ist nicht initialisiert.")
        return await ollama.chat(messages, instructions, max_output_tokens)

    if not ai:
        raise RuntimeError(f"Unbekannter ai_provider: {AI_PROVIDER}")
'@
if ($server.Contains($old)) { $server = $server.Replace($old, $new) }
elseif ($server -notmatch 'AI_PROVIDER == "ollama"') { throw 'Could not patch generate_reply automatically because server.py differs from the expected version.' }
Set-Content $ServerPath $server -Encoding UTF8

Write-Host ''
Write-Host 'Done. XEON now uses qwen3:8b locally through Ollama.'
Write-Host 'Start XEON with: python server.py'
