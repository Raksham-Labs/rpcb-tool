---
description: Review the KiCad schematic for electrical and BOM problems
---

# Schematic review via `rpcb`

You are reviewing a KiCad schematic. The `rpcb` CLI gives you a resolved model
of the design — connectivity is already computed by KiCad itself, so you never
need to read `.kicad_sch` files or reason about pin coordinates.

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

All accept `--json`. The model auto-regenerates when the schematic changes.

## Method

1. `rpcb summary` to orient.
2. `rpcb notes` **before** anything else. A finding that contradicts a designer
   note usually means you misread the design, not that there is a bug.
3. `rpcb check` for mechanical findings.
4. `rpcb text` if doing a full pass; targeted queries otherwise.

## Rules for reporting

**Verify before asserting.** `rpcb check` findings are prompts to look, not
defects. Confirm against the part's actual limits before calling something a
problem.

**Datasheet limits are not facts you remember.** Any claim about a supply range,
absolute maximum, drive strength, or timing must come from a datasheet you
actually consulted. If you cannot cite one, label the finding **UNVERIFIED** and
say which number needs checking. Two models agreeing on a recalled spec verifies
nothing.

**Do the arithmetic.** "Marginal supply" is not a finding. "5V − 0.4V Schottky
drop = 4.6V against a 4.5V minimum, so a 4.75V input puts it out of spec" is.
Quote real numbers from the model.

**Check symbol against value.** Where a component's Value and its schematic
symbol disagree, confirm the pinouts actually match — a wrong symbol yields a
correct-looking netlist for the wrong part. Report per-pin differences, not just
the name mismatch.

**Separate verified from assumed.** If a finding depends on intent you cannot
see — bus topology, whether a pad drives 5V logic, whether a spare pin is
deliberate — say so and ask, rather than asserting a defect.

**Rank by consequence.** Something that intermittently degrades a bus outranks a
missing MPN. Lead with what would actually bite.

Close with what checks out, so silence on those reads as deliberate rather than
an omission.

$ARGUMENTS
