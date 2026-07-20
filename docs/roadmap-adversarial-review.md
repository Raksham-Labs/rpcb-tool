# Roadmap: adversarial review (`rpcb duel`)

Design agreed but **not built**. Depends on `parts.yaml` existing first — the
citation gate below is the whole point, and it cannot work without it.

## Why

Two agents agreeing is **not** evidence of correctness. They can share the same
wrong recollection of a spec and reinforce it into false confidence — worse than
one agent, because agreement reads as verification.

Live example from the first review of FlowLiteV2: the top-ranked finding (CAN
transceiver undervolted) rests on "MCP2562FD minimum VDD = 4.5V", asserted from
model memory and never checked against the datasheet. If a second model recalls
the same number, nothing has been verified.

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

- [ ] `parts.yaml` — MPN → verified limits with page citations (~11 parts matter)
- [ ] fix `U1` MPN (`MIC5219-3` is truncated) and `U3` datasheet URL (points at
      VL53L1X; board uses VL53L4CX) — these are the join keys
- [ ] supply-margin rules reading `parts.yaml`, so the deterministic checker
      catches the CAN rail case with no LLM at all
