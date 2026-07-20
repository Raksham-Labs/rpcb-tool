#!/usr/bin/env bash
# rpcb installer — CLI + Claude MCP + Codex MCP + Claude plugin.
#
#   curl -fsSL https://raw.githubusercontent.com/Raksham-Labs/rpcb-tool/main/install.sh | bash
#   ./install.sh                 # from a local clone
#   ./install.sh --uninstall
#
# Idempotent: safe to re-run. Every step reports SKIP / OK / WARN.

set -uo pipefail

REPO_URL="${RPCB_REPO:-https://github.com/Raksham-Labs/rpcb-tool}"
INSTALL_DIR="${RPCB_HOME:-$HOME/.local/share/rpcb-tool}"
BRANCH="${RPCB_BRANCH:-main}"

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
skip() { printf '  \033[90m·\033[0m %s\n' "$1"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; }
err()  { printf '  \033[31m✗\033[0m %s\n' "$1"; }

need_cmd() { command -v "$1" >/dev/null 2>&1; }

# ---------------------------------------------------------------- uninstall
if [ "${1:-}" = "--uninstall" ]; then
  bold "Uninstalling rpcb"
  if need_cmd uv; then uv tool uninstall rpcb >/dev/null 2>&1 && ok "removed CLI (uv)"; fi
  if need_cmd pipx; then pipx uninstall rpcb >/dev/null 2>&1 && ok "removed CLI (pipx)"; fi
  [ -L "$HOME/.local/bin/rpcb" ] && rm -f "$HOME/.local/bin/rpcb" && ok "removed shim"
  if need_cmd claude; then claude mcp remove --scope user rpcb >/dev/null 2>&1 && ok "removed Claude MCP"; fi
  python3 - <<'PY' 2>/dev/null && ok "removed Codex MCP entry"
import os, re
p = os.path.expanduser('~/.codex/config.toml')
if os.path.exists(p):
    s = open(p).read()
    out = re.sub(r'\n*# rpcb \(auto\)\n\[mcp_servers\.rpcb\][^\[]*', '\n', s)
    if out != s:
        open(p, 'w').write(out)
PY
  echo
  echo "The repo at $INSTALL_DIR was left in place. Remove it manually if you want."
  exit 0
fi

echo
bold "rpcb installer"
echo

# ------------------------------------------------------------------ 0. deps
bold "Checking prerequisites"
if ! need_cmd python3; then err "python3 not found — install Python 3.9+ first"; exit 1; fi
ok "python3 $(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')"

if need_cmd kicad-cli; then
  ok "kicad-cli on PATH"
elif [ -x "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli" ]; then
  ok "kicad-cli found (KiCad.app)"
else
  warn "kicad-cli not found — rpcb needs it to resolve netlists."
  warn "Install KiCad, or set KICAD_CLI=/path/to/kicad-cli"
fi

# ------------------------------------------------------------------ 1. source
bold "Getting the source"
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/pyproject.toml" ]; then
  INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
  ok "using local clone at $INSTALL_DIR"
elif [ -d "$INSTALL_DIR/.git" ]; then
  git -C "$INSTALL_DIR" pull --quiet --ff-only 2>/dev/null \
    && ok "updated $INSTALL_DIR" || skip "kept existing $INSTALL_DIR"
elif [ -f "$INSTALL_DIR/pyproject.toml" ]; then
  ok "using existing $INSTALL_DIR"
else
  need_cmd git || { err "git required to fetch the repo"; exit 1; }
  mkdir -p "$(dirname "$INSTALL_DIR")"
  git clone --quiet --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR" \
    && ok "cloned to $INSTALL_DIR" || { err "clone failed from $REPO_URL"; exit 1; }
fi

# ------------------------------------------------------------------ 2. CLI
bold "Installing the rpcb CLI"
# Editable install: fixes made while reviewing one board are live in every
# other project immediately, with no reinstall step.
if need_cmd uv; then
  if uv tool install --force --editable "$INSTALL_DIR" >/dev/null 2>&1; then
    ok "installed via uv (editable)"
  else
    err "uv tool install failed"; exit 1
  fi
elif need_cmd pipx; then
  pipx install --force --editable "$INSTALL_DIR" >/dev/null 2>&1 \
    && ok "installed via pipx (editable)" || { err "pipx install failed"; exit 1; }
else
  VENV="$INSTALL_DIR/.venv"
  python3 -m venv "$VENV" >/dev/null 2>&1
  "$VENV/bin/pip" install --quiet --upgrade pip >/dev/null 2>&1
  "$VENV/bin/pip" install --quiet --editable "$INSTALL_DIR" >/dev/null 2>&1 \
    || { err "venv install failed"; exit 1; }
  mkdir -p "$HOME/.local/bin"
  ln -sf "$VENV/bin/rpcb" "$HOME/.local/bin/rpcb"
  ok "installed to venv, shim at ~/.local/bin/rpcb"
fi

# PATH sanity — the plugin and Codex entry both invoke bare `rpcb`.
if ! need_cmd rpcb; then
  for d in "$HOME/.local/bin" "$HOME/.cargo/bin"; do
    [ -x "$d/rpcb" ] && export PATH="$d:$PATH"
  done
fi
if need_cmd rpcb; then
  ok "rpcb $(rpcb --version 2>/dev/null | awk '{print $2}') on PATH"
else
  warn "rpcb installed but not on PATH — add ~/.local/bin to PATH and re-run"
fi

# ------------------------------------------------------------- 3. Claude MCP
bold "Registering MCP with Claude Code"
if need_cmd claude; then
  if claude mcp list 2>/dev/null | grep -q '^rpcb'; then
    skip "already registered"
  elif claude mcp add --scope user rpcb -- rpcb mcp >/dev/null 2>&1; then
    ok "registered at user scope (available in every project)"
  else
    warn "could not register automatically. Run:"
    warn "  claude mcp add --scope user rpcb -- rpcb mcp"
  fi
else
  skip "claude not found — skipping"
fi

# -------------------------------------------------------------- 4. Codex MCP
bold "Registering MCP with Codex"
if need_cmd codex; then
  python3 - <<'PY'
import os
p = os.path.expanduser('~/.codex/config.toml')
os.makedirs(os.path.dirname(p), exist_ok=True)
src = open(p).read() if os.path.exists(p) else ''
if '[mcp_servers.rpcb]' in src:
    print('  \033[90m·\033[0m already registered')
else:
    block = '\n# rpcb (auto)\n[mcp_servers.rpcb]\ncommand = "rpcb"\nargs = ["mcp"]\n'
    with open(p, 'a') as fh:
        fh.write(block)
    print('  \033[32m✓\033[0m appended [mcp_servers.rpcb] to ~/.codex/config.toml')
PY
else
  skip "codex not found — skipping"
fi

# ----------------------------------------------------------- 5. Claude plugin
bold "Installing the Claude Code plugin"
if need_cmd claude; then
  if claude plugin marketplace list 2>/dev/null | grep -q 'rpcb'; then
    skip "marketplace already added"
  else
    claude plugin marketplace add "$INSTALL_DIR" >/dev/null 2>&1 \
      && ok "added marketplace" \
      || warn "could not add marketplace; run: claude plugin marketplace add $INSTALL_DIR"
  fi
  if claude plugin list 2>/dev/null | grep -q '^rpcb'; then
    skip "plugin already installed"
  else
    claude plugin install rpcb@rpcb >/dev/null 2>&1 \
      && ok "installed plugin (/review-schematic + skill)" \
      || warn "could not install plugin; run: claude plugin install rpcb@rpcb"
  fi
else
  skip "claude not found — skipping"
fi

# ------------------------------------------------------------------ 6. verify
bold "Verifying"
if need_cmd rpcb; then
  if printf '%s\n' \
      '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05"}}' \
      '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
      | rpcb mcp 2>/dev/null | grep -q design_summary; then
    ok "MCP server responds with tools"
  else
    warn "MCP server did not respond as expected"
  fi
else
  warn "skipped (rpcb not on PATH in this shell)"
fi

echo
bold "Done."
cat <<'EOF'

  cd <any-kicad-project>
  rpcb summary            # overview
  rpcb check              # run design rules
  rpcb pin U2.45          # what a pin connects to
  rpcb review             # launch Claude with the design preloaded
  rpcb review --codex     # same, with Codex

  In Claude Code:  /review-schematic   (or just ask about the board)
  Project rules:   rpcb init  ->  rpcb.yaml

  Restart Claude Code / Codex to pick up the new MCP server.
EOF
echo
