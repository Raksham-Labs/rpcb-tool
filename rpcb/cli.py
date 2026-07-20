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

from . import extract, rules as rules_mod, views
from .project import ProjectError, load

VERSION = '1.0.0'
PROMPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'review_prompt.md')


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
    if args.strict and any(f['severity'] == 'error' for f in findings):
        return 1
    return 0


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


def cmd_review(args):
    """Regenerate the model, then hand the agent a preloaded session.

    Extracting BEFORE launching means the agent physically cannot read a stale
    model -- no in-session staleness guard required on this path.
    """
    project = load(args.path)
    try:
        extract.ensure_fresh(project, verbose=True)
    except extract.ExtractError as exc:
        return die(str(exc))

    with open(PROMPT_PATH, encoding='utf-8') as fh:
        instructions = fh.read()

    context = [f'Project: {project.name}  ({project.root})']
    if project.config_path:
        context.append(f'Project rules: {os.path.basename(project.config_path)}')
    system_prompt = instructions + '\n\n## This session\n\n' + '\n'.join(context) + '\n'

    task = args.task or (
        'Review this board\'s schematic for real design problems. '
        'Follow the method and reporting rules above.')

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
               '--allowedTools', 'Bash(rpcb:*)']
        if args.print:
            cmd.append('-p')
        cmd.append(task)

    if args.dry_run:
        print(f'would run: {agent}')
        print(f'  cwd: {project.root}')
        print(f'  system prompt: {len(system_prompt):,} chars')
        print(f'  task: {task}')
        return 0

    return subprocess.call(cmd, cwd=project.root)


def cmd_init(args):
    project = load(args.path)
    path = os.path.join(project.root, 'rpcb.yaml')
    if os.path.exists(path) and not args.force:
        return die(f'{os.path.basename(path)} already exists (use --force)')
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
""")
    print(f'wrote {os.path.relpath(path, project.root)}  (optional — built-in '
          f'rules run without it)')
    print(f'project: {project.name}')
    print(f"sheets : {[os.path.basename(p) for p in project.schematics]}")
    print('next   : rpcb rules --kinds')
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

    p = sp.add_parser('rules', help='list active rules')
    p.add_argument('--kinds', action='store_true',
                   help='document how to write a rule')
    sp.add_parser('mcp', help='run the MCP stdio server')

    return ap


HANDLERS = {
    'summary': cmd_summary, 'component': cmd_component, 'net': cmd_net,
    'pin': cmd_pin, 'trace': cmd_trace, 'find': cmd_find, 'notes': cmd_notes,
    'text': cmd_text, 'check': cmd_check, 'dump': cmd_dump,
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
    except (extract.ExtractError, rules_mod.RulesError) as exc:
        return die(str(exc))
    except views.NotFound as exc:
        return die(str(exc))
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
