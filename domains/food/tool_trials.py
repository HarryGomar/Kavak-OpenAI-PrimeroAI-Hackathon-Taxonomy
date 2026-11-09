"""Candidate Food tools: source-only subprocess trials and ordinary CLI-callable adapters.

This is a restricted code contract plus process/timeout isolation, not an operating-system
security sandbox. Candidate wrappers are local to an A/B arm; this module never edits
validator.yaml or admits a production tool.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json
import math
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace


ALLOWED_MODULES = {'re', 'json', 'math', 'unicodedata', 'collections'}
BLOCKED_CALLS = {'open', 'exec', 'eval', 'compile', 'input', 'getattr', 'setattr', 'delattr',
                 'globals', 'locals', 'vars', 'dir', 'breakpoint', '__import__'}
CONTEXT_FIELDS = ('domain', 'brands', 'listing_id', 'source_evidence', 'listing')
SOURCE_FIELDS = ('listing_id', 'source', 'title', 'source_reported_brand', 'description_text',
                 'flavor_text', 'food_form_text', 'ingredients_text', 'dietary_claims_json',
                 'package_text', 'category_path_json', 'seller_name', 'organizations_json',
                 'variant_options_json', 'variant_name')


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str)+'\n', encoding='utf-8')


def source_context(context=None):
    """Project only source-bearing fields; never serialize the whole role context."""
    context = context or {}
    if hasattr(context, 'context'):
        context = context.context
    get = context.get if isinstance(context, dict) else lambda k, d=None: getattr(context, k, d)
    result = {k: get(k) for k in CONTEXT_FIELDS if get(k) is not None}
    def project(listing):
        if hasattr(listing, 'model_dump'):
            listing = listing.model_dump(mode='json')
        if isinstance(listing, list):
            return [project(row) for row in listing]
        if not isinstance(listing, dict):
            raise ValueError('Tool listing evidence must be a source object or list')
        if 'fields' in listing and 'id' in listing:
            from domains.food.place_paths import evidence
            listing = evidence(listing)
        return {k: listing[k] for k in SOURCE_FIELDS if k in listing}
    for key in ('listing', 'source_evidence'):
        if key in result:
            result[key] = project(result[key])
    # The caller supplies source evidence, not a raw context with scorer state.
    return json.loads(json.dumps(result, ensure_ascii=False))


def _contract(code, name):
    if not isinstance(name, str) or not name.isidentifier() or name.startswith('_'):
        raise ValueError('Tool name must be a public Python identifier')
    tree = ast.parse(code)
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    if name not in functions:
        raise ValueError('Proposed tool function is missing')
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.AsyncFunctionDef, ast.Global, ast.Nonlocal, ast.With,
                             ast.AsyncWith, ast.Lambda)):
            raise ValueError(f'Unsupported candidate code construct: {type(node).__name__}')
        if isinstance(node, ast.Attribute) and node.attr.startswith('_'):
            raise ValueError('Private/reflection attributes are unavailable')
        if isinstance(node, ast.Name) and node.id.startswith('__'):
            raise ValueError('Private/reflection names are unavailable')
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALLS:
            raise ValueError(f'Unavailable callable: {node.func.id}')
        if isinstance(node, ast.Import) and any(a.name not in ALLOWED_MODULES for a in node.names):
            raise ValueError('Only source-analysis standard-library imports are available')
        if isinstance(node, ast.ImportFrom):
            compat = (node.module == 'agents' and all(a.name in {'function_tool', 'RunContextWrapper'} for a in node.names)) or (
                node.module == 'taxo.roles.validator' and all(a.name == 'ValidateContext' for a in node.names)) or (
                node.module == '__future__' and all(a.name == 'annotations' for a in node.names))
            if not compat and (node.level or node.module not in ALLOWED_MODULES):
                raise ValueError(f'Unavailable import: {node.module}')
    body = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module in ('agents', 'taxo.roles.validator', '__future__'):
            continue  # SDK decorators/types are compatibility markers, never SDK execution.
        if isinstance(node, ast.FunctionDef):
            if any(not isinstance(d, ast.Name) or d.id != 'function_tool' for d in node.decorator_list):
                raise ValueError('Only the optional @function_tool marker is supported')
            node.decorator_list = []
            for default in node.args.defaults + [d for d in node.args.kw_defaults if d is not None]:
                ast.literal_eval(default)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            ast.literal_eval(node.value)
        elif not isinstance(node, (ast.Import, ast.ImportFrom)) and not (
            isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            raise ValueError('Top-level candidate execution is unavailable')
        body.append(node)
    tree.body = body
    fn = functions[name]
    if fn.args.posonlyargs or fn.args.vararg or fn.args.kwarg or not fn.args.args or fn.args.args[0].arg != 'ctx':
        raise ValueError('Tool signature must be (ctx, explicit JSON arguments), without variadic arguments')
    positional = fn.args.args
    defaults = [inspect.Parameter.empty]*(len(positional)-len(fn.args.defaults)) + [ast.literal_eval(d) for d in fn.args.defaults]
    parameters = [inspect.Parameter(a.arg, inspect.Parameter.POSITIONAL_OR_KEYWORD, default=d)
                  for a, d in zip(positional, defaults)]
    parameters += [inspect.Parameter(a.arg, inspect.Parameter.KEYWORD_ONLY,
                   default=inspect.Parameter.empty if d is None else ast.literal_eval(d))
                   for a, d in zip(fn.args.kwonlyargs, fn.args.kw_defaults)]
    return ast.fix_missing_locations(tree), inspect.Signature(parameters), ast.get_docstring(fn) or ''


def _execute(code, name, arguments, context, timeout):
    _contract(code, name)[1].bind(None, **arguments)
    payload = {'code': code, 'name': name, 'arguments': arguments, 'context': source_context(context)}
    result = subprocess.run([sys.executable, '-I', str(Path(__file__).resolve()), '--worker'],
                            input=json.dumps(payload), capture_output=True, text=True, encoding='utf-8', timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'Candidate tool worker failed: {result.stderr[-1000:]}')
    return json.loads(result.stdout)


def _arguments(value):
    value = json.loads(value) if isinstance(value, str) else value
    if not isinstance(value, dict):
        raise ValueError('fires_on/quiet_on must be JSON argument objects')
    return value


def try_tool(change, output, context=None, *, timeout=5):
    """Run the actual proposed implementation on its declared fire/quiet argument cases."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    report = {'accepted': False, 'production_admission': False, 'tool_name': change.get('tool_name'),
              'case_origin': 'model-authored probe cases; not gold or held-out accuracy', 'timeout_seconds': timeout,
              'context_contract': list(CONTEXT_FIELDS)}
    _write(output/'proposal.json', change)
    try:
        name, code = change.get('tool_name'), change.get('code') or ''
        _contract(code, name)
        (output/'candidate.py').write_text(code, encoding='utf-8')
        cases = {k: _arguments(change.get(k)) for k in ('fires_on', 'quiet_on')}
        if cases['fires_on'] == cases['quiet_on']:
            raise ValueError('Fire and quiet probes must have different inputs')
        results = {k: _execute(code, name, args, context, timeout) for k, args in cases.items()}
        def flagged(value):
            return value if isinstance(value, bool) else value.get('flagged') if isinstance(value, dict) else None
        fire, quiet = map(flagged, (results['fires_on'], results['quiet_on']))
        explicit = isinstance(fire, bool) and isinstance(quiet, bool)
        if explicit and (not fire or quiet):
            raise ValueError('Tool must flag fires_on=True and quiet_on=False')
        if not explicit and results['fires_on'] == results['quiet_on']:
            raise ValueError('Fire and quiet probes returned identical outputs')
        report.update(accepted=True, source=str((output/'candidate.py').resolve()), results=results,
                      source_sha256=hashlib.sha256(code.encode('utf-8')).hexdigest(),
                      semantic_probe_status='fire_true_quiet_false' if explicit else 'distinct_outputs_semantics_need_review',
                      semantic_review_required=not explicit,
                      reason='Implementation executed on both declared cases; paired real-data A/B still required')
    except Exception as error:
        report.update(reason=f'{type(error).__name__}: {error}')
    _write(output/'report.json', report)
    return report


def load_tool(report_path):
    """An isolated callable for one candidate arm; compatible with run_sync's tool dispatcher."""
    report_path = Path(report_path)
    report = json.loads(report_path.read_text(encoding='utf-8'))
    if not report.get('accepted'):
        raise ValueError('Cannot load a refused candidate tool')
    code = Path(report['source']).read_text(encoding='utf-8')
    if hashlib.sha256(code.encode('utf-8')).hexdigest() != report['source_sha256']:
        raise ValueError('Candidate tool changed after its declared-case trial')
    name = report['tool_name']
    _, signature, doc = _contract(code, name)
    def tool(ctx, **kwargs):
        return _execute(code, name, kwargs, ctx, report['timeout_seconds'])
    tool.__name__, tool.__doc__, tool.__signature__ = name, doc, signature
    return tool


def apply_change(setup, change, tool_report=None):
    """Return an experimental setup copy; refusal/rejection never mutates the current setup."""
    kind = change.get('kind')
    if kind not in ('question', 'checklist_step', 'tool'):
        return None
    if kind == 'tool' and (not tool_report or not tool_report.get('accepted')):
        return None
    question = change.get('question_id') or change.get('step_id') or (
        f"use_{change['tool_name']}" if kind == 'tool' else None)
    ask = change.get('ask') or change.get('text')
    if not question or not ask:
        return None
    result = copy.deepcopy(setup)
    entry = {'id': question, 'ask': ask, 'tools': list(change.get('tools') or []),
             'then': change.get('then'), 'status': 'proposal'}
    if kind == 'tool':
        entry['tools'] = sorted(set(entry['tools']) | {change['tool_name']})
    questions = [q for q in result.get('questions', []) if q['id'] != question]
    index = next((i+1 for i, q in enumerate(questions) if q['id'] == change.get('after')), len(questions))
    result.update(version=int(setup.get('version', 1))+1, use_proposals=True,
                  questions=questions[:index]+[entry]+questions[index:], production_admission=False)
    return result


def compare_paired(current, candidate):
    """Fragrance's paired exact/harm/abstain decision, requiring identical answered membership."""
    if set(current) != set(candidate) or not current:
        raise ValueError('Paired arms must cover the same nonempty observation IDs')
    ids = sorted(current)
    n = len(ids)
    result = {'n': n}
    def wilson(count):
        p, z = count/n, 1.96
        center = (p+z*z/(2*n))/(1+z*z/n)
        half = z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/(1+z*z/n)
        return [center-half, center+half]
    for metric in ('exact', 'harm', 'abstain'):
        a, b = sum(bool(current[i][metric]) for i in ids), sum(bool(candidate[i][metric]) for i in ids)
        differences = [int(bool(candidate[i][metric]))-int(bool(current[i][metric])) for i in ids]
        mean = sum(differences)/n
        half = 1.96*math.sqrt(sum((d-mean)**2 for d in differences)/max(n-1, 1))/math.sqrt(n)
        result[metric] = {'current': a/n, 'candidate': b/n, 'delta': mean,
                          'current_ci': wilson(a), 'candidate_ci': wilson(b),
                          'delta_ci': [mean-half, mean+half], 'gains': differences.count(1),
                          'regressions': differences.count(-1)}
    result['keep_for_development'] = result['exact']['delta'] > 0 and result['harm']['delta'] <= 0 and result['abstain']['delta'] <= .05
    result['production_admission'] = False
    return result


def _worker(payload):
    import builtins
    import importlib
    import __future__
    tree, _, _ = _contract(payload['code'], payload['name'])
    allowed = ('bool', 'str', 'int', 'float', 'dict', 'list', 'tuple', 'set', 'frozenset', 'len', 'sorted',
               'sum', 'min', 'max', 'abs', 'all', 'any', 'enumerate', 'range', 'zip', 'isinstance',
               'next', 'reversed', 'round', 'ValueError', 'TypeError', 'KeyError')
    safe = {name: getattr(builtins, name) for name in allowed}
    def imports(name, globals=None, locals=None, fromlist=(), level=0):
        if level or name not in ALLOWED_MODULES:
            raise ImportError(f'Unavailable import: {name}')
        return importlib.import_module(name)
    safe['__import__'] = imports
    namespace = {'__builtins__': safe}
    exec(compile(tree, '<candidate-tool>', 'exec', flags=__future__.annotations.compiler_flag), namespace)
    context = SimpleNamespace(context=SimpleNamespace(**payload['context']))
    return namespace[payload['name']](context, **payload['arguments'])


if __name__ == '__main__' and sys.argv[1:] == ['--worker']:
    print(json.dumps(_worker(json.load(sys.stdin)), ensure_ascii=False))
