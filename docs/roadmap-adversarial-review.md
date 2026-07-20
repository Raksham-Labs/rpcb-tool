# Roadmap: adversarial review (`rpcb duel`)

Design agreed but **not built**. Depends on `parts.yaml` existing first — the
citation gate below is the whole point, and it cannot work without it.

## Why

Two agents agreeing is **not** evidence of correctness. They can share the same
wrong recollection of a spec and reinforce it into false confidence — worse than
one agent, because agreement reads as verification.

This is not hypothetical. In an early review, the top-ranked finding was that a
transceiver sat below its minimum supply voltage — a conclusion that rested
entirely on a minimum-VDD figure recalled from model memory and never checked
against the datasheet. The connectivity behind it was solid; the limit it was
compared against was not. A second model recalling the same number would have
confirmed nothing.

## Shape

```
rpcb duel
  ├─ seed: rpcb check findings + fresh full-text extract   (deterministic, free)
  ├─ round loop (cap 2-3):
  │     claude -p   role: PROPOSER — find problems, cite evidence
  │     codex exec  role: REFUTER  — kill these findings, default to refuted
  │     (swap roles each round)
  ├─ state: findings.json — proposed → refuted | confirmed | disputed
  ├─ stop: a round changes no state, or cap reached
  └─ out:  disputes FIRST, then confirmed; transcripts archived per run
```

## Non-negotiable design points

1. **The conductor is a neutral referee.** If Claude orchestrates, it is player
   and referee at once — deciding when its own findings survived. A small
   external script conducting both as headless workers removes that.

2. **Deterministic control path.** No model decides loop flow, role assignment,
   or status transitions. Plain code.

3. **Do not rebuild the runtime.** `claude -p` and `codex exec` already contain
   full agentic loops. Shell out to them; never re-implement tool dispatch,
   retries, or context management. Subscriptions authenticate through the CLIs.

4. **The citation gate** — the reason this is worth building at all:

   > A finding citing an electrical limit cannot reach `confirmed` unless the
   > limit exists in `parts.yaml` with a page reference, regardless of how many
   > models agree.

   Prompting cannot enforce this, because agreement is the failure mode. A
   referee script can: `if not citation: status = "unverified"`.

5. **Surface disputes, not consensus.** Where two frontier models still disagree
   after a full round is the shortlist worth a human minute. Agreement is
   boring; conflict is information.

6. **Cap rounds hard.** Each round is two full headless sessions. Run before
   fab, not on every edit.

## Escalation ladder

| Rung | What | When |
|---|---|---|
| 1 | shell out to `claude -p` / `codex exec`, parse `--output-format json` | build this |
| 2 | Claude Agent SDK — programmatic sessions, same engine | only if streaming/session control is genuinely needed |
| 3 | own general agent runtime | never |

## Prerequisites

- [ ] `parts.yaml` — MPN → verified limits with page citations. Only the active
      parts need entries; nobody needs a datasheet for an 0402 resistor.
- [ ] clean MPN and datasheet fields on the board being reviewed — MPN is the
      join key, and a datasheet link inherited from a borrowed symbol may point
      at a different device entirely.
      `rpcb datasheets` now reports both gaps: parts with no MPN come back
      **unidentified**, and schematic links are listed for confirmation rather
      than trusted. It surfaces the work; filling it in is still manual.
- [x] the documents themselves, gathered before review — `rpcb datasheets`
      inventories `vendor/<part>/datasheets/` and `datasheets/`, and the agent
      prompts stop and ask for whatever is missing instead of reasoning from
      recall. This is acquisition, not citation: it makes the document present,
      it does not prove a number was read off it. The citation gate above still
      needs the referee script.
- [ ] supply-margin rules reading `parts.yaml`, so the deterministic checker
      catches rail-headroom problems with no LLM in the loop at all
