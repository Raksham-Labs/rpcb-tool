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
rpcb datasheets               which parts need a datasheet, and which are here
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
canonical path each document belongs at. It exits non-zero while anything is
absent or unfiled.

**It does not check what is inside any file.** `filed` means only that a file
sits at that path — a zero-byte file named correctly would say `filed`. You are
the check. Work the list until the command exits clean, then review.

### 1. Open every file it lists

For each `filed` entry and every `unfiled` file, open the PDF and confirm which
device it actually covers. Then:

- **Right document, right path** — leave it.
- **Right document, wrong name or wrong folder** — move it to the canonical path
  the command printed. Create the directory if it does not exist.
- **Wrong document** — do not leave it sitting at a path that claims otherwise.
  Say so, and treat that part as absent.
- **A part not on this board** — leave the file alone and say what it is. Never
  delete a document you did not add.

A datasheet link inherited from a borrowed symbol may name another device
entirely, so a file's name is never evidence of its contents.

### 2. Fetch what is absent

Use the link the schematic carries, or search the MPN. Confirm the document
names the part before filing it at the canonical path. A confidently wrong
datasheet is worse than a missing one.

### 3. Ask for whatever is left, and stop

If you cannot fetch a document, list the parts, say what you tried, and ask the
user for it. **Do not begin the review.** Do not review "the parts you do have"
and leave the rest for later unless the user explicitly tells you to proceed
without them — a partial review reads as a complete one.

### 4. Report the BOM gaps

`rpcb datasheets` lists parts with no MPN and parts with no manufacturer. Tell
the user to fix them in the schematic. MPN is the join key: a part without one
cannot be looked up, cannot be filed under a canonical name, and cannot be
ordered. Report this whether or not it blocked you.

### What does not need a datasheet

Connectivity questions — what a pin joins, what sits on a net, whether a rail is
driven — need no document; answer those freely. The gate applies the moment a
claim turns on a voltage, current, timing or thermal number.

## Project requirements — answer every one, in a table

`rpcb requirements` lists what this project has declared must be true of the
board, in plain English. No rule evaluates them; that is why they are written
down for you. **You are the check.**

Open your report with a table covering **every** requirement, in order. Never
omit one — a requirement absent from the table reads as passed, and silence is
the failure mode this table exists to prevent.

| id | requirement | verdict | evidence |
|---|---|---|---|
| REQ001 | MCU can put the transceiver in silent mode | MET | `U6.8 (S)` → `CAN_SILENT` → `U2.31`, driven |
| REQ002 | Every exposed pin has ESD protection | NOT MET | `J4.3` → `SWDIO` reaches `U2.34` with no TVS |

Use exactly these verdicts:

- **MET** — satisfied, with specific evidence: refs, pins, nets, or a datasheet
  page. "Looks fine" is not evidence.
- **NOT MET** — not satisfied. Say precisely what is absent or wrong.
- **AT RISK** — partly satisfied, or satisfied only if an assumption holds. Name
  the assumption.
- **UNVERIFIABLE** — cannot be settled from the schematic. Say what would settle
  it: the PCB layout, a datasheet you could not obtain, or the designer's
  intent. This is an honest answer; guessing is not.

A requirement's `severity` orders your write-up, not the verdict. An `error`
requirement returning NOT MET leads the report.

After the table, expand only the rows that need it — every NOT MET and AT RISK,
and any MET whose evidence needs explaining. Do not restate the passing rows in
prose.

## Rules for reporting

**Verify before asserting.** `rpcb check` findings are prompts to look, not
defects. Confirm against the part's actual limits before calling something a
problem.

**Datasheet limits are not facts you remember.** Any claim about a supply range,
absolute maximum, drive strength, or timing must come from a datasheet in the
project that you actually opened. Cite the part and page. If the document is not
there, you have not finished gathering — go back and fetch it or ask for it.
Where you genuinely cannot get it and the user has said to continue anyway,
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
