<#
    rpcb installer for Windows -- CLI + Claude MCP + Codex MCP + Claude plugin.

      irm https://raw.githubusercontent.com/Raksham-Labs/rpcb-tool/main/install.ps1 | iex
      .\install.ps1                 # from a local clone
      .\install.ps1 -Uninstall

    Idempotent: safe to re-run. Every step reports skip / ok / warn.

    macOS and Linux use install.sh instead.
#>
param(
    [switch]$Uninstall
)

# Checked at runtime, not with #Requires: that directive is unreliable when the
# script arrives through `irm | iex` rather than as a file on disk.
if ($PSVersionTable.PSVersion.Major -lt 5) {
    Write-Host 'rpcb needs PowerShell 5.1 or newer.' -ForegroundColor Red
    exit 1
}

$RepoUrl    = if ($env:RPCB_REPO)   { $env:RPCB_REPO }   else { 'https://github.com/Raksham-Labs/rpcb-tool' }
$Branch     = if ($env:RPCB_BRANCH) { $env:RPCB_BRANCH } else { 'main' }
$InstallDir = if ($env:RPCB_HOME)   { $env:RPCB_HOME }   else { Join-Path $env:LOCALAPPDATA 'rpcb-tool' }

# uv and pipx both shim into here, so the venv fallback matches them.
$BinDir = Join-Path $env:USERPROFILE '.local\bin'

# ASCII markers, not glyphs: legacy conhost code pages mangle Unicode.
function Write-Head($m) { Write-Host ''; Write-Host $m -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host '  [ ok ] ' -ForegroundColor Green    -NoNewline; Write-Host $m }
function Write-Skip($m) { Write-Host '  [skip] '  -ForegroundColor DarkGray -NoNewline; Write-Host $m }
function Write-Warn($m) { Write-Host '  [warn] '  -ForegroundColor Yellow   -NoNewline; Write-Host $m }
function Write-Fail($m) { Write-Host '  [fail] '  -ForegroundColor Red      -NoNewline; Write-Host $m }

function Test-Cmd($name) {
    [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

# Windows PATH edits only reach new processes, so mirror into the live session too.
function Add-UserPath($dir) {
    $current = [Environment]::GetEnvironmentVariable('Path', 'User')
    $parts = @()
    if ($current) { $parts = @($current -split ';' | Where-Object { $_ -ne '' }) }
    if ($parts -contains $dir) { return $false }
    $joined = (@($parts) + @($dir)) -join ';'
    [Environment]::SetEnvironmentVariable('Path', $joined, 'User')
    $env:Path = "$dir;$env:Path"
    return $true
}

$CodexConfig = Join-Path $env:USERPROFILE '.codex\config.toml'

# ------------------------------------------------------------------ uninstall
if ($Uninstall) {
    Write-Head 'Uninstalling rpcb'

    if (Test-Cmd 'uv') {
        & uv tool uninstall rpcb 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { Write-Ok 'removed CLI (uv)' }
    }
    if (Test-Cmd 'pipx') {
        & pipx uninstall rpcb 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { Write-Ok 'removed CLI (pipx)' }
    }
    foreach ($shim in @('rpcb.exe', 'rpcb.cmd')) {
        $p = Join-Path $BinDir $shim
        if (Test-Path $p) { Remove-Item $p -Force; Write-Ok "removed shim $shim" }
    }
    if (Test-Cmd 'claude') {
        & claude mcp remove --scope user rpcb 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { Write-Ok 'removed Claude MCP' }
    }
    if (Test-Path $CodexConfig) {
        $src = Get-Content $CodexConfig -Raw
        # Consume the block line by line, stopping at the next section header.
        # Matching to the next '[' would stop inside `args = ["mcp"]`.
        $rx = '\r?\n*# rpcb \(auto\)\r?\n\[mcp_servers\.rpcb\]\r?\n(?:(?!\[)[^\r\n]*(?:\r?\n|$))*'
        $out = [regex]::Replace($src, $rx, "`n")
        if ($out -ne $src) {
            [System.IO.File]::WriteAllText($CodexConfig, $out, (New-Object System.Text.UTF8Encoding($false)))
            Write-Ok 'removed Codex MCP entry'
        }
    }

    Write-Host ''
    Write-Host "The repo at $InstallDir was left in place. Remove it manually if you want."
    if ($env:KICAD_CLI) {
        Write-Host "KICAD_CLI is still set to $env:KICAD_CLI -- clear it manually if you no longer want it."
    }
    exit 0
}

Write-Host ''
Write-Host 'rpcb installer' -ForegroundColor Cyan

# -------------------------------------------------------------------- 0. deps
Write-Head 'Checking prerequisites'

# uv can provision its own interpreter, so a missing system Python is only fatal
# when uv is absent too.
$Python = $null
$candidates = @(
    @{ Exe = 'py';      Args = @('-3') },
    @{ Exe = 'python3'; Args = @() },
    @{ Exe = 'python';  Args = @() }
)
foreach ($cand in $candidates) {
    $cmd = Get-Command $cand.Exe -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }
    # The Microsoft Store alias stub resolves but only opens the Store.
    if ($cmd.Source -and $cmd.Source -like '*\WindowsApps\*') { continue }
    $probe = @($cand.Args) + @('-c', 'import sys;print("%d.%d"%sys.version_info[:2])')
    $ver = & $cand.Exe @probe 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $ver) { continue }
    try { $parsed = [version]$ver } catch { continue }
    if ($parsed -lt [version]'3.9') { continue }
    $Python = $cand
    Write-Ok "python $ver ($($cand.Exe))"
    break
}
if (-not $Python) {
    if (Test-Cmd 'uv') {
        Write-Warn 'no Python 3.9+ found -- uv will provision one'
    } else {
        Write-Fail 'no Python 3.9+ found. Install from python.org (tick "Add to PATH"), or install uv.'
        exit 1
    }
}

# extract.py probes the default KiCad paths itself, so this only has to cover
# the versions and locations it does not know about -- hence KICAD_CLI.
$kicadCli = $null
if (Test-Cmd 'kicad-cli') {
    Write-Ok 'kicad-cli on PATH'
} else {
    $roots = @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:LOCALAPPDATA) | Where-Object { $_ }
    $found = @()
    foreach ($root in $roots) {
        $found += Get-ChildItem -Path (Join-Path $root 'KiCad\*\bin\kicad-cli.exe') -ErrorAction SilentlyContinue
    }
    if ($found.Count -gt 0) {
        $kicadCli = ($found | Sort-Object -Descending -Property @{ Expression = {
            try { [version]$_.Directory.Parent.Name } catch { [version]'0.0' }
        }} | Select-Object -First 1).FullName
        Write-Ok "kicad-cli found at $kicadCli"
    } else {
        Write-Warn 'kicad-cli not found -- rpcb needs it to resolve netlists.'
        Write-Warn 'Install KiCad, or set KICAD_CLI to its path.'
    }
}

# ------------------------------------------------------------------ 1. source
Write-Head 'Getting the source'
# $PSScriptRoot is empty under `irm | iex`, which is exactly the remote case.
if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot 'pyproject.toml'))) {
    $InstallDir = $PSScriptRoot
    Write-Ok "using local clone at $InstallDir"
} elseif (Test-Path (Join-Path $InstallDir '.git')) {
    & git -C $InstallDir pull --quiet --ff-only 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { Write-Ok "updated $InstallDir" } else { Write-Skip "kept existing $InstallDir" }
} elseif (Test-Path (Join-Path $InstallDir 'pyproject.toml')) {
    Write-Ok "using existing $InstallDir"
} else {
    if (-not (Test-Cmd 'git')) { Write-Fail 'git required to fetch the repo'; exit 1 }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $InstallDir) | Out-Null
    & git clone --quiet --branch $Branch $RepoUrl $InstallDir 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { Write-Ok "cloned to $InstallDir" } else { Write-Fail "clone failed from $RepoUrl"; exit 1 }
}

# --------------------------------------------------------------------- 2. CLI
Write-Head 'Installing the rpcb CLI'
# Editable install: fixes made while reviewing one board are live in every
# other project immediately, with no reinstall step.
if (Test-Cmd 'uv') {
    & uv tool install --force --editable $InstallDir 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Fail 'uv tool install failed'; exit 1 }
    Write-Ok 'installed via uv (editable)'
} elseif (Test-Cmd 'pipx') {
    & pipx install --force --editable $InstallDir 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Fail 'pipx install failed'; exit 1 }
    Write-Ok 'installed via pipx (editable)'
} else {
    # Windows venvs put console scripts in Scripts\, not bin\.
    $venv = Join-Path $InstallDir '.venv'
    $venvArgs = @($Python.Args) + @('-m', 'venv', $venv)
    & $Python.Exe @venvArgs 2>&1 | Out-Null
    $venvPy = Join-Path $venv 'Scripts\python.exe'
    if (-not (Test-Path $venvPy)) { Write-Fail "could not create a venv at $venv"; exit 1 }
    & $venvPy -m pip install --quiet --upgrade pip 2>&1 | Out-Null
    & $venvPy -m pip install --quiet --editable $InstallDir 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Fail 'venv install failed'; exit 1 }

    New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
    # Copy the generated .exe launcher rather than writing a .cmd: Codex spawns
    # the MCP server without a shell, and CreateProcess will not run a .cmd.
    $venvExe = Join-Path $venv 'Scripts\rpcb.exe'
    if (Test-Path $venvExe) {
        Copy-Item $venvExe (Join-Path $BinDir 'rpcb.exe') -Force
        Write-Ok "installed to venv, shim at $BinDir\rpcb.exe"
    } else {
        Write-Fail "venv install produced no rpcb.exe in $venv\Scripts"
        exit 1
    }
}

# PATH sanity -- the plugin and Codex entry both invoke bare `rpcb`.
if (-not (Test-Cmd 'rpcb')) {
    if (Test-Path (Join-Path $BinDir 'rpcb.exe')) {
        if (Add-UserPath $BinDir) { Write-Ok "added $BinDir to your user PATH" }
        else { $env:Path = "$BinDir;$env:Path" }
    }
}
if (Test-Cmd 'rpcb') {
    $v = (& rpcb --version 2>$null) -split '\s+' | Select-Object -Last 1
    Write-Ok "rpcb $v on PATH"
} else {
    Write-Warn "rpcb installed but not on PATH -- add $BinDir to PATH and open a new terminal"
}

# Only pin KICAD_CLI when kicad-cli is off PATH; extract.py reads it first.
if ($kicadCli) {
    if ($env:KICAD_CLI -eq $kicadCli) {
        Write-Skip 'KICAD_CLI already set'
    } else {
        [Environment]::SetEnvironmentVariable('KICAD_CLI', $kicadCli, 'User')
        $env:KICAD_CLI = $kicadCli
        Write-Ok 'set KICAD_CLI for your user'
    }
}

# --------------------------------------------------------------- 3. Claude MCP
Write-Head 'Registering MCP with Claude Code'
if (Test-Cmd 'claude') {
    $existing = & claude mcp list 2>$null
    if ($existing -match '^rpcb') {
        Write-Skip 'already registered'
    } else {
        & claude mcp add --scope user rpcb -- rpcb mcp 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Ok 'registered at user scope (available in every project)'
        } else {
            Write-Warn 'could not register automatically. Run:'
            Write-Warn '  claude mcp add --scope user rpcb -- rpcb mcp'
        }
    }
} else {
    Write-Skip 'claude not found -- skipping'
}

# ---------------------------------------------------------------- 4. Codex MCP
Write-Head 'Registering MCP with Codex'
if (Test-Cmd 'codex') {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $CodexConfig) | Out-Null
    $src = if (Test-Path $CodexConfig) { Get-Content $CodexConfig -Raw } else { '' }
    if ($src -match '\[mcp_servers\.rpcb\]') {
        Write-Skip 'already registered'
    } else {
        $block = "`n# rpcb (auto)`n[mcp_servers.rpcb]`ncommand = `"rpcb`"`nargs = [`"mcp`"]`n"
        # No BOM: it trips some TOML parsers.
        [System.IO.File]::AppendAllText($CodexConfig, $block, (New-Object System.Text.UTF8Encoding($false)))
        Write-Ok "appended [mcp_servers.rpcb] to $CodexConfig"
    }
} else {
    Write-Skip 'codex not found -- skipping'
}

# ------------------------------------------------------------- 5. Claude plugin
Write-Head 'Installing the Claude Code plugin'
if (Test-Cmd 'claude') {
    $markets = & claude plugin marketplace list 2>$null
    if ($markets -match 'rpcb') {
        Write-Skip 'marketplace already added'
    } else {
        & claude plugin marketplace add $InstallDir 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { Write-Ok 'added marketplace' }
        else { Write-Warn "could not add marketplace; run: claude plugin marketplace add $InstallDir" }
    }
    $plugins = & claude plugin list 2>$null
    if ($plugins -match '^rpcb') {
        Write-Skip 'plugin already installed'
    } else {
        & claude plugin install rpcb@rpcb 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { Write-Ok 'installed plugin (/review-schematic + skill)' }
        else { Write-Warn 'could not install plugin; run: claude plugin install rpcb@rpcb' }
    }
} else {
    Write-Skip 'claude not found -- skipping'
}

# ------------------------------------------------------------------ 6. verify
Write-Head 'Verifying'
if (Test-Cmd 'rpcb') {
    $handshake = @(
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05"}}'
        '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
    )
    $reply = $handshake | & rpcb mcp 2>$null
    if ($reply -match 'design_summary') { Write-Ok 'MCP server responds with tools' }
    else { Write-Warn 'MCP server did not respond as expected' }
} else {
    Write-Warn 'skipped (rpcb not on PATH in this shell)'
}

Write-Host ''
Write-Host 'Done.' -ForegroundColor Cyan
Write-Host @'

  cd <any-kicad-project>
  rpcb summary            # overview
  rpcb check              # run design rules
  rpcb pin U2.45          # what a pin connects to
  rpcb review             # launch Claude with the design preloaded
  rpcb review --codex     # same, with Codex

  In Claude Code:  /review-schematic   (or just ask about the board)
  Project rules:   rpcb init  ->  rpcb.yaml

  Restart Claude Code / Codex to pick up the new MCP server.
  Open a new terminal if PATH or KICAD_CLI changed.
'@
Write-Host ''
