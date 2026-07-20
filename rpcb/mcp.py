"""MCP stdio server exposing the design model.

Dependency-free: MCP over stdio is JSON-RPC 2.0, implemented directly so this
keeps working without a pip resolution step. Views are called in-process -- no
subprocess hop.

STALENESS IS THE POINT. The model is derived from the schematic. If you edit the
schematic and an agent answers from a stale model, that is worse than having no
tool. Every call re-hashes the sources and regenerates when they have changed.

Protocol note: stdout carries JSON-RPC ONLY. All logging goes to stderr.
"""
import json
import os
import sys

from . import (datasheets as datasheets_mod, extract, requirements as reqs_mod,
               rules as rules_mod, views)
from .project import ProjectError, load

SUPPORTED_PROTOCOLS = {'2024-11-05', '2025-03-26', '2025-06-18'}
DEFAULT_PROTOCOL = '2024-11-05'

TOOL_DEFS = [
    {'name': 'design_summary',
     'description': ('Overview of the KiCad design: component/net/pin counts, power '
                     'vs signal nets, ICs, pin-type histogram. Cheap (~200 tokens). '
                     'START HERE before other design tools.'),
     'inputSchema': {'type': 'object', 'properties': {}}},
    {'name': 'design_component',
     'description': ('Full pin table for one component: every pin with function, '
                     'electrical type and net, plus footprint, MPN, DNP and signal '
                     'neighbours. Use for "what is U6 wired to".'),
     'inputSchema': {'type': 'object',
                     'properties': {'ref': {'type': 'string',
                                            'description': 'e.g. U6'}},
                     'required': ['ref']}},
    {'name': 'design_net',
     'description': ('Every pin on a net with each pin\'s function, electrical type '
                     'and component value. Use for "what is on +3.3V".'),
     'inputSchema': {'type': 'object',
                     'properties': {'name': {'type': 'string',
                                             'description': 'e.g. +3.3V or CANH'}},
                     'required': ['name']}},
    {'name': 'design_pin',
     'description': ('What a single pin connects to. Cheapest connectivity query '
                     '(~50 tokens). Use for "what is U2 pin 45 on".'),
     'inputSchema': {'type': 'object',
                     'properties': {'pin': {'type': 'string',
                                            'description': 'REF.PIN, e.g. U2.45'}},
                     'required': ['pin']}},
    {'name': 'design_trace',
     'description': ('Walk outward from a pin through nets and series passives. '
                     'Stops at power rails and will not expand through ICs larger '
                     'than max_expand_pins, so it stays readable.'),
     'inputSchema': {'type': 'object',
                     'properties': {
                         'pin': {'type': 'string', 'description': 'REF.PIN'},
                         'hops': {'type': 'integer', 'description': 'default 3'},
                         'through_power': {'type': 'boolean'},
                         'max_expand_pins': {'type': 'integer',
                                             'description': 'default 3'}},
                     'required': ['pin']}},
    {'name': 'design_find',
     'description': ('Regex search across component refs, values, MPNs, part names, '
                     'net names and design notes.'),
     'inputSchema': {'type': 'object',
                     'properties': {'pattern': {'type': 'string'}},
                     'required': ['pattern']}},
    {'name': 'design_notes',
     'description': ('Designer annotations from the schematic (stated intent) with '
                     'nearby components. Check findings against these BEFORE '
                     'reporting them -- a finding that contradicts a note usually '
                     'means the design was misread.'),
     'inputSchema': {'type': 'object', 'properties': {}}},
    {'name': 'design_check',
     'description': ('Run the rule set and return findings with evidence. Findings '
                     'are prompts to look, NOT proof of defects -- verify each '
                     'against the datasheet before reporting it as a problem.'),
     'inputSchema': {'type': 'object',
                     'properties': {'severity': {'type': 'string',
                                                 'enum': ['error', 'warn', 'info']}}}},
    {'name': 'design_requirements',
     'description': ('Plain-English requirements this project has declared in '
                     'rpcb.yaml. No rule evaluates these -- they are judgement, and '
                     'you are the one answering them. A review MUST return an '
                     'explicit verdict for EVERY requirement in a table, with '
                     'evidence, and must never silently omit one.'),
     'inputSchema': {'type': 'object', 'properties': {}}},
    {'name': 'design_datasheets',
     'description': ('Which parts need a datasheet, the canonical path each document '
                     'belongs at, and which files are unfiled. RUN THIS BEFORE '
                     'asserting any electrical limit. It reports paths only and does '
                     'NOT look inside any file -- open each PDF yourself to confirm '
                     'it names the right device, move or rename it to the canonical '
                     'path, fetch what is absent, and ask the user for the rest '
                     'before reviewing. Also lists BOM gaps to report back.'),
     'inputSchema': {'type': 'object', 'properties': {}}},
    {'name': 'design_full_text',
     'description': ('The ENTIRE design as compact text: notes, component table, '
                     'every pin of every component, and all nets (~6k tokens). Use '
                     'for a full review; prefer targeted tools for single questions.'),
     'inputSchema': {'type': 'object',
                     'properties': {'include_unconnected': {'type': 'boolean'}}}},
]


def log(msg):
    print(f'[rpcb-mcp] {msg}', file=sys.stderr, flush=True)


def _model(project):
    note = extract.ensure_fresh(project, verbose=True)
    with open(project.model_path, encoding='utf-8') as fh:
        return json.load(fh), note


def dispatch(name, args):
    project = load()
    model, note = _model(project)
    banner = f'[model regenerated: {note}]\n' if note else ''

    if name == 'design_summary':
        return banner + views.summary(model)
    if name == 'design_component':
        return banner + views.component(model, str(args['ref']))
    if name == 'design_net':
        return banner + views.net(model, str(args['name']))
    if name == 'design_pin':
        return banner + views.pin(model, str(args['pin']))
    if name == 'design_trace':
        return banner + views.trace(
            model, str(args['pin']), hops=int(args.get('hops') or 3),
            through_power=bool(args.get('through_power')),
            max_expand_pins=int(args.get('max_expand_pins') or 3))
    if name == 'design_find':
        return banner + views.find(model, str(args['pattern']))
    if name == 'design_notes':
        return banner + views.notes(model)
    if name == 'design_check':
        findings = rules_mod.run(model, rules_mod.load_rules(project))
        sev = args.get('severity')
        if sev:
            findings = [f for f in findings if f['severity'] == sev]
        return banner + rules_mod.render(findings)
    if name == 'design_requirements':
        cfg = (os.path.basename(project.config_path)
               if project.config_path else None)
        return banner + reqs_mod.render(reqs_mod.load(project), cfg)
    if name == 'design_datasheets':
        return banner + datasheets_mod.render(
            datasheets_mod.inventory(model, project.root))
    if name == 'design_full_text':
        return banner + views.full_text(
            model, include_unconnected=bool(args.get('include_unconnected')))
    raise KeyError(name)


def handle(msg):
    method, mid = msg.get('method'), msg.get('id')

    if method == 'initialize':
        want = (msg.get('params') or {}).get('protocolVersion')
        version = want if want in SUPPORTED_PROTOCOLS else DEFAULT_PROTOCOL
        return {'jsonrpc': '2.0', 'id': mid, 'result': {
            'protocolVersion': version,
            'capabilities': {'tools': {}},
            'serverInfo': {'name': 'rpcb', 'version': '1.0.0'}}}

    if method in ('notifications/initialized', 'initialized'):
        return None

    if method == 'ping':
        return {'jsonrpc': '2.0', 'id': mid, 'result': {}}

    if method == 'tools/list':
        return {'jsonrpc': '2.0', 'id': mid, 'result': {'tools': TOOL_DEFS}}

    if method == 'tools/call':
        params = msg.get('params') or {}
        name = params.get('name', '')
        args = params.get('arguments') or {}
        try:
            text = dispatch(name, args)
        except ProjectError as exc:
            # The server is registered globally, so it gets started in
            # directories that are not KiCad projects. Say so plainly.
            text = f'No KiCad project here: {exc}'
        except KeyError:
            text = f'unknown tool {name!r}'
        except Exception as exc:                              # noqa: BLE001
            text = f'{type(exc).__name__}: {exc}'
        return {'jsonrpc': '2.0', 'id': mid,
                'result': {'content': [{'type': 'text', 'text': text}]}}

    if mid is None:
        return None
    return {'jsonrpc': '2.0', 'id': mid,
            'error': {'code': -32601, 'message': f'method not found: {method}'}}


def serve():
    try:
        proj = load()
        log(f'serving {proj.name} at {proj.root}')
    except ProjectError:
        log('started outside a KiCad project; tools will report that')
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        reply = handle(msg)
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + '\n')
            sys.stdout.flush()
    return 0
