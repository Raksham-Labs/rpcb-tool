"""Datasheet inventory: which parts need one, and what is actually on disk.

Rules check connectivity. They cannot check whether 4.6V clears a part's
minimum -- that needs the document. A review asserting an electrical limit
without one is quoting memory, and two models recalling the same wrong number
agree just as confidently as two recalling the right one.

WHAT THIS MODULE WILL NOT DO is decide whether a file is the right datasheet.
It cannot: only opening the PDF answers that, and a filename is not evidence.
An earlier version matched part numbers against filenames and called that
`present` -- which passed a zero-byte file named `MCP2562FD.pdf`. A check that
only reads names accepts anything named correctly, so that check is gone.

What is left is strictly mechanical, and therefore trustworthy:

  * which parts need a datasheet at all      (reference prefix)
  * the one canonical path each should be at (deterministic from the MPN)
  * whether a file exists at exactly that path
  * every other file sitting in the datasheet directories, unfiled

`filed` therefore means "a file is at the canonical path", never "the right
document is present". Confirming the device, renaming, moving and fetching are
the agent's work -- see review_prompt.md. This module tells it what to look at.

Two locations:

    vendor/<part>/datasheets/   primary -- beside that part's symbols,
                                footprints and 3D models
    datasheets/                 secondary -- a document covering several parts,
                                one belonging to no single component, or where
                                no vendor folder matches
"""
import os
import re

# Reference prefixes whose limits a schematic review does not turn on. Nobody
# needs a datasheet for an 0402 resistor; demanding one trains the reader to
# ignore the list, which costs more than the parts it would catch.
PASSIVE_PREFIXES = frozenset({
    'R', 'C', 'L', 'FB', 'TP', 'H', 'FID', 'MH', 'MK', 'LOGO', 'NT', 'JP',
})

# Which of these a given review actually turns on is NOT decided here. A
# reference prefix cannot tell you that: a TVS standoff voltage is the whole
# question on one board and irrelevant on the next, and the difference is what
# is being reviewed -- something this module has no access to.
#
# So the tool reports every candidate with enough context to judge it -- part
# number, description, pin count, what is on disk -- and the reviewer decides
# what it needs before starting. See review_prompt.md.

VENDOR_DIR = 'vendor'
DATASHEET_DIR = 'datasheets'

# Folder names shorter than this match too much: `vendor/ldo` against any part
# number beginning "ldo" is coincidence, not routing.
MIN_FOLDER_LEN = 4


def _norm(text):
    return re.sub(r'[^a-z0-9]', '', (text or '').lower())


def _clean(text):
    """KiCad writes `~` for an empty field; treat it as empty."""
    text = (text or '').strip()
    return '' if text in ('~', '-') else text


def _is_url(text):
    return _clean(text).startswith(('http://', 'https://'))


def slug(text):
    """Part number -> filename stem. `MCP2562FDT-H/MF` -> `MCP2562FDT-H-MF`.

    Deterministic, so the canonical path is the same every run and an agent
    filing a document lands exactly where the next run will look.
    """
    return re.sub(r'-+', '-', re.sub(r'[^A-Za-z0-9._-]', '-', _clean(text))).strip('-')


def ref_prefix(ref):
    """`U12` -> `U`, `FB3` -> `FB`."""
    return re.match(r'^[A-Za-z]*', ref or '').group(0).upper()


def ref_sort(ref):
    """Natural order, so J2 precedes J10 instead of following it."""
    digits = re.search(r'(\d+)', ref or '')
    return (ref_prefix(ref), int(digits.group(1)) if digits else 0, ref or '')


def requires_datasheet(ref):
    return bool(ref) and ref_prefix(ref) not in PASSIVE_PREFIXES


def _vendor_folders(root):
    """Existing vendor folders, with the symbol libraries each supplies."""
    folders = {}
    vendor = os.path.join(root, VENDOR_DIR)
    if not os.path.isdir(vendor):
        return folders
    for entry in sorted(os.listdir(vendor)):
        path = os.path.join(vendor, entry)
        if not os.path.isdir(path):
            continue
        libs = set()
        for _dirpath, _dirs, files in os.walk(path):
            for name in files:
                if name.endswith('.kicad_sym'):
                    libs.add(_norm(os.path.splitext(name)[0]))
        folders[entry] = libs
    return folders


def canonical_dir(comp, folders):
    """Which of the two locations this part's datasheet belongs in.

    Routed to a vendor folder two ways, because those folders are named by
    whatever made sense to a human:

      by symbol library -- vendor/can_transceiver/CANBUS.kicad_sym means a part
        whose libpart is `CANBUS:MCP2562` belongs there
      by folder name    -- vendor/stm32g0 against MPN STM32G0B1CCU6

    Neither can invent a folder that does not exist. Where nothing matches, the
    shared directory is the honest answer rather than a guessed name.
    """
    lib = _norm((comp.get('libpart') or '').split(':')[0])
    for entry, libs in folders.items():
        if lib and lib in libs:
            return os.path.join(VENDOR_DIR, entry, DATASHEET_DIR)
    for key in (_clean(comp.get('mpn')), _clean(comp.get('value'))):
        norm_key = _norm(key)
        if not norm_key:
            continue
        for entry in sorted(folders, key=len, reverse=True):
            name = _norm(entry)
            if len(name) >= MIN_FOLDER_LEN and norm_key.startswith(name):
                return os.path.join(VENDOR_DIR, entry, DATASHEET_DIR)
    return DATASHEET_DIR


def _existing_files(root):
    """Every file in either datasheet location, project-relative."""
    found = []
    vendor = os.path.join(root, VENDOR_DIR)
    if os.path.isdir(vendor):
        for entry in sorted(os.listdir(vendor)):
            here = os.path.join(vendor, entry, DATASHEET_DIR)
            if os.path.isdir(here):
                found += [os.path.join(here, f) for f in sorted(os.listdir(here))]
    fallback = os.path.join(root, DATASHEET_DIR)
    if os.path.isdir(fallback):
        found += [os.path.join(fallback, f) for f in sorted(os.listdir(fallback))]
    return [os.path.relpath(p, root) for p in found
            if os.path.isfile(p) and not os.path.basename(p).startswith('.')]


def inventory(model, root):
    """Classify every component; locate files by exact path only."""
    folders = _vendor_folders(root)
    on_disk = _existing_files(root)
    claimed = set()

    required, passive, not_fitted, bom_gaps = [], [], [], []
    for ref, comp in model['components'].items():
        if not requires_datasheet(ref):
            passive.append(ref)
            continue
        # A DNP part is not populated, so its limits do not constrain the board
        # as built. Counted, not silently dropped.
        if comp.get('dnp'):
            not_fitted.append(ref)
            continue

        mpn, value = _clean(comp.get('mpn')), _clean(comp.get('value'))
        # MPN is the join key. Value is a fallback only because some libraries
        # put the part number there; it is not a substitute for a real MPN.
        key = mpn or value
        directory = canonical_dir(comp, folders)
        path = os.path.join(directory, slug(key) + '.pdf') if key else None
        filed = bool(path) and path in on_disk
        if filed:
            claimed.add(path)

        url = _clean(comp.get('datasheet'))
        entry = {
            'ref': ref,
            'mpn': mpn,
            'manufacturer': _clean(comp.get('manufacturer')),
            'value': value,
            # Description, pin count and symbol are what let a reviewer tell an
            # MCU from an indicator LED without opening anything. Carried here
            # so the judgement can be made from this one command.
            'description': _clean(comp.get('description')),
            'pins': len(comp.get('pins') or ()),
            'libpart': _clean(comp.get('libpart')),
            'url': url if _is_url(url) else '',
            'url_field': url,
            'identified': bool(key),
            'path': path,
            'dir': directory,
            'filed': filed,
        }
        required.append(entry)
        # No MPN blocks the lookup outright; a missing manufacturer only makes
        # sourcing ambiguous. Ordered so the severe gap is not buried.
        if not mpn:
            bom_gaps.append({'ref': ref, 'gap': 'no MPN', 'value': value, 'rank': 0})
        elif not entry['manufacturer']:
            bom_gaps.append({'ref': ref, 'gap': 'no manufacturer', 'value': mpn,
                             'rank': 1})

    required.sort(key=lambda r: (r['filed'], ref_sort(r['ref'])))
    bom_gaps.sort(key=lambda g: (g['rank'], ref_sort(g['ref'])))
    return {
        'required': required,
        'filed': [r for r in required if r['filed']],
        'absent': [r for r in required if not r['filed'] and r['identified']],
        'unidentified': [r for r in required if not r['identified']],
        # Files nobody's canonical path claims. Wrong name, wrong folder, or a
        # document for a part not on this board -- the agent must open them to
        # tell which, so they are listed rather than guessed about.
        'unfiled': [p for p in on_disk if p not in claimed],
        'bom_gaps': bom_gaps,
        'skipped_passive': passive,
        'skipped_not_fitted': not_fitted,
        'searched': [os.path.join(VENDOR_DIR, '*', DATASHEET_DIR), DATASHEET_DIR],
    }


def render(inv):
    out = []
    w = out.append
    required = inv['required']
    absent, unknown, unfiled = inv['absent'], inv['unidentified'], inv['unfiled']

    if not required:
        return 'no parts require a datasheet (only passives and mechanical).'

    w(f"{len(required)} candidate parts — {len(inv['filed'])} filed, "
      f"{len(absent)} absent"
      + (f", {len(unknown)} unidentified" if unknown else ''))
    w('')
    w('This is the candidate list, NOT a fetch list. Which of these a review')
    w('turns on depends on what is being reviewed, which this command cannot')
    w('know — decide that yourself from the descriptions below, get what you')
    w('need BEFORE reviewing, and say which you judged irrelevant and why.')
    w('')
    w('"filed" means a file sits at the canonical path. It does NOT mean the')
    w('file is the right document — open it and confirm it names the part.')

    named = [r for r in required if r['identified']]
    if named:
        w('')
        w(f"  {'ref':<7}{'part':<22}{'pins':>5}  {'what it is':<30}datasheet")
        for r in named:
            # Fall back to the symbol name, minus an empty library nickname
            # that would otherwise render as a bare leading colon.
            what = (r['description'] or r['libpart'].lstrip(':') or '—')[:29]
            where = r['path'] if r['filed'] else f"ABSENT -> {r['path']}"
            w(f"  {r['ref']:<7}{(r['mpn'] or r['value'])[:21]:<22}"
              f"{r['pins']:>5}  {what:<30}{where}")

    if unfiled:
        w('')
        w(f"unfiled files ({len(unfiled)}) — no part's canonical path claims these.")
        w('Open each: if it is one of the parts above, rename and move it there;')
        w('if it belongs to no part on this board, say so rather than deleting it.')
        for p in unfiled:
            w(f"  {p}")

    if unknown:
        w('')
        w(f"unidentified ({len(unknown)}): "
          f"{' '.join(sorted((r['ref'] for r in unknown), key=ref_sort))}")
        w('  No MPN and no part number in Value, so there is nothing to look up')
        w('  and no canonical name to file under. These need the BOM fixed first;')
        w('  asking for the document would name the wrong problem. Not counted as')
        w('  absent, so unlabelled headers do not hold the gate shut forever.')

    if inv['bom_gaps']:
        w('')
        w(f"BOM gaps ({len(inv['bom_gaps'])}) — tell the user to fix these:")
        for g in inv['bom_gaps']:
            w(f"  {g['ref']:<7}{g['gap']:<18}{g['value']}")

    urls = [r for r in absent if r['url']]
    if urls:
        w('')
        w('links carried by the schematic — a link inherited from a borrowed')
        w('symbol may name another device, so confirm before filing:')
        for r in urls:
            w(f"  {r['ref']:<7}{(r['mpn'] or r['value'])[:21]:<22}{r['url']}")

    no_link = [r for r in absent if not r['url']]
    if no_link:
        w('')
        w("no link in the schematic: "
          f"{' '.join(sorted((r['ref'] for r in no_link), key=ref_sort))}")
        w('  Search the part number, or ask the user for the document.')

    w('')
    w(f"skipped {len(inv['skipped_passive'])} passive/mechanical, "
      f"{len(inv['skipped_not_fitted'])} not fitted (DNP)")
    w(f"searched: {'  '.join(inv['searched'])}")
    return '\n'.join(out)
