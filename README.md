# rpcb

Feed KiCad schematics to LLMs. Resolved netlist model, pin/net queries,
declarative design rules, MCP server, and an agent launcher.

A `.kicad_sch` file is ~60% rendering data, and its connectivity is *implicit in
floating-point pin coordinates* — a wire connects to a pin only when two numbers
happen to be equal. Handing that to a model is how you get confidently wrong
answers about what is wired to what. `rpcb` hands it a resolved netlist instead:
**~100k tokens of schematic → ~6k tokens of design.**

## Install

macOS / Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/Raksham-Labs/rpcb-tool/main/install.sh | bash
```

Windows (PowerShell):

```powershell
irm https://raw.githubusercontent.com/Raksham-Labs/rpcb-tool/main/install.ps1 | iex
```

Installs the CLI, registers the MCP server with **both** Claude Code and Codex,
and installs the Claude Code plugin. Idempotent; `./install.sh --uninstall` /
`.\install.ps1 -Uninstall` reverses it. Requires Python 3.9+ and KiCad (for
`kicad-cli`).

Use `install.ps1` in a native PowerShell prompt, not `install.sh` under Git Bash
— Windows venvs use `Scripts\` rather than `bin/`, and `python3` there is
usually the Microsoft Store stub. Under WSL, use `install.sh` and install KiCad
and the `claude` CLI inside WSL too, since the MCP server shells out to
`kicad-cli`.

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
rpcb datasheets               # which parts need a datasheet, and which are here
rpcb requirements             # project requirements a reviewer must answer
rpcb text                     # the entire design, compact (~6k tokens)

rpcb review                   # launch Claude with the design preloaded
rpcb review --codex           # same, with Codex
```

All accept `--json`. No configuration: the project is found by walking up to the
nearest `.kicad_pro`, and the sheet hierarchy is discovered by following
`Sheetfile` references.

In Claude Code you also get `/review-schematic`, `/rpcb-init-rules`, a
`schematic-review` skill, and `design_*` MCP tools.

## Why connectivity comes from KiCad

Nets are **not** re-derived from pin geometry. A hand-rolled resolver was built
once and matched KiCad exactly (75/75 nets) — but only after fixing a bug where
the wrong rotation direction silently swapped pins 1↔2 on every 270°-rotated
part, reversing four protection diodes. Every pin still landed neatly on a wire,
so the netlist looked perfectly valid while being wrong.

A confidently-wrong netlist is worse than none. `kicad-cli sch export netlist`
is authoritative; the schematic is parsed only for what the netlist drops —
text notes, `dnp`, `in_bom`.

## Datasheets

A rule can prove a pin is floating. It cannot tell you whether 4.6V clears a
part's minimum — that needs the document.

```bash
rpcb datasheets            # candidates, with what is on disk
rpcb datasheets --strict   # exit 1 if any candidate is absent (for CI)
```

### The command lists candidates; the reviewer decides

It reports every part that could plausibly need a datasheet, with part number,
**pin count** and **description** — enough to tell a 49-pin Cortex-M0 from a
2-pin indicator LED — then stops. Which ones a given review turns on depends on
what is being reviewed, and no reference prefix knows that: a TVS standoff
voltage is the whole question on one board and irrelevant on the next.

So it exits 0. An earlier version blocked on every non-passive part, which on a
real board meant 17 documents when 7 mattered, and the reviewer dutifully began
bulk-downloading LEDs and connectors. **A gate that demands too much gets worked
around rather than satisfied.** The obligation to gather before reviewing lives
in the prompts, where the judgement is: the reviewer picks what its findings
will rest on, fetches those first, and must state in one line each which parts
it judged irrelevant — a silent drop being indistinguishable from a forgotten
one.

`--strict` is for CI, which genuinely does want everything on disk.

Every part gets one canonical path, derived from its MPN:

```
vendor/<part>/datasheets/<MPN>.pdf   primary — beside that part's symbols,
                                     footprints and 3D models
datasheets/<MPN>.pdf                 secondary — a document covering several
                                     parts, one belonging to no single
                                     component, or where no vendor folder
                                     matches
```

Parts route to a vendor folder by symbol library
(`vendor/can_transceiver/CANBUS.kicad_sym` claims `CANBUS:MCP2562`) or by folder
name prefixing the part number (`vendor/stm32g0` claims `STM32G0B1CCU6`).
Neither can invent a folder that does not exist, so where nothing matches the
shared directory is the honest answer rather than a guessed name.

### The tool does not open the files

`filed` means only that a file sits at the canonical path. It is not a claim
about contents — a zero-byte file with the right name reports `filed`.

This was deliberate. An earlier version matched part numbers against filenames
and called that *present*, which passed both an empty file and one containing
the wrong device. **A check that only reads names accepts anything named
correctly**, so it was removed rather than tuned. What remains is mechanical and
therefore trustworthy: which parts need a document, where each belongs, whether
a file is there, and which files are unfiled.

Confirming the device, renaming, moving and fetching are the agent's work. The
prompts require it to open every file, move anything misnamed or misplaced to
its canonical path, fetch what it decided it needs, and **stop and ask** for the
rest rather than reviewing from recall — a partial review reads as a complete
one.

The prompts also say *why* this is worth the ceremony: every wrong-but-confident
hardware finding is a limit recalled instead of read, you cannot tell from the
inside which remembered number is the wrong one, and a second model agreeing
proves nothing because it is also recalling. The document has to be in hand
before reasoning starts — afterwards you read it looking for confirmation rather
than for the number.

Parts with no MPN and no part number in Value come back **unidentified**: there
is nothing to look up and no canonical name to file under, so the fix is the
BOM, not the document. They do not hold the gate shut, or an unlabelled 2-pin
header would fail it forever. `rpcb datasheets` also lists BOM gaps — missing
MPN, missing manufacturer — for the agent to report back.

Connectivity questions need no datasheet. The gate applies the moment a claim
turns on a voltage, current, timing or thermal number.

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
rpcb init             # scaffold a blank rpcb.yaml, when you want one
rpcb init --agent     # have an agent study the board and write real rules
```

`rpcb init` writes a blank form. `rpcb init --agent` launches Claude (or Codex,
with `--codex`) against the board with instructions for writing tripwires: read
the designer's notes, check what the built-ins already catch, and assert only
what is true of *this* design. It is told to write **no file** when nothing is
worth asserting — a ruleset that can never fire is worse than none, because the
next reader believes the board is covered.

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

### Requirements — plain English, for what no rule can express

```
rules:         mechanical, evaluated by the engine, same answer every run
requirements:  prose, evaluated by a reviewer, answered with evidence
```

Plenty of what matters about a board has no check kind. "The MCU must be able to
put the CAN transceiver in silent mode" is perfectly checkable — but only by
someone reading the design, and a rule that pattern-matched net names to fake it
would fire on the name rather than the intent, which is worse than no rule
because it looks like coverage.

```yaml
requirements:
  - id: REQ001
    severity: error              # orders the write-up, not the verdict
    must: >                      # an assertion, not a topic
      The MCU must be able to put the CAN transceiver into silent mode.
    why: >
      Field units share the bus with a diagnostic tool; a stuck transmitter
      takes the whole bus down and cannot be isolated in the field.
    refs: [U2, U6]               # optional: where to start looking
    nets: [CANH, CANL]           # optional
```

```bash
rpcb requirements     # what is declared, and the verdicts expected
```

`must` has to be something the board either satisfies or does not. "Check the
CAN bus" cannot be answered; the example above can. A malformed entry — no `id`,
no `must`, a duplicate id, an invalid severity — fails loudly rather than being
skipped.

Every review must return an explicit verdict for **every** requirement, in a
table:

| id | requirement | verdict | evidence |
|---|---|---|---|
| REQ001 | MCU can put the transceiver in silent mode | MET | `U6.8 (S)` → `CAN_SILENT` → `U2.31`, driven |
| REQ002 | Every exposed pin has ESD protection | NOT MET | `J4.3` → `SWDIO` reaches `U2.34` with no TVS |

**MET** needs specific evidence — refs, pins, nets, a datasheet page; "looks
fine" is not evidence. **AT RISK** names the assumption it depends on.
**UNVERIFIABLE** says what would settle it — the PCB, a datasheet, the
designer's intent — which is an honest answer where guessing is not.

The table is the point. A requirement missing from a report reads as passed, so
omitting one is the failure this exists to prevent. `rpcb check` will not
evaluate requirements — it only tells you how many are waiting on a verdict.

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
- **Datasheet limits are not modelled.** `rpcb datasheets` gets the documents
  in front of the reviewer, but no rule reads them — "is 4.6V enough for this
  part" is still a judgement call, not a check. See
  [docs/roadmap-adversarial-review.md](docs/roadmap-adversarial-review.md) for
  the planned parts library that would make it mechanical.
- **No `no_connect` flags** in a design means an unwired pin is
  indistinguishable from a deliberately-unused one.

## Layout

```
rpcb/
  sexpr.py            S-expression reader (no dependencies)
  project.py          .kicad_pro discovery + sheet-hierarchy walk
  extract.py          netlist + schematic -> design.json
  datasheets.py       which parts need a datasheet, and which are on disk
  requirements.py     plain-English requirements a reviewer must answer
  views.py            text renderers (return strings; shared by CLI and MCP)
  rules/
    spec.py           what a rule may contain (CHECK_KINDS)
    loader.py         built-ins merged with the project's optional rpcb.yaml
    engine.py         evaluation and rendering
    builtin.yaml      rules shipped with the tool
  mcp.py              MCP stdio server (JSON-RPC 2.0, no SDK)
  cli.py              argparse front end + agent launcher
  review_prompt.md    instructions injected by `rpcb review`
  init_prompt.md      instructions injected by `rpcb init --agent`
plugins/rpcb/         Claude Code plugin (thin: no Python)
install.sh            macOS / Linux
install.ps1           Windows
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
