# Writing `rpcb.yaml` for this board

You are generating a project rule file for one specific KiCad board. The
built-in rules already run everywhere with no configuration — this file exists
only to assert things that are true of **this** design and could not be known
generically.

## What you are producing

A `rpcb.yaml` whose rules would each fire if a later edit broke something real.
Not a summary of the board. Not a restatement of the built-ins.

If, after studying the design, there is nothing worth asserting, **write no
file** and say so. An empty ruleset is a legitimate and common outcome; a file
full of rules that can never fire is worse than none, because the next reader
believes it is covered.

## Method

1. `rpcb summary` — orient.
2. `rpcb notes` — the designer's stated intent. This is the richest source of
   tripwires: a note saying "120R only at bus ends" is an assertion someone
   already made in prose, and turning it into a rule is exactly the job.
3. `rpcb check` — see what the built-ins already catch. **Never write a rule
   that duplicates one.** Run `rpcb rules` to see what is active.
4. `rpcb rules --kinds` — the authoritative parameter reference. Read it before
   writing, rather than guessing field names. It is generated from the engine,
   so it cannot drift from what the code accepts.
5. `rpcb text` — the whole design, if you need it.

## What makes a good rule here

**Prefer tripwires.** A tripwire asserts something true now and stays silent
while it stays true — `net_must_contain`, `net_pin_count`. Producing no findings
today is the point: it is a regression guard for the next revision. Good
candidates are structural facts a future edit could plausibly break:

- a termination resistor that belongs on a specific net
- a pull-up whose absence would be silent but wrong
- the expected pin count on a bus, so a stray connection is caught
- a rail that must reach a specific set of parts

**Earn every ignore.** `ignore_nets`, `ignore_refs_matching` and
`enabled: false` remove information, and every ignore is a place a real problem
can hide. Only silence a finding you have actually investigated, record the
conclusion in `why`, and check the ignore would ever match — an ignore that
cannot fire is dead config that misleads whoever reads it next.

**Do not encode datasheet limits.** Rules cannot read datasheets, and a rule
asserting "4.5V minimum" is a remembered number wearing the costume of a check.
Limits belong in a review, with the document open.

## Two kinds of entry

```
rules:         mechanical, evaluated by the engine, same answer every run
requirements:  prose, evaluated by a reviewer, answered with evidence
```

When something matters but **no check kind expresses it**, do not force it into
a rule that pattern-matches net names — a rule firing on a name rather than the
intent is worse than no rule, because it looks like coverage. Write it as a
requirement instead:

```yaml
requirements:
  - id: REQ001
    severity: error
    must: >
      The MCU must be able to put the CAN transceiver into silent mode.
    why: >
      Field units share the bus with a diagnostic tool; a stuck transmitter
      takes the whole bus down and cannot be isolated in the field.
    refs: [U2, U6]
    nets: [CANH, CANL]
```

`must` has to be an **assertion the board either satisfies or does not** — not a
topic. "Check the CAN bus" cannot be answered; "every CAN transceiver can be put
in silent mode by the MCU" can. Every review returns an explicit verdict for
every requirement, so a vague one produces a vague verdict forever.

Designer notes are the best source for both. A note stating intent that no check
kind can express is a requirement; one asserting a structural fact is a rule.

## Format

```yaml
rules:
  - id: CAN001                 # required. Reuse a built-in id to override it.
    check: net_must_contain    # required. See `rpcb rules --kinds`.
    severity: error            # error | warn | info. Default warn.
    why: >                     # shown with every finding — say why it matters,
      CAN needs termination;   # not what the rule does
      120R belongs only at physical bus ends.
    net: CANH                  # ...then the params for that check kind
    must_contain: [R2]
```

`why` is read by whoever hits the finding months from now. "Termination
missing" tells them nothing they cannot see. Say what breaks if it is wrong.

## Before you finish

1. Run `rpcb check` with your file in place. Every rule must parse, and you must
   be able to explain each finding it produces.
2. Confirm each tripwire is silent **now** — a tripwire firing on the current
   board is either a real bug you have just found (say so, prominently) or a
   rule you have written backwards.
3. Deliberately reason about whether each rule could ever fire. Say which edit
   would trip it. If you cannot name one, delete the rule.
4. Report what you wrote and why, and name anything you considered and rejected.
