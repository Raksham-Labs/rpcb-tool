"""Evaluate rules against the design model.

Findings are FACTS WITH EVIDENCE, never verdicts. Rule false-positives are
inevitable; a checker that mixes them into the data becomes untrustworthy.
"""
import re

from .spec import SEVERITY_ORDER


def _caps_on(m, net):
    out = []
    for n in net['nodes']:
        comp = m['components'].get(n['ref'], {})
        if comp.get('libpart', '').startswith('Device:C') or n['ref'].startswith('C'):
            out.append(n['ref'])
    return out


def _pull_resistor(m, net_name, ref):
    """A resistor on `net_name` whose other pin sits on a power rail."""
    if not ref.startswith('R'):
        return None
    comp = m['components'].get(ref, {})
    for _num, p in comp.get('pins', {}).items():
        if p['net'] and p['net'] != net_name:
            if m['nets'].get(p['net'], {}).get('is_power'):
                return f"{ref} -> {p['net']}"
    return None


def _norm(s):
    return re.sub(r'[^a-z0-9]', '', s.lower())


def run(m, rules):
    findings = []

    def add(rule, title, evidence):
        findings.append({
            'id': rule['id'], 'severity': rule['severity'], 'check': rule['check'],
            'title': title, 'evidence': evidence,
            'why': ' '.join((rule.get('why') or '').split()),
        })

    for rule in rules:
        kind = rule['check']
        ignore_nets = set(rule.get('ignore_nets') or [])
        ig_ref = re.compile(rule['ignore_refs_matching']) \
            if rule.get('ignore_refs_matching') else None
        only_ref = re.compile(rule['only_refs_matching']) \
            if rule.get('only_refs_matching') else None

        if kind == 'undriven_power':
            # Only power_in matters. A plain `input` fed by a bidirectional MCU
            # GPIO is normal and must not be reported as an unpowered rail.
            for name, net in m['nets'].items():
                if name in ignore_nets:
                    continue
                sinks = [f"{n['ref']}.{n['pin']}" for n in net['nodes']
                         if n['type'] == 'power_in']
                supplies = [f"{n['ref']}.{n['pin']}" for n in net['nodes']
                            if n['type'] == 'power_out']
                if sinks and not supplies:
                    add(rule, f'power net {name}: {len(sinks)} power_in pins, '
                              f'no power_out source',
                        {'net': name, 'power_in_pins': sinks,
                         'pin_types_present': sorted({n['type'] for n in net['nodes']})})

        elif kind == 'floating_pins':
            want = set(rule.get('types') or [])
            for ref, c in m['components'].items():
                for num, p in c['pins'].items():
                    if p['net'] is None and p['type'] in want:
                        add(rule, f"{ref}.{num} ({p['function']}, {p['type']}) "
                                  f'is not connected to any net',
                            {'ref': ref, 'pin': num, 'type': p['type']})

        elif kind == 'single_pin_net':
            # Aggregated: separate warnings for every spare MCU pin bury
            # everything else.
            ig_types = set(rule.get('ignore_types') or [])
            unwired = []
            for name, net in m['nets'].items():
                if net['pin_count'] != 1:
                    continue
                nd = net['nodes'][0]
                if nd['type'] in ig_types or (ig_ref and ig_ref.match(nd['ref'])):
                    continue
                unwired.append(f"{nd['ref']}.{nd['pin']}({nd['function']})")
            if unwired:
                by_ref = {}
                for u in unwired:
                    by_ref.setdefault(u.split('.')[0], []).append(u)
                add(rule, f'{len(unwired)} pins are on single-pin nets (unwired) '
                          f'across {len(by_ref)} components',
                    {'by_component': {k: sorted(v) for k, v in sorted(by_ref.items())}})

        elif kind == 'pin_type_present':
            want = set(rule.get('types') or [])
            hits = [{'pin': f"{n['ref']}.{n['pin']}", 'function': n['function'],
                     'net': name}
                    for name, net in m['nets'].items() for n in net['nodes']
                    if n['type'] in want]
            if hits:
                add(rule, f'{len(hits)} pins typed {sorted(want)} (invisible to ERC)',
                    {'pins': hits})

        elif kind == 'needs_pullup':
            want = set(rule.get('types') or [])
            for name, net in m['nets'].items():
                for n in net['nodes']:
                    if n['type'] not in want:
                        continue
                    pulls = [p for p in (_pull_resistor(m, name, o['ref'])
                                         for o in net['nodes']) if p]
                    if not pulls:
                        add(rule, f"{n['ref']}.{n['pin']} ({n['function']}, "
                                  f'{n["type"]}) on {name} has no pull resistor',
                            {'net': name, 'pin': f"{n['ref']}.{n['pin']}",
                             'net_members': [f"{x['ref']}.{x['pin']}"
                                             for x in net['nodes']]})

        elif kind == 'decoupling':
            ratio = float(rule.get('min_caps_per_power_pin', 1.0))
            for name, net in m['nets'].items():
                if not net['is_power'] or name in ignore_nets:
                    continue
                sinks = [n for n in net['nodes'] if n['type'] == 'power_in']
                if not sinks:
                    continue
                caps = _caps_on(m, net)
                if len(caps) < ratio * len(sinks):
                    add(rule, f'net {name}: {len(caps)} caps for {len(sinks)} '
                              f'power_in pins (want >= {ratio:g} per pin)',
                        {'net': name, 'caps': sorted(caps),
                         'power_in_pins': [f"{n['ref']}.{n['pin']}" for n in sinks]})

        elif kind == 'value_vs_symbol':
            for ref, c in m['components'].items():
                if only_ref and not only_ref.match(ref):
                    continue
                part = c['libpart'].split(':')[-1]
                val = c['value']
                if not part or not val:
                    continue
                if _norm(part)[:6] and _norm(part)[:6] not in _norm(val) \
                        and _norm(val)[:6] not in _norm(part):
                    add(rule, f'{ref}: Value {val!r} vs symbol {part!r}',
                        {'ref': ref, 'value': val, 'symbol': part,
                         'mpn': c.get('mpn', ''), 'footprint': c['footprint']})

        elif kind == 'required_field':
            field = rule['field']
            missing = [r for r, c in m['components'].items()
                       if not c.get('fields', {}).get(field)
                       and not (ig_ref and ig_ref.match(r))]
            if missing:
                add(rule, f'{len(missing)} components have no {field}',
                    {'field': field, 'refs': sorted(missing)})

        elif kind == 'net_must_contain':
            name = rule['net']
            net = m['nets'].get(name)
            if net is None:
                add(rule, f'net {name} does not exist', {'net': name})
                continue
            present = {n['ref'] for n in net['nodes']}
            missing = [r for r in (rule.get('must_contain') or []) if r not in present]
            if missing:
                add(rule, f'net {name} is missing {missing}',
                    {'net': name, 'missing': missing, 'present': sorted(present)})

        elif kind == 'net_pin_count':
            name = rule['net']
            net = m['nets'].get(name)
            if net is None:
                add(rule, f'net {name} does not exist', {'net': name})
                continue
            if 'min_pins' in rule and net['pin_count'] < rule['min_pins']:
                add(rule, f'net {name} has {net["pin_count"]} pins, '
                          f'expected >= {rule["min_pins"]}', {'net': name})
            if 'max_pins' in rule and net['pin_count'] > rule['max_pins']:
                add(rule, f'net {name} has {net["pin_count"]} pins, '
                          f'expected <= {rule["max_pins"]}', {'net': name})

        else:
            findings.append({'id': rule['id'], 'severity': 'info', 'check': kind,
                             'title': f'unknown check kind {kind!r}',
                             'evidence': {}, 'why': ''})

    findings.sort(key=lambda f: (SEVERITY_ORDER.get(f['severity'], 3), f['id']))
    return findings


def render(findings):
    if not findings:
        return '0 findings — nothing to look at.'
    counts = {}
    for f in findings:
        counts[f['severity']] = counts.get(f['severity'], 0) + 1
    out = [f'{len(findings)} findings  '
           + '  '.join(f'{k}={v}' for k, v in sorted(counts.items())),
           '(findings are prompts to look, not proof of defects)', '']
    for f in findings:
        out.append(f"[{f['severity'].upper():5}] {f['id']}  {f['title']}")
        for k, v in f['evidence'].items():
            if isinstance(v, list) and len(v) > 8:
                v = v[:8] + [f'... +{len(v) - 8} more']
            out.append(f'          {k}: {v}')
        if f['why']:
            out.append(f"          why: {f['why']}")
        out.append('')
    return '\n'.join(out)
