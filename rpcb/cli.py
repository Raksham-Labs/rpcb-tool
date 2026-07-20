#!/usr/bin/env python3
"""rpcb — feed KiCad schematics to LLMs.

    rpcb summary                  overview
    rpcb check                    run rules
    rpcb pin U2.45                what a pin connects to
    rpcb review                   launch Claude with the design preloaded
    rpcb review --codex           same, with Codex
    rpcb mcp                      MCP stdio server
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

from . import (datasheets as datasheets_mod, extract, requirements as reqs_mod,
               rules as rules_mod, views)
from .project import ProjectError, load

VERSION = '1.1.0'
_HERE = os.path.dirname(os.path.abspath(__file__))
PROMPT_PATH = os.path.join(_HERE, 'review_prompt.md')
INIT_PROMPT_PATH = os.path.join(_HERE, 'init_prompt.md')

# A review now files datasheets: it opens PDFs, fetches what is absent and moves
# documents to their canonical path, so read-only rpcb access is not enough.
REVIEW_TOOLS = ('Bash(rpcb:*) Bash(mkdir:*) Bash(mv:*) Bash(curl:*) '
                'Read Write WebFetch WebSearch')
# Writing rules needs the design and the file being authored, nothing external.
INIT_TOOLS = 'Bash(rpcb:*) Read Write Edit'


def die(msg, code=2):
    print(f'rpcb: {msg}', file=sys.stderr)
    return code


def get_model(args):
    """Load the project model, regenerating if the schematic changed."""
    project = load(getattr(args, 'path', None))
    extract.ensure_fresh(project, verbose=True)
    with open(project.model_path, encoding='utf-8') as fh:
        return project, json.load(fh)


def out(text, as_json, payload=None):
    if as_json and payload is not None:
        print(json.dumps(payload, indent=1, ensure_ascii=False))
    else:
        print(text)
    return 0


# --------------------------------------------------------------------------
def cmd_extract(args):
    project = load(args.path)
    model = extract.extract(project, regenerate_netlist=not args.no_netlist)
    path = extract.write(project, model)
    s = model['stats']
    print(f'wrote {os.path.relpath(path, project.root)} '
          f'({os.path.getsize(path):,} bytes)')
    print(f"  {s['components']} components ({s['components_dnp']} DNP) · "
          f"{s['nets']} nets · {s['pin_nodes']} pin-nodes · "
          f"{s['notes']} notes · sheets {s['sheets']}")
    print(f"  sheets scanned: "
          f"{[os.path.basename(p) for p in project.schematics]}")
    return 0


def cmd_summary(args):
    _p, m = get_model(args)
    return out(views.summary(m), args.json, m['stats'])


def cmd_component(args):
    _p, m = get_model(args)
    return out(views.component(m, args.ref), args.json,
               m['components'].get(args.ref))


def cmd_net(args):
    _p, m = get_model(args)
    return out(views.net(m, args.name), args.json, m['nets'].get(args.name))


def cmd_pin(args):
    _p, m = get_model(args)
    return out(views.pin(m, args.pin), args.json,
               {'pin': args.pin, 'net': m['graph']['pin_to_net'].get(args.pin)})


def cmd_trace(args):
    _p, m = get_model(args)
    return out(views.trace(m, args.pin, hops=args.hops,
                           through_power=args.through_power,
                           max_expand_pins=args.max_expand_pins), False)


def cmd_find(args):
    _p, m = get_model(args)
    return out(views.find(m, args.pattern), False)


def cmd_notes(args):
    _p, m = get_model(args)
    return out(views.notes(m), args.json, m['notes'])


def cmd_text(args):
    _p, m = get_model(args)
    text = views.full_text(m, include_unconnected=args.include_unconnected)
    print(text)
    print(f'\n[[ {len(text):,} bytes  ~{len(text)//4:,} tokens ]]', file=sys.stderr)
    return 0


def cmd_check(args):
    project, m = get_model(args)
    findings = rules_mod.run(m, rules_mod.load_rules(project))
    if args.severity:
        findings = [f for f in findings if f['severity'] == args.severity]
    if args.json:
        print(json.dumps(findings, indent=1, ensure_ascii=False))
    else:
        print(rules_mod.render(findings))
        # Pointer, not a finding. Requirements are judgement; folding prose into
        # deterministic output is exactly the mixing this tool avoids. But an
        # unmentioned requirement is one nobody answers, so say it exists.
        pending = reqs_mod.load(project)
        if pending:
            print(f'\n{len(pending)} project requirement(s) need a reviewer\'s '
                  'verdict — see `rpcb requirements`. No rule evaluates them.')
    if args.strict and any(f['severity'] == 'error' for f in findings):
        return 1
    return 0


def cmd_requirements(args):
    project = load(getattr(args, 'path', None))
    reqs = reqs_mod.load(project)
    name = os.path.basename(project.config_path) if project.config_path else None
    return out(reqs_mod.render(reqs, name), args.json, reqs)


def cmd_datasheets(args):
    """Inventory the documents a review needs before it can verify any limit.

    Exits non-zero while any are absent or any file is unfiled: this is a gate,
    and a gate that always returns 0 is a suggestion. Unidentified parts do not
    hold it shut -- their gap is the BOM, not a missing document.
    """
    project, m = get_model(args)
    inv = datasheets_mod.inventory(m, project.root)
    out(datasheets_mod.render(inv), args.json, inv)
    blocked = inv['absent'] or inv['unfiled']
    return 1 if blocked and not args.quiet else 0


def cmd_dump(args):
    _p, m = get_model(args)
    section = m if args.section == 'all' else m.get(args.section)
    if section is None:
        return die(f'no section {args.section!r}; have: {list(m)}')
    print(json.dumps(section, indent=1, ensure_ascii=False))
    return 0


def cmd_mcp(_args):
    from . import mcp
    return mcp.serve()


def _launch_agent(project, prompt_path, task, tools, args):
    """Hand an agent a session preloaded with the design and one instruction set.

    Extracting BEFORE launching means the agent physically cannot read a stale
    model -- no in-session staleness guard required on this path.
    """
    try:
        extract.ensure_fresh(project, verbose=True)
    except extract.ExtractError as exc:
        return die(str(exc))

    with open(prompt_path, encoding='utf-8') as fh:
        instructions = fh.read()

    context = [f'Project: {project.name}  ({project.root})']
    if project.config_path:
        context.append(f'Project rules: {os.path.basename(project.config_path)}')
    system_prompt = instructions + '\n\n## This session\n\n' + '\n'.join(context) + '\n'

    agent = 'codex' if args.codex else 'claude'
    exe = shutil.which(agent)
    if not exe:
        return die(f'{agent} not found on PATH')

    if args.codex:
        # Codex has no append-system-prompt flag; fold the instructions into
        # the prompt itself.
        cmd = [exe]
        if args.print:
            cmd.append('exec')
        cmd.append(system_prompt + '\n---\n\n' + task)
    else:
        cmd = [exe, '--append-system-prompt', system_prompt,
               '--allowedTools', tools]
        if args.print:
            cmd.append('-p')
        cmd.append(task)

    if args.dry_run:
        print(f'would run: {agent}')
        print(f'  cwd: {project.root}')
        print(f'  system prompt: {len(system_prompt):,} chars')
        print(f'  tools: {tools if not args.codex else "(codex default)"}')
        print(f'  task: {task}')
        return 0

    return subprocess.call(cmd, cwd=project.root)


def cmd_review(args):
    task = args.task or (
        'Review this board\'s schematic for real design problems. '
        'Gather datasheets first, as the instructions require. '
        'Follow the method and reporting rules above.')
    return _launch_agent(load(args.path), PROMPT_PATH, task, REVIEW_TOOLS, args)


def cmd_init(args):
    project = load(args.path)
    path = os.path.join(project.root, 'rpcb.yaml')
    if os.path.exists(path) and not args.force:
        return die(f'{os.path.basename(path)} already exists (use --force)')

    if args.agent or args.codex:
        # The scaffold is a blank form; this reads the board and fills it in.
        # Writing nothing is a valid outcome and the prompt says so -- a file of
        # rules that can never fire is worse than no file, because the next
        # reader believes the board is covered.
        task = ('Study this board and write rpcb.yaml with rules that assert what '
                'is true of it. Follow the method above. If nothing is worth '
                'asserting, write no file and say why.')
        return _launch_agent(project, INIT_PROMPT_PATH, task, INIT_TOOLS, args)

    if args.dry_run:
        print(f'would write {os.path.relpath(path, project.root)} (scaffold)')
        print(f'project: {project.name}')
        return 0

    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(f"""# rpcb rules for {project.name}
#
# THIS FILE IS OPTIONAL. rpcb's built-in rules run with or without it -- delete
# it any time and `rpcb check` still works. It exists for two things:
#
#   1. TRIPWIRES — assert something true of THIS board. A tripwire stays silent
#      while correct and fires if a later edit breaks it. This is the main
#      reason to keep the file.
#
#   2. TUNING — override or silence a built-in by reusing its id.
#
# Every ignore is a place a real problem can hide, so prefer tripwires over
# silencing, and only silence a finding you have actually investigated.
#
#   `rpcb rules`          what is active right now
#   `rpcb rules --kinds`  every check kind, its parameters, and an example
#
# Findings are prompts to look, not verdicts.

rules: []

# --- tripwire example: fires only if someone removes the termination ---
#  - id: CAN001
#    severity: error
#    check: net_must_contain
#    net: CANH
#    must_contain: [R2]
#    why: CAN needs termination; 120R belongs only at physical bus ends.

# --- tuning example: silence a built-in you have investigated ---
#  - id: PWR001
#    ignore_nets: [VSYS]        # fed from a connector, not an on-board regulator


# REQUIREMENTS — plain English, for what no rule can evaluate.
#
#   rules:         mechanical, evaluated by the engine, same answer every run
#   requirements:  prose, evaluated by a reviewer, answered with evidence
#
# A review must return an explicit verdict for EVERY requirement in a table --
# MET, NOT MET, AT RISK or UNVERIFIABLE -- and may never silently skip one. Use
# these for intent a check kind cannot express. Do not use them for datasheet
# limits; those belong in a review with the document open.
#
#   `rpcb requirements`   what is declared, and the verdicts expected

requirements: []

#  - id: REQ001
#    severity: error
#    must: >
#      The MCU must be able to put the CAN transceiver into silent mode.
#    why: >
#      Field units share the bus with a diagnostic tool; a stuck transmitter
#      takes the whole bus down and cannot be isolated in the field.
#    refs: [U2, U6]             # optional: where to start looking
#    nets: [CANH, CANL]         # optional
""")
    print(f'wrote {os.path.relpath(path, project.root)}  (optional — built-in '
          f'rules run without it)')
    print(f'project: {project.name}')
    print(f"sheets : {[os.path.basename(p) for p in project.schematics]}")
    print('next   : rpcb rules --kinds   (or `rpcb init --agent` to have an '
          'agent write real rules)')
    return 0


def cmd_rules(args):
    if args.kinds:
        print(rules_mod.render_kinds())
        return 0

    project = None
    try:
        project = load(args.path)
    except ProjectError:
        pass

    active = rules_mod.load_rules(project, include_disabled=True)
    cfg = project.config_path if project else None
    print(f"project rules: {os.path.basename(cfg) if cfg else 'none (optional)'}")
    print()
    print(f"{'id':<10}{'severity':<10}{'check':<20}{'source':<18}status")
    for rule in active:
        status = 'disabled' if rule.get('enabled') is False else 'active'
        print(f"{rule['id']:<10}{rule['severity']:<10}{rule['check']:<20}"
              f"{rule['_source']:<18}{status}")
    print()
    print('`rpcb rules --kinds` documents how to write one.')
    if not cfg:
        print('`rpcb init` creates an optional rpcb.yaml for board-specific rules.')
    return 0


# --------------------------------------------------------------------------
def build_parser():
    ap = argparse.ArgumentParser(
        prog='rpcb', description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--version', action='version', version=f'rpcb {VERSION}')
    ap.add_argument('--path', help='project directory (default: cwd)')
    ap.add_argument('--json', action='store_true', help='machine-readable output')
    sp = ap.add_subparsers(dest='cmd')

    sp.add_parser('summary', help='design overview')

    p = sp.add_parser('component', help='pins of one component')
    p.add_argument('ref')

    p = sp.add_parser('net', help='pins on one net')
    p.add_argument('name')

    p = sp.add_parser('pin', help='what a pin connects to')
    p.add_argument('pin')

    p = sp.add_parser('trace', help='walk outward from a pin')
    p.add_argument('pin')
    p.add_argument('--hops', type=int, default=3)
    p.add_argument('--through-power', action='store_true')
    p.add_argument('--max-expand-pins', type=int, default=3,
                   help='only continue through components with <= N pins')

    p = sp.add_parser('find', help='regex search')
    p.add_argument('pattern')

    sp.add_parser('notes', help='designer annotations')

    p = sp.add_parser('text', help='entire design, compact')
    p.add_argument('--include-unconnected', action='store_true')

    p = sp.add_parser('check', help='run rules')
    p.add_argument('--severity', choices=['error', 'warn', 'info'])
    p.add_argument('--strict', action='store_true',
                   help='exit 1 if any error-severity finding')

    sp.add_parser('requirements',
                  help='plain-English requirements a reviewer must answer')

    p = sp.add_parser('datasheets', help='which parts need a datasheet, and which are here')
    p.add_argument('--quiet', action='store_true',
                   help='inventory only; do not exit 1 when any are missing')

    p = sp.add_parser('dump', help='raw JSON section')
    p.add_argument('section', nargs='?', default='all')

    p = sp.add_parser('extract', help='rebuild the model')
    p.add_argument('--no-netlist', action='store_true',
                   help='reuse the existing netlist export')

    p = sp.add_parser('review', help='launch an agent with the design preloaded')
    p.add_argument('task', nargs='?', help='what to review (optional)')
    p.add_argument('--codex', action='store_true', help='use Codex instead of Claude')
    p.add_argument('-p', '--print', action='store_true', help='headless')
    p.add_argument('--dry-run', action='store_true')

    p = sp.add_parser('init', help='write rpcb.yaml for this project')
    p.add_argument('--force', action='store_true')
    p.add_argument('--agent', action='store_true',
                   help='have an agent study the board and write real rules, '
                        'instead of writing a blank scaffold')
    p.add_argument('--codex', action='store_true',
                   help='use Codex instead of Claude (implies --agent)')
    p.add_argument('-p', '--print', action='store_true', help='headless')
    p.add_argument('--dry-run', action='store_true')

    p = sp.add_parser('rules', help='list active rules')
    p.add_argument('--kinds', action='store_true',
                   help='document how to write a rule')
    sp.add_parser('mcp', help='run the MCP stdio server')

    return ap


HANDLERS = {
    'summary': cmd_summary, 'component': cmd_component, 'net': cmd_net,
    'pin': cmd_pin, 'trace': cmd_trace, 'find': cmd_find, 'notes': cmd_notes,
    'text': cmd_text, 'check': cmd_check, 'dump': cmd_dump,
    'datasheets': cmd_datasheets, 'requirements': cmd_requirements,
    'extract': cmd_extract, 'review': cmd_review, 'init': cmd_init,
    'rules': cmd_rules, 'mcp': cmd_mcp,
}


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_help()
        return 0
    try:
        return HANDLERS[args.cmd](args)
    except ProjectError as exc:
        return die(str(exc))
    except (extract.ExtractError, rules_mod.RulesError,
            reqs_mod.RequirementsError) as exc:
        return die(str(exc))
    except views.NotFound as exc:
        return die(str(exc))
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
