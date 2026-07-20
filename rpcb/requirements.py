"""Plain-English requirements a reviewer must answer explicitly.

A `check:` rule is mechanical: the engine evaluates it and the answer is the
same every run. Plenty of what matters about a board is not like that. "The MCU
must be able to put the CAN transceiver in silent mode" is checkable, but only
by someone reading the design -- there is no check kind for it, and inventing
one that pattern-matched net names would be a rule that fires on the name rather
than the intent.

So these live in `requirements:`, deliberately apart from `rules:`:

    rules:         mechanical, evaluated by the engine, same answer every run
    requirements:  prose, evaluated by a reviewer, answered with evidence

This module does not evaluate anything -- it cannot. It loads them, validates
their shape, and hands them to the reviewer, which is required to return a
verdict for every one. The value is that nothing is silently skipped: a
requirement with no answer is visible as a gap in the table rather than absent
from a report that otherwise looks complete.

Format in rpcb.yaml:

    requirements:
      - id: REQ001
        must: >
          The MCU must be able to put the CAN transceiver into silent mode.
        why: >                       # optional, shown with the verdict
          Field units share the bus with a diagnostic tool; a stuck
          transmitter takes the whole bus down.
        severity: error              # optional: error | warn | info
        refs: [U2, U6]               # optional: where to start looking
        nets: [CANH, CANL]           # optional
"""
import os

from .rules.spec import SEVERITY_ORDER

VERDICTS = ('MET', 'NOT MET', 'AT RISK', 'UNVERIFIABLE')


class RequirementsError(Exception):
    """rpcb.yaml has a malformed `requirements:` block."""


def _load_yaml(path):
    try:
        import yaml
    except ImportError as exc:                            # pragma: no cover
        raise RequirementsError('pyyaml is required to read requirements') from exc
    with open(path, encoding='utf-8') as fh:
        return yaml.safe_load(fh) or {}


def load(project=None):
    """Requirements from the project's optional rpcb.yaml.

    Absent file, absent key and empty list are all simply "none" -- a board
    needs no requirements to be reviewable, exactly as it needs no rules.
    """
    cfg_path = project.config_path if project else None
    if not cfg_path:
        return []
    raw = _load_yaml(cfg_path).get('requirements')
    if raw is None:
        return []
    name = os.path.basename(cfg_path)
    if not isinstance(raw, list):
        raise RequirementsError(f'`requirements:` in {name} must be a list')

    out, seen = [], set()
    for index, item in enumerate(raw, 1):
        where = f'requirement #{index} in {name}'
        if not isinstance(item, dict):
            raise RequirementsError(f'{where} must be a mapping with `id` and `must`')
        rid = item.get('id')
        if not rid:
            raise RequirementsError(f'{where} has no `id`')
        if rid in seen:
            raise RequirementsError(f'duplicate requirement id {rid!r} in {name}')
        seen.add(rid)

        must = (item.get('must') or '').strip()
        if not must:
            # Without an assertion there is nothing to return a verdict on. A
            # bare topic ("check the CAN bus") cannot be answered met or not.
            raise RequirementsError(
                f'requirement {rid} has no `must`. State it as an assertion the '
                'board either satisfies or does not, e.g. '
                'must: "Every CAN transceiver can be put in silent mode by the MCU."')

        severity = item.get('severity', 'warn')
        if severity not in SEVERITY_ORDER:
            raise RequirementsError(
                f'requirement {rid} has severity {severity!r}; '
                'expected error, warn or info.')

        out.append({
            'id': rid,
            'must': must,
            'why': (item.get('why') or '').strip(),
            'severity': severity,
            'refs': list(item.get('refs') or []),
            'nets': list(item.get('nets') or []),
        })
    return out


def render(reqs, config_name=None):
    if not reqs:
        return ('no project requirements.\n\n'
                'Add a `requirements:` list to rpcb.yaml for things a reviewer must '
                'judge but no rule can evaluate. See `rpcb rules --kinds` for what '
                'belongs in `rules:` instead.')

    out = []
    w = out.append
    w(f"{len(reqs)} requirement(s)"
      + (f' from {config_name}' if config_name else ''))
    w('')
    w('Each needs an explicit verdict in the review, with evidence:')
    w(f"  {'  '.join(VERDICTS)}")
    for r in reqs:
        w('')
        w(f"{r['id']}  [{r['severity']}]")
        w(f"  must: {r['must']}")
        if r['why']:
            w(f"  why : {r['why']}")
        if r['refs']:
            w(f"  refs: {' '.join(str(x) for x in r['refs'])}")
        if r['nets']:
            w(f"  nets: {' '.join(str(x) for x in r['nets'])}")
    w('')
    w('These are judgement, not mechanics. No rule evaluates them and none is')
    w('marked met until a reviewer says so with evidence.')
    return '\n'.join(out)
