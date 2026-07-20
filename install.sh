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

# ------------------------------------------------------------------- windows
# Git Bash / MSYS2 / Cygwin: Windows venvs use Scripts\ not bin/, `python3` is
# usually the Store stub, and ~/.local/bin is not on the Windows PATH. WSL
# reports Linux and falls through to the normal path, as it should.
case "$(uname -s 2>/dev/null)" in
  MINGW*|MSYS*|CYGWIN*)
    err "this is a Windows shell -- use install.ps1 instead:"
    err "  irm https://raw.githubusercontent.com/Raksham-Labs/rpcb-tool/main/install.ps1 | iex"
    exit 1
    ;;
esac

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
# Consume the block line by line, stopping at the next section header. Matching
# to the next '[' would stop inside `args = ["mcp"]` and orphan that fragment.
RX = r'\r?\n*# rpcb \(auto\)\r?\n\[mcp_servers\.rpcb\]\r?\n(?:(?!\[)[^\r\n]*(?:\r?\n|$))*'
if os.path.exists(p):
    s = open(p).read()
    out = re.sub(RX, '\n', s)
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
# Checked for CORRECTNESS, not presence. An entry left over from an older
# install points at whatever that install used; "already registered" would
# report success while the wrong thing stayed wired up.
if need_cmd claude; then
  mcp_line="$(claude mcp list 2>/dev/null | grep '^rpcb:' || true)"
  if [ -z "$mcp_line" ]; then
    if claude mcp add --scope user rpcb -- rpcb mcp >/dev/null 2>&1; then
      ok "registered at user scope (available in every project)"
    else
      warn "could not register automatically. Run:"
      warn "  claude mcp add --scope user rpcb -- rpcb mcp"
    fi
  elif printf '%s' "$mcp_line" | grep -q 'rpcb mcp'; then
    skip "already registered correctly"
  else
    claude mcp remove --scope user rpcb >/dev/null 2>&1
    if claude mcp add --scope user rpcb -- rpcb mcp >/dev/null 2>&1; then
      ok "re-registered (previous entry did not invoke \`rpcb mcp\`)"
    else
      warn "could not re-register. Run:"
      warn "  claude mcp remove --scope user rpcb && claude mcp add --scope user rpcb -- rpcb mcp"
    fi
  fi
else
  skip "claude not found — skipping"
fi

# -------------------------------------------------------------- 4. Codex MCP
bold "Registering MCP with Codex"
if need_cmd codex; then
  python3 - <<'PY'
import os, re

OK, SKIP, WARN = '\033[32m✓\033[0m', '\033[90m·\033[0m', '\033[33m!\033[0m'
BODY = '# rpcb (auto)\n[mcp_servers.rpcb]\ncommand = "rpcb"\nargs = ["mcp"]\n'
# Matches only what this installer wrote. Consumes line by line to the next
# section header -- stopping at the first '[' would land inside args = ["mcp"].
RX = r'\r?\n*# rpcb \(auto\)\r?\n\[mcp_servers\.rpcb\]\r?\n(?:(?!\[)[^\r\n]*(?:\r?\n|$))*'


def canonical(base):
    """The one form this installer ever writes, so a re-run settles at once."""
    base = base.rstrip()
    return base + '\n\n' + BODY if base else BODY


p = os.path.expanduser('~/.codex/config.toml')
os.makedirs(os.path.dirname(p), exist_ok=True)
src = open(p).read() if os.path.exists(p) else ''

if re.search(RX, src):
    # Rewrite rather than skip: an entry from an older install may name a
    # different command, and skipping would report success over a stale one.
    # Compared against what the write would produce, so a correct file is left
    # untouched rather than rewritten on every run.
    want = canonical(re.sub(RX, '\n', src))
    if want == src:
        print(f'  {SKIP} already registered correctly')
    else:
        open(p, 'w').write(want)
        print(f'  {OK} refreshed [mcp_servers.rpcb] in ~/.codex/config.toml')
elif '[mcp_servers.rpcb]' in src:
    # Present but not ours -- hand-written or from another tool. Leave it.
    print(f'  {WARN} [mcp_servers.rpcb] exists but was not written by this')
    print(f'  {WARN} installer; left untouched. Check it runs: rpcb mcp')
else:
    open(p, 'w').write(canonical(src))
    print(f'  {OK} added [mcp_servers.rpcb] to ~/.codex/config.toml')
PY
else
  skip "codex not found — skipping"
fi

# ----------------------------------------------------------- 5. Claude plugin
bold "Installing the Claude Code plugin"
# The marketplace is checked by PATH, not by name. A plain name check is why a
# second install from a different directory used to leave the plugin serving
# prompts from the first one while the CLI ran the second -- the two surfaces
# silently disagreeing about which checkout is live.
registered_marketplace() {
  claude plugin marketplace list --json 2>/dev/null | python3 -c '
import json, sys
try:
    rows = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for m in rows if isinstance(rows, list) else []:
    if m.get("name") == "rpcb":
        print(m.get("path") or m.get("installLocation") or "")
        break
' 2>/dev/null
}

if need_cmd claude; then
  want="$(cd "$INSTALL_DIR" && pwd -P)"
  have="$(registered_marketplace)"
  [ -n "$have" ] && [ -d "$have" ] && have="$(cd "$have" && pwd -P)"

  if [ -z "$have" ]; then
    if claude plugin marketplace list 2>/dev/null | grep -q 'rpcb'; then
      # Registered, but this claude cannot report the path (older --json).
      claude plugin marketplace update rpcb >/dev/null 2>&1 \
        && ok "refreshed marketplace" || skip "marketplace present"
      warn "could not verify it points at $want — check with:"
      warn "  claude plugin marketplace list"
    else
      claude plugin marketplace add "$INSTALL_DIR" >/dev/null 2>&1 \
        && ok "added marketplace -> $want" \
        || warn "could not add marketplace; run: claude plugin marketplace add $INSTALL_DIR"
    fi
  elif [ "$have" = "$want" ]; then
    claude plugin marketplace update rpcb >/dev/null 2>&1 \
      && ok "marketplace up to date -> $want" \
      || skip "marketplace points at $want"
  else
    claude plugin marketplace remove rpcb >/dev/null 2>&1
    if claude plugin marketplace add "$INSTALL_DIR" >/dev/null 2>&1; then
      ok "re-pointed marketplace: $have -> $want"
    else
      err "could not re-point marketplace from $have to $want"
      warn "  claude plugin marketplace remove rpcb"
      warn "  claude plugin marketplace add $INSTALL_DIR"
    fi
  fi

  if claude plugin list 2>/dev/null | grep -q '^[^a-zA-Z0-9]*rpcb@'; then
    claude plugin update rpcb@rpcb >/dev/null 2>&1 \
      && ok "plugin updated (restart to apply)" \
      || skip "plugin installed"
  else
    claude plugin install rpcb@rpcb >/dev/null 2>&1 \
      && ok "installed plugin (/review-schematic, /rpcb-init-rules + skill)" \
      || warn "could not install plugin; run: claude plugin install rpcb@rpcb"
  fi
else
  skip "claude not found — skipping"
fi

# ------------------------------------------------------------------ 6. verify
bold "Verifying"
if need_cmd rpcb; then
  tools="$(printf '%s\n' \
      '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05"}}' \
      '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
      | rpcb mcp 2>/dev/null || true)"
  # Check a tool from THIS version, not just any tool: an old binary still on
  # PATH answers design_summary perfectly well and would pass a laxer check.
  if printf '%s' "$tools" | grep -q design_requirements; then
    ok "MCP server responds with this version's tools"
  elif printf '%s' "$tools" | grep -q design_summary; then
    err "an OLDER rpcb is answering on PATH — $(command -v rpcb)"
    warn "its MCP tools predate this install. Open a new shell and re-run,"
    warn "or check for another rpcb earlier in PATH."
  else
    warn "MCP server did not respond as expected"
  fi
  ok "rpcb $(rpcb --version 2>/dev/null | awk '{print $2}') at $(command -v rpcb)"
else
  warn "skipped (rpcb not on PATH in this shell)"
fi

echo
bold "Done."
cat <<'EOF'

  cd <any-kicad-project>
  rpcb summary            # overview
  rpcb check              # run design rules
  rpcb datasheets         # documents a review needs before it can verify limits
  rpcb requirements       # plain-English requirements a reviewer must answer
  rpcb pin U2.45          # what a pin connects to
  rpcb review             # launch Claude with the design preloaded
  rpcb review --codex     # same, with Codex

  In Claude Code:  /review-schematic  ·  /rpcb-init-rules
  Project rules:   rpcb init          ->  rpcb.yaml  (blank scaffold)
                   rpcb init --agent  ->  an agent writes rules for this board

  RESTART Claude Code / Codex. The MCP tool list and the plugin's prompts are
  read at startup, so a running session keeps serving the previous version.
EOF
echo
