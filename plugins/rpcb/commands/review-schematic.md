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
rpcb datasheets               required documents, canonical paths, BOM gaps
rpcb requirements             project requirements you must answer explicitly
rpcb text                     the ENTIRE design, compact (~6k tokens)
```

All accept `--json`. The model auto-regenerates when the schematic changes.

## Method

1. `rpcb summary` to orient.
2. `rpcb notes` **before** anything else. A finding that contradicts a designer
   note usually means you misread the design, not that there is a bug.
3. `rpcb datasheets` — **gather documents before reviewing.** See below.
4. `rpcb requirements` — what this project says must be true. Answer every one.
5. `rpcb check` for mechanical findings.
6. `rpcb text` if doing a full pass; targeted queries otherwise.

## Gather datasheets first — this blocks the review

`rpcb datasheets` names every part whose limits could matter and the one
canonical path each document belongs at (`vendor/<part>/datasheets/<MPN>.pdf`,
or `datasheets/<MPN>.pdf` where no vendor folder matches). It exits non-zero
while anything is absent or unfiled.

**It does not look inside any file.** `filed` means a file sits at that path —
a zero-byte file named correctly reports `filed`. You are the check.

1. **Open every file listed**, including the `unfiled` ones, and confirm which
   device each actually covers. Right document at the wrong name or in the wrong
   folder: move it to the canonical path, creating directories as needed. Wrong
   document: say so and treat the part as absent. A file for no part on this
   board: leave it and say what it is — never delete a document you did not add.
2. **Fetch what is absent** from the schematic's link or by searching the MPN,
   confirming the device before filing it.
3. **Ask the user for the rest, and stop.** Do not begin the review, and do not
   quietly review only the parts you have — a partial review reads as a complete
   one. Continue only if the user says to proceed without them.
4. **Report the BOM gaps** it lists — parts with no MPN or no manufacturer. MPN
   is the join key: without one a part cannot be looked up, filed, or ordered.

## Project requirements — answer every one, in a table

`rpcb requirements` lists what this project declares must be true of the board,
in plain English. No rule evaluates them — that is why they are written down for
you.

Open the review with a table covering **every** requirement, in order. Never
omit one: a requirement absent from the table reads as passed.

| id | requirement | verdict | evidence |
|---|---|---|---|
| REQ001 | MCU can put the transceiver in silent mode | MET | `U6.8 (S)` → `CAN_SILENT` → `U2.31`, driven |
| REQ002 | Every exposed pin has ESD protection | NOT MET | `J4.3` → `SWDIO` reaches `U2.34` with no TVS |

Verdicts, exactly these: **MET** (with specific evidence — refs, pins, nets or a
datasheet page; "looks fine" is not evidence), **NOT MET** (say what is absent),
**AT RISK** (partly satisfied, or only if an assumption holds — name it),
**UNVERIFIABLE** (cannot be settled from the schematic — say what would settle
it; this is honest, guessing is not).

`severity` orders the write-up, not the verdict. After the table, expand only
NOT MET, AT RISK, and any MET whose evidence needs explaining.

## Rules for reporting

**Verify before asserting.** `rpcb check` findings are prompts to look, not
defects. Confirm against the part's actual limits before calling something a
problem.

**Datasheet limits are not facts you remember.** Any claim about a supply range,
absolute maximum, drive strength, or timing must come from a datasheet in the
project that you actually opened — cite the part and page. If it is not there,
gathering is not finished. Only where the user has said to continue anyway,
label the finding **UNVERIFIED** and name the number that needs checking. Two
models agreeing on a recalled spec verifies nothing.

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
