"""What a rule may contain, and how to explain it.

Single source of truth: `rpcb rules --kinds` renders this, and the README and
SKILL point at that command rather than restating it, so documentation cannot
drift from what the engine accepts.
"""

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
