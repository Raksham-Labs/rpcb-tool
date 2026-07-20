"""Render the design model as compact text.

Every function returns a string rather than printing, so the CLI, the MCP
server and the launcher all share one implementation with no subprocess hop.
"""
import os
import re


def pin_sort(num):
    return (0, int(num)) if str(num).isdigit() else (1, str(num))


class NotFound(Exception):
    pass


def summary(m):
    s = m['stats']
    out = []
    w = out.append
    name = m.get('source', {}).get('project') or os.path.basename(
        m['design'].get('source', 'design'))
    w(f"# {name} — {s['components']} components · {s['nets']} nets · "
      f"{s['pin_nodes']} pin-nodes · sheets {s['sheets']}")
    for v in m['design'].get('variants', []):
        w(f"  variant: {v['name']} — {v['description']}")
    w('')
    w('pintypes: ' + ', '.join(f'{k}={v}' for k, v in s['pintype_histogram'].items()))
    power = sorted(n['name'] for n in m['nets'].values() if n['is_power'])
    signal = sorted(n['name'] for n in m['nets'].values()
                    if not n['is_power'] and not n['is_unconnected'])
    ics = sorted(r for r, c in m['components'].items() if r.startswith('U'))
    w('')
    w(f'power nets ({len(power)}): ' + ' '.join(power))
    w('')
    w(f'signal nets ({len(signal)}): ' + ' '.join(signal))
    w('')
    w(f'ICs: ' + ' '.join(ics))
    w('')
    w(f"unconnected nets: {s['nets_unconnected']}   notes: {s['notes']}")
    w('')
    w('next: component <ref> | net <name> | pin <ref.pin> | check | notes')
    return '\n'.join(out)


def component(m, ref):
    c = m['components'].get(ref)
    if c is None:
        near = [r for r in m['components'] if r.upper().startswith(ref.upper())]
        raise NotFound(f'no component {ref!r}'
                       + (f'; did you mean {near}?' if near else ''))
    out = []
    w = out.append
    w(f"{c['ref']}  {c['value']}   [{c['libpart']}]")
    w(f"  footprint : {c['footprint']}")
    w(f"  sheet     : {c['sheet']}   dnp={c['dnp']}  in_bom={c['in_bom']}")
    if c['mpn']:
        w(f"  mpn       : {c['mpn']}  ({c['manufacturer']})")
    if c['description']:
        w(f"  desc      : {c['description']}")
    if c.get('datasheet'):
        w(f"  datasheet : {c['datasheet']}")
    w(f"  {'pin':>4}  {'function':<16}{'type':<16}net")
    for num in sorted(c['pins'], key=pin_sort):
        p = c['pins'][num]
        w(f"  {num:>4}  {p['function'][:15]:<16}{p['type']:<16}"
          f"{p['net'] if p['net'] else '— FLOATING —'}")
    nb = m['graph']['signal_neighbors'].get(ref, [])
    w(f"  signal neighbours: {' '.join(nb) if nb else '(none)'}")
    return '\n'.join(out)


def net(m, name):
    n = m['nets'].get(name)
    if n is None:
        matches = [k for k in m['nets'] if name.lower() in k.lower()]
        if len(matches) == 1:
            n = m['nets'][matches[0]]
        else:
            raise NotFound(f'no net {name!r}'
                           + (f'; matches: {matches[:20]}' if matches else ''))
    out = []
    w = out.append
    tags = []
    if n['is_power']:
        tags.append('power')
    if n['is_global']:
        tags.append('global')
    if n['is_unconnected']:
        tags.append('unconnected')
    w(f"{n['name']}  [{' '.join(tags) if tags else 'signal'}]  "
      f"{n['pin_count']} pins  class={n['net_class']}  sheets={n['sheets']}")
    if n['power_evidence']:
        w(f"  power evidence: {'; '.join(n['power_evidence'])}")
    w(f"  drivers: {' '.join(n['drivers']) if n['drivers'] else '(none)'}")
    w(f"  {'ref.pin':<12}{'function':<16}{'type':<16}value")
    for nd in sorted(n['nodes'], key=lambda x: (x['ref'], pin_sort(x['pin']))):
        val = m['components'].get(nd['ref'], {}).get('value', '')
        w(f"  {nd['ref'] + '.' + nd['pin']:<12}{nd['function'][:15]:<16}"
          f"{nd['type']:<16}{val}")
    return '\n'.join(out)


def pin(m, pin_id):
    if '.' not in pin_id:
        raise NotFound('use REF.PIN, e.g. U2.45')
    ref, num = pin_id.rsplit('.', 1)
    c = m['components'].get(ref)
    if not c or num not in c['pins']:
        raise NotFound(f'no pin {pin_id}')
    p = c['pins'][num]
    n = m['nets'].get(p['net']) if p['net'] else None
    others = [x for x in (n['nodes'] if n else [])
              if not (x['ref'] == ref and x['pin'] == num)]
    out = [f"{ref}.{num}  {p['function']}  ({p['type']})  "
           f"on net {p['net'] or '— FLOATING —'}"]
    for x in sorted(others, key=lambda x: x['ref']):
        val = m['components'].get(x['ref'], {}).get('value', '')
        out.append(f"   -> {x['ref']}.{x['pin']:<4} {x['function'][:15]:<16}"
                   f"{x['type']:<16}{val}")
    if not others:
        out.append('   -> nothing else on this net')
    return '\n'.join(out)


def trace(m, start, hops=3, through_power=False, max_expand_pins=3):
    if '.' not in start:
        raise NotFound('use REF.PIN, e.g. U2.45')
    seen, frontier, rows = {start}, [start], []
    for hop in range(hops):
        nxt = []
        for pid in frontier:
            net_name = m['graph']['pin_to_net'].get(pid)
            if not net_name:
                continue
            n = m['nets'][net_name]
            if n['is_power'] and not through_power:
                rows.append({'hop': hop + 1, 'from': pid, 'net': net_name,
                             'note': 'stopped at power rail (use --through-power)'})
                continue
            for nd in n['nodes']:
                tid = f"{nd['ref']}.{nd['pin']}"
                if tid in seen:
                    continue
                seen.add(tid)
                rows.append({'hop': hop + 1, 'from': pid, 'net': net_name, 'to': tid,
                             'function': nd['function'], 'type': nd['type'],
                             'value': m['components'].get(nd['ref'], {}).get('value', '')})
                # Continue only through small passives (series R, coupling C,
                # diode). Expanding through a 49-pin MCU would enumerate the
                # whole board and say nothing.
                landed = m['components'].get(nd['ref'], {})
                pins = landed.get('pins', {})
                if len(pins) <= max_expand_pins:
                    for other in pins:
                        oid = f"{nd['ref']}.{other}"
                        if oid not in seen:
                            nxt.append(oid)
        frontier = nxt
    out = [f'trace from {start} ({hops} hops)']
    for r in rows:
        if 'to' in r:
            out.append(f"  hop{r['hop']}  {r['from']:>10} --[{r['net']}]--> "
                       f"{r['to']:<10} {r['function'][:14]:<15}{r['type']:<15}{r['value']}")
        else:
            out.append(f"  hop{r['hop']}  {r['from']:>10} --[{r['net']}]  {r['note']}")
    if len(out) == 1:
        out.append('  (nothing reachable)')
    return '\n'.join(out)


def find(m, pattern):
    pat = re.compile(pattern, re.I)
    comps = [f"{r} {c['value']} [{c['libpart']}]" for r, c in m['components'].items()
             if pat.search(r) or pat.search(c['value']) or pat.search(c['libpart'])
             or pat.search(c.get('mpn', ''))]
    nets = [f"{k} ({v['pin_count']} pins)" for k, v in m['nets'].items() if pat.search(k)]
    notes = [t['text'] for t in m['notes'] if pat.search(t['text'])]
    out = []
    for kind, rows in (('components', comps), ('nets', nets), ('notes', notes)):
        if rows:
            out.append(f'{kind} ({len(rows)}):')
            out.extend(f'  {r}' for r in rows)
    return '\n'.join(out) if out else f'nothing matches {pattern!r}'


def notes(m):
    if not m['notes']:
        return '(no text annotations in this schematic)'
    out = []
    for n in m['notes']:
        near = ', '.join(f"{x['ref']}@{x['distance_mm']}mm"
                         for x in n['near_components'])
        out.append(f"- [{n['sheet_file']}] {n['text']}")
        out.append(f"    near: {near or '(nothing within 60mm)'}")
    return '\n'.join(out)


def full_text(m, include_unconnected=False):
    out = []
    w = out.append
    s = m['stats']
    name = m.get('source', {}).get('project', 'design')
    w(f"# {name} — {s['components']} components · {s['nets']} nets · "
      f"{s['pin_nodes']} pin-nodes")
    w('# connectivity resolved by kicad-cli; notes/dnp from schematic')

    w('\n## DESIGN NOTES')
    if m['notes']:
        for n in m['notes']:
            near = ' '.join(x['ref'] for x in n['near_components'])
            w(f"- [{n['sheet_file']}] {n['text']}" + (f'   (near {near})' if near else ''))
    else:
        w('(none)')

    w('\n## COMPONENTS')
    w(f"{'ref':<6}{'value':<20}{'symbol':<24}{'footprint':<32}{'sheet':<11}mpn")
    for r, c in sorted(m['components'].items(), key=lambda kv: (kv[1]['sheet'], kv[0])):
        fp = c['footprint'].split(':')[-1][:31]
        part = c['libpart'].split(':')[-1][:23]
        w(f"{r:<6}{c['value'][:19]:<20}{part:<24}{fp:<32}{c['sheet']:<11}"
          f"{c['mpn']}{'  [DNP]' if c['dnp'] else ''}")

    w('\n## CONNECTIONS BY COMPONENT')
    for r, c in sorted(m['components'].items(), key=lambda kv: (kv[1]['sheet'], kv[0])):
        w(f"\n{r} {c['value']} [{c['libpart'].split(':')[-1]}] sheet:{c['sheet']}")
        for num in sorted(c['pins'], key=pin_sort):
            p = c['pins'][num]
            w(f"  {num:>4}  {p['function'][:15]:<16}{p['type']:<16}"
              f"{p['net'] or '— FLOATING —'}")

    w('\n## NETS')
    omitted = 0
    for nm, n in sorted(m['nets'].items(), key=lambda kv: -kv[1]['pin_count']):
        if n['is_unconnected'] and not include_unconnected:
            omitted += 1
            continue
        tag = ' [power]' if n['is_power'] else ''
        pins = ' '.join(sorted(f"{x['ref']}.{x['pin']}" for x in n['nodes']))
        w(f'{nm}{tag} ({n["pin_count"]}): {pins}')
    if omitted:
        w(f"\n({omitted} single-pin 'unconnected-*' nets omitted; "
          f'--include-unconnected to list them)')
    return '\n'.join(out)
