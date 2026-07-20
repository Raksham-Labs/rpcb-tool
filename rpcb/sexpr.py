"""Minimal S-expression reader for KiCad files (schematics and netlists).

Shared by kicad_extract.py / kicad_query.py. No third-party dependencies.
"""

_ESCAPES = {'n': '\n', 't': '\t', 'r': '\r', '"': '"', '\\': '\\'}


def tokenize(s):
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c in '()':
            yield ('P', c)
            i += 1
        elif c == '"':
            j, buf = i + 1, []
            while j < n:
                ch = s[j]
                if ch == '\\' and j + 1 < n:
                    # KiCad writes \n, \", \\ inside quoted strings.
                    buf.append(_ESCAPES.get(s[j + 1], s[j + 1]))
                    j += 2
                elif ch == '"':
                    break
                else:
                    buf.append(ch)
                    j += 1
            yield ('S', ''.join(buf))
            i = j + 1
        elif c.isspace():
            i += 1
        else:
            j = i
            while j < n and not s[j].isspace() and s[j] not in '()"':
                j += 1
            yield ('A', s[i:j])
            i = j


def parse(text):
    """Parse into nested lists. Leaves are ('A'|'S', value) tuples."""
    stack, root = [], None
    for kind, val in tokenize(text):
        if kind == 'P' and val == '(':
            node = []
            if stack:
                stack[-1].append(node)
            stack.append(node)
        elif kind == 'P' and val == ')':
            node = stack.pop()
            if not stack:
                root = node
        elif stack:
            stack[-1].append((kind, val))
    return root


def parse_file(path):
    with open(path, encoding='utf-8') as fh:
        return parse(fh.read())


def head(node):
    if isinstance(node, list) and node and isinstance(node[0], tuple):
        return node[0][1]
    return None


def atoms(node):
    """Scalar arguments of a node, excluding its head."""
    return [t[1] for t in node[1:] if isinstance(t, tuple)]


def subs(node, name=None):
    if not node:
        return []
    return [c for c in node[1:]
            if isinstance(c, list) and (name is None or head(c) == name)]


def sub(node, name):
    found = subs(node, name)
    return found[0] if found else None


def a1(node, name, default=''):
    """First scalar of the named child node, or `default`."""
    child = sub(node, name)
    if child is None:
        return default
    vals = atoms(child)
    return vals[0] if vals else default


def arg(node, index, default=''):
    """Positional scalar argument of `node` itself."""
    vals = atoms(node)
    return vals[index] if len(vals) > index else default
