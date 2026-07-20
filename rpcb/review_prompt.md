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

## Get the datasheets you need BEFORE reviewing

This matters more than it sounds. Every wrong-but-confident hardware finding
comes from the same place: a limit recalled instead of read. You cannot tell
from the inside which of your remembered numbers is the wrong one, and a second
opinion agreeing with you proves nothing — you would both be recalling. The
document is the only thing that settles it, and it has to be in hand *before*
you start reasoning, because once you have formed a view you will read the
datasheet looking for confirmation rather than the number.

`rpcb datasheets` gives you the candidates: every part that could plausibly need
a document, with its part number, pin count, description, and the canonical path
its datasheet belongs at.

### 1. Decide which ones this review actually turns on

**This is your judgement, and the command deliberately does not make it.** It
cannot: which parts matter depends on what you are reviewing, and it does not
know that.

Reason from what you are being asked. A general review turns on the parts whose
behaviour you cannot derive from the schematic — MCUs, regulators, sensors,
transceivers, crystals: supply windows, drive strength, load capacitance,
timing. A question about one subsystem turns on that subsystem's parts and
little else.

Do not reflexively fetch everything. Twenty documents you did not read are worse
than five you did, because the list starts looking like a chore instead of
evidence. But do not under-reach either: if a finding ends up resting on a TVS
standoff voltage, a Schottky drop, or a connector's current rating, you needed
that document, so go get it then.

**Say what you decided.** List the parts you judged this review does not turn
on, in one line each. A part silently dropped is indistinguishable from one you
forgot.

### 2. Open every file already on disk

`filed` means only that a file sits at the canonical path — the command never
reads it, and a zero-byte file with the right name reports `filed`. You are the
check. For each `filed` entry and every `unfiled` file, open it and confirm
which device it covers:

- **Right document, right path** — leave it.
- **Right document, wrong name or folder** — move it to the canonical path
  printed for that part, creating directories as needed.
- **Wrong document** — do not leave it at a path claiming otherwise. Say so and
  treat that part as absent.
- **Not a part on this board** — leave it and say what it is. Never delete a
  document you did not add.

A datasheet link inherited from a borrowed symbol may name a different device,
so a filename is never evidence of contents.

### 3. Fetch what you decided you need

Use the link the schematic carries, or search the MPN. Confirm the document
names the part before filing it — a confidently wrong datasheet is worse than a
missing one.

### 4. Ask for what you cannot get, and stop

If a document you decided you need cannot be fetched, name those parts, say what
you tried, and ask the user for them. **Do not start the review.** Do not
quietly review around them: a partial review reads as a complete one. Proceed
only if the user says to go ahead without them, and then label every affected
finding **UNVERIFIED**.

### 5. Report the BOM gaps

The command lists parts with no MPN and no manufacturer. Tell the user to fix
them: MPN is the join key, so a part without one cannot be looked up, filed, or
ordered. Report this even when it did not affect your review.

### What needs no datasheet

Connectivity — what a pin joins, what sits on a net, whether a rail is driven —
is answered by the model itself. Answer those freely. The obligation starts the
moment a claim turns on a voltage, current, timing or thermal number.

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
