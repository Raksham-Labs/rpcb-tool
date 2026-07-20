---
name: schematic-review
description: Query and review KiCad schematics — pin connections, nets, design rules, BOM checks. Use whenever the user asks about a schematic, netlist, PCB design, what a pin or net connects to, or wants a hardware design reviewed. Also use when a .kicad_sch or .kicad_pro file is in play.
---

# Reviewing KiCad schematics with `rpcb`

Never read `.kicad_sch` files directly. They are ~60% rendering data (font sizes,
stroke widths, fill types) and their connectivity is implicit in floating-point
pin coordinates — a wire connects to a pin only when two coordinates happen to
be equal. Deriving nets from that by hand is how you get a confidently wrong
answer.

`rpcb` gives you the netlist already resolved by KiCad itself.

## Commands

```
rpcb summary                  overview — start here (~200 tokens)
rpcb notes                    designer's annotations (stated intent)
rpcb check                    rule findings with evidence
rpcb component U6             every pin of one part: function, type, net
rpcb net +3.3V                every pin on one net
rpcb pin U2.45                what a single pin connects to (~50 tokens)
rpcb trace U2.45 --hops 3     walk outward through series passives
rpcb find CAN                 regex over refs, values, MPNs, nets, notes
rpcb datasheets               which parts need a datasheet, and which are here
rpcb requirements             project requirements you must answer explicitly
rpcb text                     the ENTIRE design, compact (~6k tokens)
```

All accept `--json`. The model regenerates automatically when the schematic
changes, so results are never stale.

If MCP tools named `design_*` are available, they are the same data — either
interface works.

## Method for a review

1. `rpcb summary` to orient.
2. `rpcb notes` **before** anything else. A finding that contradicts a designer
   note usually means you misread the design, not that there is a bug.
3. `rpcb datasheets` — **gather documents before reviewing.** See below.
4. `rpcb requirements` — what this project says must be true. Answer every one.
5. `rpcb check` for mechanical findings.
6. `rpcb text` for a full pass; targeted queries for single questions.

## Gather datasheets first — this blocks the review

You cannot verify an electrical limit you do not have. `rpcb datasheets` names
every part whose limits could matter and the one canonical path each document
belongs at:

```
vendor/<part>/datasheets/<MPN>.pdf    primary — beside that part's symbols,
                                      footprints and 3D models
datasheets/<MPN>.pdf                  secondary — a document covering several
                                      parts, one belonging to no single
                                      component, or where no vendor folder
                                      matches
```

It exits non-zero while anything is absent or unfiled.

**The command does not look inside any file.** `filed` means only that a file
sits at that path — a zero-byte file with the right name reports `filed`. You
are the check. Work the list until it exits clean, then review.

### 1. Open every file it lists

For each `filed` entry and every `unfiled` file, open the PDF and confirm which
device it actually covers.

- **Right document, right path** — leave it.
- **Right document, wrong name or wrong folder** — move it to the canonical path
  printed for that part, creating the directory if needed.
- **Wrong document** — do not leave it at a path that claims otherwise. Say so
  and treat that part as absent.
- **Not a part on this board** — leave it and say what it is. Never delete a
  document you did not add.

A datasheet link inherited from a borrowed symbol may name another device, so a
filename is never evidence of contents.

### 2. Fetch what is absent

Use the link the schematic carries, or search the MPN. Confirm the document
names the part before filing it. A confidently wrong datasheet is worse than a
missing one.

### 3. Ask for the rest, and stop

If you cannot fetch one, list those parts, say what you tried, and ask the user
for the documents. **Do not begin the review.** Do not quietly review the parts
you do have — a partial review reads as a complete one. Proceed only if the user
explicitly says to go ahead without them.

### 4. Report the BOM gaps

The command lists parts with no MPN and parts with no manufacturer. Tell the
user to fix them in the schematic: MPN is the join key, so a part without one
cannot be looked up, filed, or ordered. Report this even when nothing blocked
you.

### What does not need a datasheet

Connectivity questions — what a pin joins, what sits on a net, whether a rail is
driven — need no document; answer those freely. The gate applies the moment a
claim turns on a voltage, current, timing or thermal number.

## Project requirements — answer every one, in a table

`rpcb requirements` lists what this project has declared must be true of the
board, in plain English. These live in `rpcb.yaml` alongside `rules:` but are
deliberately separate from them:

```
rules:         mechanical, evaluated by the engine, same answer every run
requirements:  prose, evaluated by you, answered with evidence
```

No rule evaluates a requirement — that is why it is written down for you.

Open the review with a table covering **every** requirement, in order. Never
omit one: a requirement absent from the table reads as passed, and that silence
is exactly what the table exists to prevent.

| id | requirement | verdict | evidence |
|---|---|---|---|
| REQ001 | MCU can put the transceiver in silent mode | MET | `U6.8 (S)` → `CAN_SILENT` → `U2.31`, driven |
| REQ002 | Every exposed pin has ESD protection | NOT MET | `J4.3` → `SWDIO` reaches `U2.34` with no TVS |

Use exactly these verdicts:

- **MET** — satisfied, with specific evidence: refs, pins, nets, or a datasheet
  page. "Looks fine" is not evidence.
- **NOT MET** — not satisfied. Say precisely what is absent or wrong.
- **AT RISK** — partly satisfied, or only if an assumption holds. Name it.
- **UNVERIFIABLE** — cannot be settled from the schematic. Say what would settle
  it — the PCB layout, a datasheet you could not obtain, the designer's intent.
  This is an honest answer; guessing is not.

`severity` orders the write-up, not the verdict: an `error` requirement coming
back NOT MET leads the report. After the table, expand only the rows that need
it — every NOT MET and AT RISK, plus any MET whose evidence needs explaining.
Do not restate passing rows in prose.

## Reporting rules

**Verify before asserting.** `rpcb check` findings are prompts to look, not
defects. The rules cannot see datasheets, physical layout, or intent.

**Datasheet limits are not facts you remember.** Any claim about a supply range,
absolute maximum, drive strength, or timing must come from a datasheet in the
project that you actually opened — cite the part and the page. If it is not
there, gathering is not finished: fetch it or ask, rather than reasoning from
recall. Where the user has explicitly said to continue without one, label the
finding **UNVERIFIED** and name the number that needs checking. Two models
agreeing on a recalled spec verifies nothing — agreement is the failure mode,
not the check.

**Do the arithmetic.** "Marginal supply" is not a finding. "5V − 0.4V Schottky
drop = 4.6V against a 4.5V minimum, so a 4.75V input is out of spec" is.

**Check symbol against value.** Where a component's Value and its schematic
symbol disagree, confirm the pinouts match per pin — a wrong symbol yields a
correct-looking netlist for the wrong part. This also means datasheet links
inherited from a borrowed symbol may point at the wrong device entirely.

**Separate verified from assumed.** If a finding depends on intent you cannot
see — bus topology, whether a pad drives 5V logic, whether a spare pin is
deliberate — say so and ask rather than asserting a defect.

**Rank by consequence.** Something that intermittently degrades a bus outranks a
missing MPN.

Close with what checks out, so silence on those reads as deliberate.

## Writing rules (only when the user asks)

`rpcb check` runs built-in rules with **no configuration**. A project needs no
`rpcb.yaml` at all — never create one unprompted.

When the user does want a rule, this is the workflow:

```
rpcb rules            # what is active, and where each rule comes from
rpcb rules --kinds    # every check kind, its parameters, a worked example
rpcb init             # scaffold rpcb.yaml (only if it does not exist)
```

`rpcb rules --kinds` is the authoritative reference — read it before writing a
rule rather than guessing parameter names. A rule with an unknown `check` or a
bad `severity` fails loudly with a pointer back to that command.

A rule is a YAML mapping under `rules:` in `rpcb.yaml`:

```yaml
rules:
  - id: CAN001                 # reuse a built-in id to override it
    severity: error            # error | warn | info
    check: net_must_contain    # see rpcb rules --kinds
    net: CANH
    must_contain: [R2]
    why: CAN needs termination; 120R belongs only at physical bus ends.
```

### Prefer tripwires over silencing

A **tripwire** asserts something true of this board. It stays silent while
correct and fires when a later edit breaks it — `net_must_contain` and
`net_pin_count` exist for this. Producing no findings today is the point, not a
sign it is useless.

**Silencing** (`ignore_nets`, `ignore_refs_matching`, `enabled: false`) removes
information. Every ignore is a place a real problem can hide later. Only propose
one for a finding that has actually been investigated and understood, and say in
`why` what was concluded — a bare ignore with no reasoning is worse than the
noise it removes.

Before adding an ignore, check whether it would ever fire. An ignore that can
never match is dead config that misleads whoever reads it next.
