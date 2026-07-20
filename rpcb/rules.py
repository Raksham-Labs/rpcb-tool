"""Declarative rules engine.

Built-in rules ship with rpcb; project rules live in `rpcb.yaml` at the project
root and may add new rules or override/silence built-ins by reusing an `id`.

Findings are FACTS WITH EVIDENCE, never verdicts. The split matters: rule
false-positives are inevitable, and a checker that mixes them into the data
becomes untrustworthy.
"""
import os
import re

BUILTIN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'rules_builtin.yaml')

SEVERITY_ORDER = {'error': 0, 'warn': 1, 'info': 2}

# Single source of truth for what a rule may contain. `rpcb rules --kinds`
# prints this, and the README/SKILL point at that command rather than
# duplicating it, so documentation cannot drift from the implementation.
COMMON_KEYS = {
    'id': 'required. Stable identifier. Reuse a built-in id to override it.',
    'check': 'required. One of the kinds below.',
    'severity': 'error | warn | info. Default warn.',
    'why': 'shown with every finding. Say what the rule protects against.',
    'enabled': 'set false to silence a built-in entirely.',
}

CHECK_KINDS = {
    'undriven_power': {
        'does': 'Flags nets that have power_in pins but no power_out pin. '
                'A plain `input` fed by a bidirectional GPIO is NOT reported.',
        'params': {'ignore_nets': 'list of net names to skip'},
        'example': {'id': 'PWR001', 'check': 'undriven_power',
                    'severity': 'error', 'ignore_nets': ['VSYS']},
    },
    'floating_pins': {
        'does': 'Flags pins of the given types that belong to no net at all.',
        'params': {'types': 'required. list of pin types, e.g. [power_in, input]'},
        'example': {'id': 'NET004', 'check': 'floating_pins',
                    'types': ['power_in', 'input']},
    },
    'single_pin_net': {
        'does': 'Flags pins sitting alone on a net (wired to nothing). '
                'Aggregated into ONE finding grouped by component.',
        'params': {'ignore_types': 'list of pin types to skip, e.g. [no_connect]',
                   'ignore_refs_matching': 'regex of refs to skip'},
        'example': {'id': 'NET001', 'check': 'single_pin_net',
                    'ignore_types': ['no_connect'],
                    'ignore_refs_matching': '^(H|TP)\\d+$'},
    },
    'pin_type_present': {
        'does': 'Reports every pin of the given types. Use to surface ERC blind '
                'spots rather than to assert a defect.',
        'params': {'types': 'required. list of pin types'},
        'example': {'id': 'NET002', 'check': 'pin_type_present',
                    'types': ['unspecified'], 'severity': 'info'},
    },
    'needs_pullup': {
        'does': 'Flags pins of the given types whose net has no resistor leading '
                'to a power rail.',
        'params': {'types': 'required. e.g. [open_collector, open_emitter]'},
        'example': {'id': 'NET003', 'check': 'needs_pullup',
                    'types': ['open_collector']},
    },
    'decoupling': {
        'does': 'Compares capacitor count against power_in pin count on each '
                'power net. Cannot see physical proximity -- a pass means '
                '"plausible", not "verified".',
        'params': {'min_caps_per_power_pin': 'float, default 1.0',
                   'ignore_nets': 'list of net names to skip'},
        'example': {'id': 'PWR002', 'check': 'decoupling',
                    'min_caps_per_power_pin': 1.0},
    },
    'value_vs_symbol': {
        'does': 'Flags components whose Value disagrees with the schematic '
                'symbol they use. Usually a pin-compatible substitution, but a '
                'wrong symbol yields a correct-looking netlist for the wrong '
                'part.',
        'params': {'only_refs_matching': 'regex; restrict to these refs',
                   'ignore_refs_matching': 'regex of refs to skip'},
        'example': {'id': 'BOM002', 'check': 'value_vs_symbol',
                    'only_refs_matching': '^U\\d+$', 'severity': 'info'},
    },
    'required_field': {
        'does': 'Flags components missing a BOM field.',
        'params': {'field': 'required. field name, e.g. MPN',
                   'ignore_refs_matching': 'regex of refs to skip'},
        'example': {'id': 'BOM001', 'check': 'required_field', 'field': 'MPN',
                    'ignore_refs_matching': '^(H|TP|J)\\d+$'},
    },
    'net_must_contain': {
        'does': 'Asserts specific components sit on a named net. Use as a '
                'TRIPWIRE: it stays silent while correct and fires if a future '
                'edit removes the part.',
        'params': {'net': 'required. net name',
                   'must_contain': 'required. list of refs'},
        'example': {'id': 'CAN001', 'check': 'net_must_contain', 'net': 'CANH',
                    'must_contain': ['R2'], 'severity': 'error'},
    },
    'net_pin_count': {
        'does': 'Asserts a net has at least / at most N pins. Also a tripwire.',
        'params': {'net': 'required. net name',
                   'min_pins': 'integer', 'max_pins': 'integer'},
        'example': {'id': 'XTAL001', 'check': 'net_pin_count',
                    'net': 'Net-(C5-Pad1)', 'min_pins': 3},
    },
}


def render_kinds():
    """Human-readable reference for authoring rules."""
    import yaml
    out = ['rpcb rule structure', '=' * 60, '',
           'A rule is a YAML mapping. Common keys:', '']
    for key, desc in COMMON_KEYS.items():
        out.append(f'  {key:<10} {desc}')
    out += ['', 'Check kinds:', '']
    for name, spec in CHECK_KINDS.items():
        out.append(f'  {name}')
        out.append(f"    {' '.join(spec['does'].split())}")
        if spec['params']:
            out.append('    params:')
            for p, d in spec['params'].items():
                out.append(f'      {p:<24} {d}')
        snippet = yaml.safe_dump([spec['example']], sort_keys=False,
                                 default_flow_style=False).rstrip()
        out.append('    example:')
        out.extend('      ' + line for line in snippet.splitlines())
        out.append('')
    out += ['Project rules live in rpcb.yaml at the project root. The file is',
            'OPTIONAL -- built-in rules run with or without it. Create one with',
            '`rpcb init` when you want to add board-specific rules or tune a',
            'built-in.', '']
    return '\n'.join(out)


class RulesError(Exception):
    pass


def _load_yaml(path):
    try:
        import yaml
    except ImportError as exc:                            # pragma: no cover
        raise RulesError('pyyaml is required for rule checking') from exc
    with open(path, encoding='utf-8') as fh:
        return yaml.safe_load(fh) or {}


def load_rules(project=None, include_disabled=False):
    """Built-ins merged with project overrides.

    The project file is OPTIONAL -- built-ins run with or without it. Each
    returned rule carries `_source`: builtin, project, or builtin+project when a
    project entry tunes a built-in.
    """
    merged, order = {}, []
    for rule in _load_yaml(BUILTIN_PATH).get('rules', []):
        merged[rule['id']] = dict(rule, _source='builtin')
        order.append(rule['id'])

    cfg_path = project.config_path if project else None
    if cfg_path:
        for rule in (_load_yaml(cfg_path).get('rules') or []):
            rid = rule.get('id')
            if not rid:
                raise RulesError(f'a rule in {os.path.basename(cfg_path)} has no `id`')
            if rid in merged:
                merged[rid].update(rule)
                merged[rid]['_source'] = 'builtin+project'
            else:
                merged[rid] = dict(rule, _source='project')
                order.append(rid)

    out = []
    for rid in order:
        rule = merged[rid]
        disabled = rule.get('enabled') is False
        if disabled and not include_disabled:
            continue
        if 'check' not in rule:
            raise RulesError(
                f'rule {rid} has no `check` kind. Run `rpcb rules --kinds`.')
        if rule['check'] not in CHECK_KINDS:
            raise RulesError(
                f"rule {rid} uses unknown check {rule['check']!r}. "
                f'Run `rpcb rules --kinds` for the list.')
        rule.setdefault('severity', 'warn')
        if rule['severity'] not in SEVERITY_ORDER:
            raise RulesError(
                f"rule {rid} has severity {rule['severity']!r}; "
                f'expected error, warn or info.')
        out.append(rule)
    return out


# --------------------------------------------------------------------------
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
