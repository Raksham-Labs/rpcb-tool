# rpcb

Feed KiCad schematics to LLMs. Resolved netlist model, pin/net queries,
declarative design rules, MCP server, and an agent launcher.

A `.kicad_sch` file is ~60% rendering data, and its connectivity is *implicit in
floating-point pin coordinates* — a wire connects to a pin only when two numbers
happen to be equal. Handing that to a model is how you get confidently wrong
answers about what is wired to what. `rpcb` hands it a resolved netlist instead:
**~100k tokens of schematic → ~6k tokens of design.**

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/USER/rpcb-tool/main/install.sh | bash
```

Installs the CLI, registers the MCP server with **both** Claude Code and Codex,
and installs the Claude Code plugin. Idempotent; `./install.sh --uninstall`
reverses it. Requires Python 3.9+ and KiCad (for `kicad-cli`).

## Use

```bash
cd any-kicad-project

rpcb summary                  # overview (~200 tokens)
rpcb notes                    # designer's annotations
rpcb check                    # run design rules
rpcb component U6             # every pin: function, type, net
rpcb net +3.3V                # every pin on a net
rpcb pin U2.45                # what one pin connects to (~50 tokens)
rpcb trace U2.45 --hops 3     # walk outward through series passives
rpcb find CAN                 # regex over refs, values, MPNs, nets, notes
rpcb text                     # the entire design, compact (~6k tokens)

rpcb review                   # launch Claude with the design preloaded
rpcb review --codex           # same, with Codex
```

All accept `--json`. No configuration: the project is found by walking up to the
nearest `.kicad_pro`, and the sheet hierarchy is discovered by following
`Sheetfile` references.

In Claude Code you also get `/review-schematic`, a `schematic-review` skill, and
`design_*` MCP tools.

## Why connectivity comes from KiCad

Nets are **not** re-derived from pin geometry. A hand-rolled resolver was built
once and matched KiCad exactly (75/75 nets) — but only after fixing a bug where
the wrong rotation direction silently swapped pins 1↔2 on every 270°-rotated
part, reversing four protection diodes. Every pin still landed neatly on a wire,
so the netlist looked perfectly valid while being wrong.

A confidently-wrong netlist is worse than none. `kicad-cli sch export netlist`
is authoritative; the schematic is parsed only for what the netlist drops —
text notes, `dnp`, `in_bom`.

## Facts vs judgement

The extracted model contains only what is mechanically true: pins, nets,
electrical types, notes. Every assertion about what *should* be true lives in
rules.

This matters because rule false-positives are inevitable, and a checker that
mixes them into the data becomes untrustworthy. Findings are **evidence, not
verdicts** — a prompt to look.

## Rules

Built-ins ship with rpcb. Project rules go in `rpcb.yaml` at the project root
(`rpcb init` scaffolds it), and may add rules or override/silence built-ins by
reusing an `id`:

```yaml
rules:
  - id: PWR001
    ignore_nets: [VSYS]        # tweak a parameter
  - id: BOM001
    enabled: false             # silence entirely
  - id: CAN001                 # or add your own
    severity: error
    check: net_must_contain
    net: CANH
    must_contain: [R2]
    why: CAN needs termination; 120R only at physical bus ends.
```

Check kinds: `undriven_power`, `floating_pins`, `single_pin_net`,
`pin_type_present`, `needs_pullup`, `decoupling`, `value_vs_symbol`,
`required_field`, `net_must_contain`, `net_pin_count`.

Modifiers: `ignore_nets`, `ignore_types`, `ignore_refs_matching`,
`only_refs_matching`, `enabled`.

## Data model

JSON, not a graph database. At a few hundred nets a graph DB is pure operational
overhead. The *model* is still graph-shaped: a netlist is a **hypergraph** (a net
joins N pins, not 2), stored bipartite as pins ↔ nets, with indexes under
`graph`:

- `pin_to_net` — `"U2.45"` → `"USART1_TX"`
- `net_to_pins` — reverse
- `signal_neighbors` — component adjacency **excluding power rails**; including
  GND would make every component adjacent to every other and carry no
  information

Derived data lives in `.rpcb/` (self-gitignoring). It regenerates automatically
whenever a schematic's SHA-256 changes, so an agent can never read a stale model.

## Known limitations

- **Physical proximity is invisible.** The decoupling rule counts caps on a
  rail; it cannot tell whether one sits near the pin it serves. That needs the
  PCB.
- **Datasheet limits are not modelled.** Rules cannot check "is 4.6V enough for
  this part" — see `plan.md` in a project for the parts-library approach.
- **No `no_connect` flags** in a design means an unwired pin is
  indistinguishable from a deliberately-unused one.

## Layout

```
rpcb/
  sexpr.py            S-expression reader (no dependencies)
  project.py          .kicad_pro discovery + sheet-hierarchy walk
  extract.py          netlist + schematic -> design.json
  views.py            text renderers (return strings; shared by CLI and MCP)
  rules.py            declarative rules engine
  mcp.py              MCP stdio server (JSON-RPC 2.0, no SDK)
  cli.py              argparse front end + agent launcher
  rules_builtin.yaml  rules shipped with the tool
  review_prompt.md    instructions injected by `rpcb review`
plugins/rpcb/         Claude Code plugin (thin: no Python)
install.sh
```

The plugin contains **zero Python** — it points at `rpcb` on PATH, so Claude and
Codex run the same implementation.
