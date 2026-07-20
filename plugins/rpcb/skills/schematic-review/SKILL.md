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

## Project-specific rules

Board-specific rules live in `rpcb.yaml` at the project root and can also
override or silence built-ins by id. `rpcb rules` lists what is active;
`rpcb init` scaffolds the file.
