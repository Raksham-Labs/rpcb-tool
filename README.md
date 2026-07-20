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

Built-in rules run in **any** KiCad project with no configuration:

```bash
cd any-kicad-project && rpcb check      # works immediately, no setup
```

### `rpcb.yaml` is optional

A project file adds board-specific rules or tunes built-ins. You never need one
to use rpcb — delete it any time and `rpcb check` still works.

```bash
rpcb rules            # what is active, and where each rule comes from
rpcb rules --kinds    # every check kind, its parameters, a worked example
rpcb init             # scaffold rpcb.yaml, when you want one
```

`rpcb rules --kinds` is the authoritative reference. It is generated from the
engine itself, so it cannot drift from what the code accepts. A rule with an
unknown `check` or an invalid `severity` fails loudly and points you back to it.

### Structure

```yaml
rules:
  - id: CAN001                 # required. Reuse a built-in id to override it.
    check: net_must_contain    # required. See `rpcb rules --kinds`.
    severity: error            # error | warn | info. Default warn.
    why: >                     # shown with every finding
      CAN needs termination; 120R belongs only at physical bus ends.
    net: CANH                  # ...then the params for that check kind
    must_contain: [R2]
```

Add `enabled: false` to silence a built-in entirely.

### Tripwires vs silencing

There are two reasons to write a rule, and they are not equal.

A **tripwire** asserts something true of this board — `net_must_contain`,
`net_pin_count`. It stays silent while correct and fires when a later edit
breaks it. Producing no findings today is exactly the point; it is a regression
guard for the next revision.

**Silencing** — `ignore_nets`, `ignore_refs_matching`, `enabled: false` —
removes information. Every ignore is a place a real problem can hide. Only
silence a finding you have investigated, record the conclusion in `why`, and
check that the ignore would ever actually fire: an ignore that can never match
is dead config that misleads the next reader.

Prefer tripwires. Earn every ignore.

### Check kinds

| kind | flags |
|---|---|
| `undriven_power` | nets with `power_in` pins but no `power_out` source |
| `floating_pins` | pins of given types belonging to no net |
| `single_pin_net` | pins wired to nothing (aggregated per component) |
| `pin_type_present` | every pin of given types — surfaces ERC blind spots |
| `needs_pullup` | open-drain pins with no resistor to a rail |
| `decoupling` | capacitor count vs `power_in` count per power net |
| `value_vs_symbol` | Value disagrees with the symbol used |
| `required_field` | components missing a BOM field |
| `net_must_contain` | tripwire: named refs must sit on a net |
| `net_pin_count` | tripwire: net must have ≥ / ≤ N pins |

Run `rpcb rules --kinds` for parameters and examples.

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
  this part" — see [docs/roadmap-adversarial-review.md](docs/roadmap-adversarial-review.md)
  for the planned parts library.
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

## Docs

- [docs/kicad-file-format.md](docs/kicad-file-format.md) — what is actually
  inside a `.kicad_sch`, why 58% of it is noise, and the verified geometry rules
  (with the rotation bug that motivated using `kicad-cli`). This is the research
  the tool's design rests on.
- [docs/roadmap-adversarial-review.md](docs/roadmap-adversarial-review.md) —
  planned `rpcb duel`: Claude ↔ Codex adversarial review with a datasheet
  citation gate. Not built.
