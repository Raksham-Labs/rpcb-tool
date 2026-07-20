"""Build a complete, LLM-friendly JSON model of a KiCad design.

Connectivity comes from KiCad's own netlist exporter (kicad-cli), NOT from
re-deriving pin geometry. A hand-rolled resolver was built once and matched
KiCad exactly (75/75 nets) -- but only after fixing a bug where the wrong
rotation direction silently swapped pins 1<->2 on every 270-degree-rotated part,
reversing four protection diodes. Every pin still landed neatly on a wire, so
the netlist looked valid while being wrong. A confidently-wrong netlist is worse
than none, so KiCad is authoritative.

The schematic is parsed only for what the netlist drops: text notes, `dnp`,
`in_bom`, symbol positions and global-label names.

Output is FACTS ONLY. Judgements live in the rules layer.
"""
import hashlib
import os
import shutil
import subprocess
import sys
from collections import OrderedDict, defaultdict

from .sexpr import parse_file, atoms, subs, sub, a1, arg

SCHEMA_VERSION = '1.1'

KICAD_CLI_CANDIDATES = [
    os.environ.get('KICAD_CLI'),
    'kicad-cli',
    '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli',
    '/usr/bin/kicad-cli',
    '/usr/local/bin/kicad-cli',
    r'C:\Program Files\KiCad\9.0\bin\kicad-cli.exe',
    r'C:\Program Files\KiCad\10.0\bin\kicad-cli.exe',
]

DRIVER_TYPES = {'power_out', 'output', 'open_collector', 'open_emitter', 'tri_state'}
SINK_TYPES = {'power_in', 'input'}


class ExtractError(Exception):
    pass


def find_kicad_cli():
    for cand in KICAD_CLI_CANDIDATES:
        if not cand:
            continue
        resolved = shutil.which(cand) if os.path.basename(cand) == cand else cand
        if resolved and os.path.exists(resolved):
            return resolved
    return None


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def export_netlist(root_schematic, out_path):
    cli = find_kicad_cli()
    if cli is None:
        raise ExtractError(
            'kicad-cli not found. Install KiCad, or set $KICAD_CLI to its path.')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    proc = subprocess.run(
        [cli, 'sch', 'export', 'netlist', '--format', 'kicadsexpr',
         '-o', out_path, root_schematic],
        capture_output=True, text=True)
    if proc.returncode != 0 or not os.path.exists(out_path):
        raise ExtractError(
            f'kicad-cli netlist export failed:\n{proc.stderr.strip()[-1500:]}')
    return out_path


# --------------------------------------------------------------------------
def read_netlist(path):
    root = parse_file(path)

    libparts = {}
    for lp in subs(sub(root, 'libparts'), 'libpart'):
        key = f"{a1(lp, 'lib')}:{a1(lp, 'part')}"
        pins = OrderedDict()
        for p in subs(sub(lp, 'pins'), 'pin'):
            pins[a1(p, 'num')] = {'name': a1(p, 'name'), 'type': a1(p, 'type')}
        libparts[key] = {
            'lib': a1(lp, 'lib'),
            'part': a1(lp, 'part'),
            'description': a1(lp, 'description'),
            'datasheet': a1(lp, 'docs'),
            'footprint_filters': [arg(fp, 0) for fp in subs(sub(lp, 'footprints'), 'fp')],
            'pins': pins,
        }

    components = OrderedDict()
    for c in subs(sub(root, 'components'), 'comp'):
        ref = a1(c, 'ref')
        ls = sub(c, 'libsource')
        props = {a1(p, 'name'): a1(p, 'value') for p in subs(c, 'property')}
        fields = {k: v for k, v in props.items()
                  if not k.startswith(('ki_', 'KLC_', 'Sim.'))}
        components[ref] = {
            'ref': ref,
            'value': a1(c, 'value'),
            'footprint': a1(c, 'footprint'),
            'description': a1(c, 'description'),
            'datasheet': a1(c, 'datasheet'),
            'sheet': a1(sub(c, 'sheetpath'), 'names', '/'),
            'libpart': f"{a1(ls, 'lib')}:{a1(ls, 'part')}" if ls else '',
            'mpn': fields.get('MPN', ''),
            'manufacturer': fields.get('manufacturer', ''),
            'fields': fields,
            'units': [a1(u, 'name') for u in subs(sub(c, 'units'), 'unit')],
            'pins': OrderedDict(),
            'dnp': False,
            'in_bom': True,
        }

    nets = OrderedDict()
    for n in subs(sub(root, 'nets'), 'net'):
        name = a1(n, 'name')
        nodes = []
        for nd in subs(n, 'node'):
            ref, pin = a1(nd, 'ref'), a1(nd, 'pin')
            ptype = a1(nd, 'pintype')
            # The library pin name is authoritative; KiCad's `pinfunction`
            # appends "_<pin>" to make it unique (PB6 -> PB6_45).
            lp = libparts.get(components.get(ref, {}).get('libpart', ''))
            func = lp['pins'].get(pin, {}).get('name', '') if lp else ''
            if not func:
                func = a1(nd, 'pinfunction')
                if func.endswith('_' + pin):
                    func = func[:-(len(pin) + 1)]
            nodes.append({'ref': ref, 'pin': pin, 'function': func, 'type': ptype})
        nets[name] = {
            'name': name,
            'code': a1(n, 'code'),
            'net_class': a1(n, 'class'),
            'nodes': nodes,
        }

    design = sub(root, 'design')
    meta = {
        'tool': a1(design, 'tool'),
        'source': a1(design, 'source'),
        'sheets': [{'name': a1(s, 'name'), 'number': a1(s, 'number'),
                    'file': a1(sub(s, 'title_block'), 'source')}
                   for s in subs(design, 'sheet')],
        'variants': [{'name': a1(v, 'name'), 'description': a1(v, 'description')}
                     for v in subs(sub(root, 'variants'), 'variant')],
        'libraries': [{'logical': a1(l, 'logical'), 'uri': a1(l, 'uri')}
                      for l in subs(sub(root, 'libraries'), 'library')],
    }
    return components, nets, libparts, meta


def read_schematics(paths):
    notes, positions, global_labels, flags = [], {}, set(), {}
    for path in paths:
        fname = os.path.basename(path)
        try:
            root = parse_file(path)
        except (OSError, ValueError):
            continue

        for t in subs(root, 'text'):
            body = ' '.join(arg(t, 0).split())
            at = atoms(sub(t, 'at'))
            if body:
                notes.append({
                    'text': body,
                    'sheet_file': fname,
                    'at': [float(at[0]), float(at[1])] if len(at) >= 2 else None,
                })

        for g in subs(root, 'global_label'):
            global_labels.add(arg(g, 0))

        for s in subs(root, 'symbol'):
            ref = ''
            inst = sub(s, 'instances')
            if inst:
                proj = sub(inst, 'project')
                if proj:
                    p = sub(proj, 'path')
                    if p:
                        ref = a1(p, 'reference')
            if not ref:
                for prop in subs(s, 'property'):
                    if arg(prop, 0) == 'Reference':
                        ref = arg(prop, 1)
            if not ref or ref.startswith('#'):
                continue
            at = atoms(sub(s, 'at'))
            if len(at) >= 2:
                positions.setdefault(ref, {'sheet_file': fname,
                                           'at': [float(at[0]), float(at[1])]})
            flags.setdefault(ref, {})
            if a1(s, 'dnp') == 'yes':
                flags[ref]['dnp'] = True
            if a1(s, 'in_bom') == 'no':
                flags[ref]['in_bom'] = False
    return notes, positions, global_labels, flags


def attach_notes(notes, positions, limit=3, radius=60.0):
    """Associate each note with nearby components by distance.

    A HINT for locating the note's subject, not a claim about its scope.
    """
    for note in notes:
        if not note['at']:
            note['near_components'] = []
            continue
        nx, ny = note['at']
        near = []
        for ref, pos in positions.items():
            if pos['sheet_file'] != note['sheet_file']:
                continue
            dx, dy = pos['at'][0] - nx, pos['at'][1] - ny
            dist = (dx * dx + dy * dy) ** 0.5
            if dist <= radius:
                near.append((round(dist, 1), ref))
        near.sort()
        note['near_components'] = [{'ref': r, 'distance_mm': d} for d, r in near[:limit]]


def classify_net(net, global_labels):
    name = net['name']
    types = {n['type'] for n in net['nodes']}
    evidence = []
    if types & {'power_in', 'power_out'}:
        evidence.append('has power_in/power_out pin')
    bare = name.rsplit('/', 1)[-1]
    if bare.startswith('+') or bare in {'GND', 'GNDA', 'VSS', 'VDD', 'VCC', 'AGND'}:
        evidence.append('name matches power convention')
    return {
        'is_power': bool(evidence),
        'power_evidence': evidence,
        'is_global': bare in global_labels or name in global_labels,
        'is_unconnected': name.startswith('unconnected-'),
        'is_autonamed': name.startswith(('Net-(', 'unconnected-')),
        'sheets': sorted({n.get('sheet', '/') for n in net['nodes']}) or ['/'],
    }


def build(components, nets, libparts, meta, notes, positions, global_labels, flags):
    for ref, f in flags.items():
        if ref in components:
            components[ref]['dnp'] = f.get('dnp', False)
            components[ref]['in_bom'] = f.get('in_bom', True)

    for name, net in nets.items():
        for node in net['nodes']:
            comp = components.get(node['ref'])
            if comp is None:
                continue
            node['sheet'] = comp['sheet']
            comp['pins'][node['pin']] = {
                'function': node['function'], 'type': node['type'], 'net': name,
            }
        net.update(classify_net(net, global_labels))
        net['drivers'] = [f"{n['ref']}.{n['pin']}" for n in net['nodes']
                          if n['type'] in DRIVER_TYPES]
        net['sinks'] = [f"{n['ref']}.{n['pin']}" for n in net['nodes']
                        if n['type'] in SINK_TYPES]
        net['pin_count'] = len(net['nodes'])

    for ref, comp in components.items():
        lp = libparts.get(comp['libpart'])
        if lp:
            for num, info in lp['pins'].items():
                comp['pins'].setdefault(num, {
                    'function': info['name'], 'type': info['type'], 'net': None})
        comp['pins'] = OrderedDict(
            sorted(comp['pins'].items(),
                   key=lambda kv: (0, int(kv[0])) if kv[0].isdigit() else (1, kv[0])))
        comp['position'] = positions.get(ref, {}).get('at')

    pin_to_net = {}
    for name, net in nets.items():
        for n in net['nodes']:
            pin_to_net[f"{n['ref']}.{n['pin']}"] = name

    # Neighbours via SIGNAL nets only. Including power rails would make every
    # component adjacent to every other and carry no information.
    neighbors = defaultdict(set)
    for net in nets.values():
        if net['is_power'] or net['is_unconnected']:
            continue
        refs = {n['ref'] for n in net['nodes']}
        for r in refs:
            neighbors[r] |= (refs - {r})

    graph = {
        'model': 'bipartite hypergraph: components/pins <-> nets',
        'pin_to_net': pin_to_net,
        'net_to_pins': {name: [f"{n['ref']}.{n['pin']}" for n in net['nodes']]
                        for name, net in nets.items()},
        'signal_neighbors': {r: sorted(v) for r, v in sorted(neighbors.items())},
        'signal_neighbors_note': 'power/unconnected nets excluded to keep this useful',
    }

    pintype_hist = defaultdict(int)
    for net in nets.values():
        for n in net['nodes']:
            pintype_hist[n['type']] += 1

    stats = {
        'components': len(components),
        'components_dnp': sum(1 for c in components.values() if c['dnp']),
        'nets': len(nets),
        'nets_power': sum(1 for n in nets.values() if n['is_power']),
        'nets_unconnected': sum(1 for n in nets.values() if n['is_unconnected']),
        'pin_nodes': sum(len(n['nodes']) for n in nets.values()),
        'sheets': sorted({c['sheet'] for c in components.values()}),
        'notes': len(notes),
        'pintype_histogram': dict(sorted(pintype_hist.items(), key=lambda kv: -kv[1])),
    }
    return {
        'schema_version': SCHEMA_VERSION,
        'design': meta,
        'stats': stats,
        'components': components,
        'nets': nets,
        'libparts': libparts,
        'notes': notes,
        'graph': graph,
    }


def extract(project, regenerate_netlist=True):
    """Build the model for `project` and return it (does not write)."""
    project.ensure_out_dir()
    if regenerate_netlist or not os.path.exists(project.netlist_path):
        export_netlist(project.root_schematic, project.netlist_path)

    schematics = project.schematics
    components, nets, libparts, meta = read_netlist(project.netlist_path)
    notes, positions, global_labels, flags = read_schematics(schematics)
    attach_notes(notes, positions)
    model = build(components, nets, libparts, meta, notes, positions,
                  global_labels, flags)

    model['source'] = {
        'generator': 'rpcb',
        'schema_version': SCHEMA_VERSION,
        'project': project.name,
        'root': project.root,
        'inputs': [{'path': os.path.relpath(p, project.root), 'sha256': sha256(p),
                    'bytes': os.path.getsize(p)}
                   for p in schematics if os.path.exists(p)],
        'connectivity_source': 'kicad-cli sch export netlist (authoritative)',
    }
    return model


def is_stale(project):
    """(stale, reason) -- True if the model is missing or a schematic changed."""
    import json
    if not os.path.exists(project.model_path):
        return True, 'no model yet'
    try:
        with open(project.model_path, encoding='utf-8') as fh:
            model = json.load(fh)
    except (OSError, ValueError) as exc:
        return True, f'unreadable model: {exc}'
    if model.get('schema_version') != SCHEMA_VERSION:
        return True, (f"model schema {model.get('schema_version')} != "
                      f"{SCHEMA_VERSION}")
    recorded = {r['path']: r.get('sha256') for r in
                model.get('source', {}).get('inputs', [])}
    current = {os.path.relpath(p, project.root): sha256(p)
               for p in project.schematics if os.path.exists(p)}
    if set(recorded) != set(current):
        return True, 'sheet hierarchy changed'
    for path, digest in current.items():
        if recorded.get(path) != digest:
            return True, f'{path} changed since last extract'
    return False, ''


def write(project, model):
    import json
    project.ensure_out_dir()
    with open(project.model_path, 'w', encoding='utf-8') as fh:
        json.dump(model, fh, indent=1, ensure_ascii=False)
        fh.write('\n')
    return project.model_path


def ensure_fresh(project, verbose=False):
    """Regenerate the model if stale. Returns a note, or None if it was fresh."""
    stale, reason = is_stale(project)
    if not stale:
        return None
    if verbose:
        print(f'rpcb: regenerating model ({reason})', file=sys.stderr)
    write(project, extract(project))
    return reason
