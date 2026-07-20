"""Locate a KiCad project and its sheet hierarchy from any directory.

This is what makes rpcb portable: nothing is hardcoded to one board. The root
schematic is found via the .kicad_pro file, then child sheets are discovered by
walking `(sheet (property "Sheetfile" ...))` recursively -- so adding a sheet to
a design is picked up automatically instead of silently dropping its notes and
DNP flags.
"""
import os

from .sexpr import parse_file, subs, arg

CONFIG_NAMES = ('rpcb.yaml', 'rpcb.yml', '.rpcb.yaml')
OUTPUT_DIR = '.rpcb'


class ProjectError(Exception):
    """No usable KiCad project at the given path."""


def find_project(start=None):
    """Walk upward from `start` looking for a .kicad_pro file."""
    cur = os.path.abspath(start or os.getcwd())
    while True:
        try:
            entries = sorted(os.listdir(cur))
        except OSError:
            entries = []
        pros = [e for e in entries if e.endswith('.kicad_pro')]
        if pros:
            return cur, os.path.join(cur, pros[0])
        parent = os.path.dirname(cur)
        if parent == cur:
            raise ProjectError(
                'no .kicad_pro found in this directory or any parent. '
                'Run rpcb from inside a KiCad project.')
        cur = parent


def sheet_hierarchy(root_sch):
    """Root schematic + every child sheet, depth-first, de-duplicated.

    KiCad allows the same sheet file to be instantiated more than once; we want
    each file exactly once for note/flag scanning.
    """
    seen, ordered = set(), []
    stack = [os.path.abspath(root_sch)]
    while stack:
        path = stack.pop(0)
        key = os.path.normcase(path)
        if key in seen or not os.path.exists(path):
            continue
        seen.add(key)
        ordered.append(path)
        try:
            doc = parse_file(path)
        except (OSError, ValueError):
            continue
        base = os.path.dirname(path)
        children = []
        for sheet in subs(doc, 'sheet'):
            for prop in subs(sheet, 'property'):
                if arg(prop, 0) == 'Sheetfile':
                    child = arg(prop, 1)
                    if child:
                        children.append(os.path.join(base, child))
        stack = children + stack
    return ordered


class Project:
    """Resolved paths for one KiCad project."""

    def __init__(self, root, pro_path):
        self.root = root
        self.pro_path = pro_path
        self.name = os.path.splitext(os.path.basename(pro_path))[0]
        self.out_dir = os.path.join(root, OUTPUT_DIR)
        self.model_path = os.path.join(self.out_dir, 'design.json')
        self.netlist_path = os.path.join(self.out_dir, 'netlist.kicadsexpr.net')

    @property
    def root_schematic(self):
        path = os.path.join(self.root, self.name + '.kicad_sch')
        if os.path.exists(path):
            return path
        candidates = sorted(f for f in os.listdir(self.root)
                            if f.endswith('.kicad_sch'))
        if not candidates:
            raise ProjectError(f'no .kicad_sch found next to {self.pro_path}')
        return os.path.join(self.root, candidates[0])

    @property
    def schematics(self):
        return sheet_hierarchy(self.root_schematic)

    @property
    def config_path(self):
        for name in CONFIG_NAMES:
            path = os.path.join(self.root, name)
            if os.path.exists(path):
                return path
        return None

    def ensure_out_dir(self):
        os.makedirs(self.out_dir, exist_ok=True)
        # Derived data; keep it out of the user's git history automatically.
        marker = os.path.join(self.out_dir, '.gitignore')
        if not os.path.exists(marker):
            with open(marker, 'w', encoding='utf-8') as fh:
                fh.write('*\n')
        return self.out_dir

    def __repr__(self):
        return f'<Project {self.name} at {self.root}>'


def load(start=None):
    root, pro = find_project(start)
    return Project(root, pro)
