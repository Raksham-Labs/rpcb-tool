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
3. `rpcb check` for mechanical findings.
4. `rpcb text` for a full pass; targeted queries for single questions.

## Reporting rules

**Verify before asserting.** `rpcb check` findings are prompts to look, not
defects. The rules cannot see datasheets, physical layout, or intent.

**Datasheet limits are not facts you remember.** Any claim about a supply range,
absolute maximum, drive strength, or timing must come from a datasheet you
actually consulted. If you cannot cite one, label the finding **UNVERIFIED** and
name the number that needs checking. Two models agreeing on a recalled spec
verifies nothing — agreement is the failure mode, not the check.

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
