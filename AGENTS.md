# AGENTS.md

Instructions for AI agents working on this repo. Read before making changes.

## What this project is

`rpcb` turns a KiCad schematic into something an LLM can reason about reliably.

A `.kicad_sch` file is ~60% rendering data, and its connectivity is *implicit in
floating-point pin coordinates* — a wire connects to a pin only when two numbers
happen to be equal. Feeding that to a model produces confident, wrong answers
about what is wired to what. `rpcb` produces a resolved netlist model instead:
~100k tokens of schematic becomes ~6k tokens of design.

It ships three front ends over one implementation:

| Surface | Entry point |
|---|---|
| CLI | `rpcb summary`, `rpcb check`, `rpcb pin U2.45`, … |
| MCP server | `rpcb mcp` — registered with both Claude Code and Codex |
| Agent launcher | `rpcb review [--codex]` |

## Two invariants

**1. KiCad owns connectivity.** Never re-derive nets from pin geometry.
A hand-rolled resolver was built once and matched KiCad exactly (75/75 nets) —
but only after a bug where the wrong rotation direction silently swapped pins
1↔2 on every 270°-rotated part, reversing four protection diodes. Every pin
still landed on a wire, so it looked correct while being wrong. Connectivity
comes from `kicad-cli sch export netlist`; the schematic is parsed only for what
the netlist drops (text notes, `dnp`, `in_bom`).

**2. Facts and judgement stay separate.** `extract.py` emits only what is
mechanically true. Every assertion about what *should* be true lives in the
rules layer. Rule false-positives are inevitable; a checker that mixes them into
the data becomes untrustworthy. Findings are evidence, not verdicts.

## Layout

```
rpcb/
  sexpr.py            S-expression reader (no dependencies)
  project.py          .kicad_pro discovery + sheet-hierarchy walk
  extract.py          netlist + schematic -> design.json
  views.py            text renderers; return strings, never print
  rules.py            rules engine + CHECK_KINDS spec
  mcp.py              MCP stdio server (JSON-RPC 2.0, no SDK)
  cli.py              argparse front end + agent launcher
  rules_builtin.yaml  rules shipped with the tool
  review_prompt.md    instructions injected by `rpcb review`
plugins/rpcb/         Claude Code plugin — contains zero Python
docs/                 format research, roadmap
install.sh            CLI + both MCP registrations + plugin
```

`plugins/rpcb/` stays free of logic. It points at `rpcb` on PATH so Claude and
Codex run the same code.

## Git

- **Ask before committing.** Never commit unprompted.
- **No `Co-Authored-By` trailers.** No attribution lines of any kind.
- **Concise messages.** One line, imperative, lowercase after the prefix.
  A body only when the *why* is not obvious from the diff — and then one or two
  lines, not a changelog.

```
rules: make rpcb.yaml optional
fix: strip _<pin> suffix from pinfunction
docs: move format research into the repo
```

## Code

- **Small functions, small files.** One job each. If a function needs a section
  comment to explain its parts, split it.
- **Views return strings, never print.** The CLI, MCP server and launcher share
  them.
- **Fail loudly with a next step.** `rule X1 uses unknown check 'foo'. Run
  \`rpcb rules --kinds\`.` — not a silent no-op.
- **One source of truth.** `CHECK_KINDS` in `rules.py` defines the rule format;
  `rpcb rules --kinds` renders it and the docs point at that command. Don't
  restate it anywhere.
- **No new dependencies** without asking. Currently only `pyyaml`.

## Comments

Write a comment when a human would otherwise have to reconstruct *why* the code
is shaped that way — a non-obvious constraint, a rejected alternative, a
correctness trap.

```python
# The library pin name is authoritative; KiCad's `pinfunction`
# appends "_<pin>" to make it unique (PB6 -> PB6_45).
```

Do not narrate the diff, restate the code, or leave a marker at every change.
Comments describe the code as it stands, not its history — that is what git is
for.

## Before you finish

```bash
rpcb check          # in a real project
rpcb rules          # provenance still correct
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | rpcb mcp   # MCP responds
```

If you changed the model shape, bump `SCHEMA_VERSION` in `extract.py` — stale
models are detected by it.
