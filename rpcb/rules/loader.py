"""Merge built-in rules with a project's optional rpcb.yaml."""
import os

from .spec import CHECK_KINDS, SEVERITY_ORDER

BUILTIN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'builtin.yaml')


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
