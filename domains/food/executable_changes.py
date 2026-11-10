"""Isolated executable Food-port configuration trials on frozen source and gold.

Reuses the branch's exact proposal validators and deterministic pipeline. Gold is
read only by the unchanged scorer after both runtime arms have executed. No model
calls, production writes, or gold-derived brand registry are made here.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from dataclasses import asdict
from contextvars import ContextVar
from pathlib import Path
from types import SimpleNamespace

import yaml

from domains.food import place_paths as paths
from domains.food.ported import evaluator, parse, pipeline, propose
from taxo.codex_cli import fingerprint, write
from taxo.core.config import ROOT
from taxo.core.schemas import Listing, Node
from taxo.lattice import vocab
from taxo.memory import rules_for
from taxo.tools import checks as shared_checks
from domains.food import checks as food_checks


# Resolve the port's imports privately, preserving every vendored file byte.
# Its original Node/Listing constructors hard-code fragrance; force this adapter's
# Food context without modifying either shared or vendored implementation.
pipeline.evaluator = evaluator
pipeline.Brands, pipeline.parse, pipeline.strip_seq = parse.Brands, parse.parse, parse.strip_seq
pipeline._BRACKET = parse._BRACKET
_SOURCE_ROWS = ContextVar('food_executable_source_rows', default={})
def _source_listing(**kw):
    row = _SOURCE_ROWS.get().get(kw['id'])
    return Listing(**(kw | {'domain': 'food'} | ({'fields': row['fields']} if row else {})))
pipeline.Listing = _source_listing
pipeline.Node = lambda **kw: Node(**(kw | {'domain': 'food', 'level': kw.get('level') or 'product'}))
propose.evaluator = evaluator
propose.OPS = set(evaluator._OPS) | {'missing', 'present'}


def _run_check(name, listing, node, tax, decision=None, **params):
    local = food_checks.CHECKS
    if name not in local:
        return shared_checks.run(name, listing, node, tax, decision, **params)
    fn, default = local[name]
    detail = fn(listing, node, tax, **params)
    return shared_checks.Finding(name, decision or default, detail) if detail else None


# Only the private port validator/evaluator sees local Food capabilities.
_check_proxy = SimpleNamespace(CHECKS=shared_checks.CHECKS | food_checks.CHECKS, run=_run_check)
propose.checks = evaluator.checks = _check_proxy


def contract():
    """The executable proposal schema/language for the caller's pinned CLI role."""
    stale = ('Listings routed to an agent are NOT placed by it in this run: they keep the brand node, so they count as shallower (or\n'
             'no_brand) and they cost an agent call.')
    actual = ('INTEGRATED FOOD EXECUTION: Routed rows are sent to the actual source-only installed CLI placer. '
              'Its code-checked placements or explicit parks become final outputs alongside deterministic free placements. '
              'Candidate final measurements use actual routed calls, never cached placement answers. '
              'The labels agent_title, agent_evidence, agent_siblings and agent_search currently dispatch the same supplied-source CLI placer; '
              'external sibling retrieval and live web search are NOT implemented by these route labels. '
              'The unchanged retained reference may be a prior completed actual run. '
              'SEPARATE CONFIGURATION-ISOLATION DIAGNOSTICS may replay the same cached source-only fallback in both arms; '
              'those replays are labeled diagnostics, are not final integrated measurements, and prove no realized call or dollar savings.')
    if stale not in propose.LANGUAGE:
        raise ValueError('Pinned port language changed; review the Food execution-contract adaptation')
    cohort_language = ('\nCONFIGURATION COHORT SCOPE: Isolated executable YAML supports a top-level '
        'cohort_scope=selected (default) or original_source. original_source counts source-only cohorts '
        'from the hash-verified original corpus, using only observation_key/source_id/brand_name/listing_name '
        'for nonselected observations. Only the selected observations are emitted and scored. '
        'This is a top-level pipeline dataflow option, not a vocabulary settings key; it is preserved '
        'when subsequent vocabulary/rule candidates are evaluated. No gold registry or extra scored labels are imported.')
    return {'schema': copy.deepcopy(propose.SCHEMA), 'language': propose.LANGUAGE.replace(stale, actual)+cohort_language,
            'source': json.loads(Path(__file__).with_name('ported').joinpath('provenance.json').read_text(encoding='utf-8'))}


def check_catalog():
    """A fresh view of checks actually registered in this private Food executor."""
    return dict(_check_proxy.CHECKS)


def _cohort_scope(config):
    scope = (config or {}).get('cohort_scope', 'selected')
    if scope not in ('selected', 'original_source'):
        raise ValueError('cohort_scope must be selected or original_source')
    return scope


def _cohort_source(selected, scope):
    """Expand count context from the already hash-verified four-column index."""
    if scope == 'selected':
        return selected, {'cohort_scope': scope, 'source_rows': len(selected),
                          'selected_output_rows': len(selected), 'scoring_target_rows': len(selected),
                          'gold_reads': 0, 'nonselected_columns': []}
    if scope != 'original_source':
        raise ValueError('Unknown cohort scope')
    index = paths._source_brand_index(selected[0])
    rich = {r['id']: r for r in selected}
    for row in selected:
        original = index['by_id'].get(row['id'])
        raw = row['fields']['raw_source']
        if original is None or (original['source_id'], original['listing_name'], original['brand_name']) != (
                row.get('source'), row['title'], raw.get('brand_name')) or row.get('brand') != original['brand_name']:
            raise ValueError('Selected rich row differs from original four-column source')
        if Path(row['fields']['source_path']).resolve() != Path(index['provenance']['corpus']['path']).resolve():
            raise ValueError('Selected rows do not share the same original source corpus')
        if row['fields']['source_manifest']['sha256']['listings'] != index['provenance']['corpus']['sha256']:
            raise ValueError('Selected original source manifest checksum differs')
    cohort = []
    for lid, original in index['by_id'].items():
        if lid in rich:
            cohort.append(rich[lid])
        else:
            cohort.append({'id': lid, 'domain': 'food', 'title': original['listing_name'] or '',
                           'source': original['source_id'], 'brand': original['brand_name'],
                           'fields': {'raw_source': dict(original)}})
    return cohort, {'cohort_scope': scope, 'source_rows': len(cohort),
                    'selected_output_rows': len(selected), 'scoring_target_rows': len(selected),
                    'gold_reads': 0, 'nonselected_columns': list(paths.SOURCE_BRAND_COLUMNS),
                    'original_source': index['provenance'],
                    'registry_authority': 'Unverified raw claims and citation-validated selected warm brand nodes; no gold registry'}


def materialize_cohort_config(output, *, base_config=None, cohort_scope='original_source'):
    """Write an isolated candidate config; never edit retained/shared defaults."""
    output = Path(output)
    if base_config is None:
        config = {'vocab': yaml.safe_load((ROOT/'domains/food/vocab.yaml').read_text(encoding='utf-8')) or {},
                  'rules': [asdict(r) for r in evaluator.load(ROOT/'rules/food', ROOT/'rules/global')]}
    else:
        config = copy.deepcopy(yaml.safe_load(Path(base_config).read_text(encoding='utf-8')))
    config['cohort_scope'] = cohort_scope
    _cohort_scope(config)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as stream:
        stream.write('# Isolated source-cohort candidate; production_admission=false\n'+yaml.safe_dump(config, sort_keys=False))
    return output


def _normalise(proposal):
    if 'payload_json' not in proposal:
        return proposal
    payload = json.loads(proposal['payload_json'])
    if not isinstance(payload, dict):
        raise ValueError('payload_json must encode an object')
    kind = proposal['kind']
    base = {'kind': kind, 'label': proposal.get('id') or proposal.get('description') or kind,
            'shape': proposal.get('description', ''), 'why': proposal.get('rationale', '')}
    if kind == 'vocab':
        if set(payload) == {'axis', 'op', 'tokens'}:
            if payload['op'] not in ('add', 'remove'):
                raise ValueError('vocab op must be add or remove')
            axis, op = payload['axis'], payload['op']
            patch = {f'strip_{op}': payload['tokens']} if axis == 'strip' else {
                f'variant_{op}': {axis: payload['tokens']}}
        elif payload and set(payload) <= {'strip_add', 'strip_remove', 'variant_add', 'variant_remove', 'settings'}:
            patch = payload
        else:
            raise ValueError('vocab payload must use axis/op/tokens or the exact Food-port vocabulary patch keys')
    elif kind == 'code_rule':
        if proposal.get('decision') not in ('veto', 'abstain') or set(payload)-{'params'}:
            raise ValueError('Executable code_rule requires veto/abstain and declared check params only')
        patch = {'id': proposal['id'], 'stage': 'place',
                 'when': [{'check': proposal['check'], 'params': payload.get('params') or {}}],
                 'then': {'veto': True, 'route': 'agent_evidence'}, 'why': base['why']}
        base['kind'] = 'rule'
    elif kind == 'route':
        conditions = payload.get('when', payload.get('conditions'))
        if set(payload) - {'when', 'conditions', 'route', 'then'} or ('when' in payload and 'conditions' in payload):
            raise ValueError('route accepts when/conditions and route/then only')
        if ('route' in payload) == ('then' in payload):
            raise ValueError('route requires exactly one route or then action')
        patch = {'id': proposal['id'], 'stage': 'route', 'when': conditions,
                 'then': payload.get('then', {'route': payload.get('route')}), 'why': base['why']}
        base['kind'] = 'rule'
    else:
        raise ValueError(f'{kind} requires its dedicated implementation/source/actual-agent handler; not a vocabulary/routing patch')
    return base | {'patch': yaml.safe_dump(patch, sort_keys=False)}


def _registry(source, baseline, rules, *, exclude_placeholders=False):
    names, origins = {}, []
    by_id = {r['id']: r for r in source}
    def add(name, origin):
        if exclude_placeholders and not paths._positive_source_brand(name):
            return
        key = '_'.join(vocab.tokens(name))
        if key:
            names.setdefault(key, name)
            origins.append({'registry_key': key, 'name': name, **origin})
    for row in source:
        if row.get('brand') and (not exclude_placeholders or row.get('source')):
            add(row['brand'], {'kind': 'unverified_original_brand_field', 'source_id': row['id']})
    for node in paths.rows(baseline/'nodes.jsonl'):
        if node.get('level') != 'brand' or node.get('path') != [node.get('name')]:
            continue
        fields = node.get('fields') or {}
        row = by_id.get(fields.get('source_listing_id'))
        if not row:
            continue
        part = paths.Part(level='brand', name=node['name'], evidence=fields.get('evidence') or [])
        answer = paths.Proposal(listing_id=row['id'], action='place', nodes=[part], confidence=0, reason='Revalidate warm-start source citations')
        grounded, _, findings = paths.materialize(answer, row, rules)
        if grounded == [node['name']]:
            add(node['name'], {'kind': 'model_derived_unverified_warm_start', 'node_id': node['id'],
                              'source_id': row['id'], 'citations': fields.get('evidence'), 'checks': findings})
    return names, origins


def _final_free_rules(rules):
    """Only the explicitly qualified singleton omission check has a final hook."""
    result = []
    for rule in rules:
        if rule.status != 'active' or rule.stage != 'place':
            continue
        matches = [c for c in rule.when if isinstance(c, dict) and c.get('check') == 'source_flavour_omitted']
        if not matches:
            continue
        if (len(rule.when) != 1 or set(matches[0])-{'check', 'params'} or
            matches[0].get('params', {}) != {} or
            not isinstance(rule.then, dict) or set(rule.then) != {'veto', 'route'} or
            rule.then.get('veto') is not True or rule.then.get('route') not in propose.AGENT_ROUTES):
            raise ValueError('Final source_flavour_omitted hook requires one exact check with empty params and veto/agent-route action')
        result.append(rule)
    return result


def _free_decision(item, source, final_rules):
    """One source-only final free/routed decision shared by both execution paths."""
    unsupported_family = len(item.path) > 3 or (len(item.path) == 3 and '+variant' not in item.reason)
    permitted = paths.evidence(source)
    source_words = set().union(*(paths.tokens(v) for v in permitted.values() if isinstance(v, str)))
    path_words = set().union(*(paths.tokens(n) for n in item.path))
    ungrounded = bool(path_words-source_words)
    needs_agent = item.route in propose.AGENT_ROUTES or not item.path or unsupported_family or ungrounded
    route = item.route or ('agent_evidence' if needs_agent else 'deterministic')
    reason = ('ungrounded_free_name' if ungrounded else
              'unsupported_food_family_grouping' if unsupported_family else item.reason)
    hook = None
    if not needs_agent and final_rules:
        node = Node(id='final-free-context', domain='food', name=item.path[-1], path=list(item.path),
                    level=('brand', 'model', 'variant')[len(item.path)-1])
        listing = Listing.model_validate(source)
        for rule in final_rules:
            finding = _run_check('source_flavour_omitted', listing, node, {}, 'abstain')
            if finding is not None:
                needs_agent, route, reason = True, 'agent_evidence', 'final_free_source_flavour_omitted'
                hook = {'rule': rule.id, 'check': finding.check, 'detail': finding.detail}
                break
    return {'routed': needs_agent, 'route': route, 'reason': reason, 'final_free_hook': hook}


def _runtime(source, registry, doc, rules, cache, folder, *, cohort=None, cohort_provenance=None):
    folder.mkdir()
    vpath = folder/'vocab.yaml'
    vpath.write_text('# Isolated development configuration; not production admission.\n'+yaml.safe_dump(doc, sort_keys=False), encoding='utf-8')
    names = parse.Brands(registry, tuple(doc.get('brand_drop_suffixes') or ()),
                        shop_brand=bool((doc.get('settings') or {}).get('shop_brand')))
    context = source if cohort is None else cohort
    selected_ids = {r['id'] for r in source}
    items = [pipeline.Item(id=r['id'], title=r['title'], source=r.get('source') or '',
                brand_field=r.get('brand'), maker_field=r['fields']['raw_source'].get('manufacturer_name'),
                url=r['fields']['raw_source'].get('url'), variant_field=r['fields']['raw_source'].get('variant_name')) for r in context]
    source_by_id = {r['id']: r for r in context}
    final_rules = _final_free_rules(rules)
    context_token = _SOURCE_ROWS.set(source_by_id)
    try:
        stats = pipeline.run(items, names, vocab.load(vpath), rules)
    finally:
        _SOURCE_ROWS.reset(context_token)
    predictions, traces = [], []
    cached = routed = 0
    for item in items:
        if item.id not in selected_ids:
            continue
        decision = _free_decision(item, source_by_id[item.id], final_rules)
        wants_agent = decision['routed']
        routed += wants_agent
        if wants_agent:
            # Same already source-grounded fallback answer in both arms. This is
            # offline replay, not an actual fresh call or realized cost saving.
            pred = copy.deepcopy(cache[item.id])
            pred.update(route=decision['route'], execution_status='cached_source_only_fallback',
                        by='cached_retained_placer')
            cached += 1
        else:
            pred = {'id': item.id, 'path': list(item.path), 'route': decision['route'],
                    'by': 'food_port_deterministic', 'node_id': None, 'confidence': None,
                    'reason': decision['reason'], 'status': 'unadmitted_experiment', 'execution_status': 'offline_free_pipeline'}
        predictions.append(pred)
        traces.append({'id': item.id, 'free_path': item.path, 'brand_how': item.brand_how,
                       'step': item.step, 'reason': decision['reason'], 'rule': item.rule,
                       'route': decision['route'], 'cluster': item.cluster, 'cluster_n': item.cluster_n,
                       'final_free_hook': decision['final_free_hook'],
                       'shadow': item.shadow, 'cached_fallback': wants_agent})
    paths.dump_rows(folder/'placements.jsonl', predictions)
    paths.dump_rows(folder/'rule-events.jsonl', traces)
    return {'fresh_model_calls': 0, 'cached_fallback_rows': cached,
            'counterfactual_agent_routes': routed, 'source_rows': len(source), 'lattice': stats,
            'counterfactual_agent_share': routed/len(source), 'cohort': cohort_provenance or {'cohort_scope': 'selected', 'source_rows': len(source)}}


def build_plan(root, fallback, config_path, output):
    """Run the final system's free stages BEFORE gold; route every unresolved row.

    ``fallback`` supplies citation-revalidated brand memory only. Its placement
    answers are never loaded. ``config_path=None`` retains route-all-agent;
    otherwise an isolated YAML ``{vocab, rules}`` runs the exact port pipeline.
    Actual agent execution belongs to the caller on ``routed_ids`` only.
    """
    root, fallback, output = Path(root), Path(fallback), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    provenance = contract()['source']
    for entry in provenance['files']:
        if fingerprint(Path(__file__).with_name('ported')/entry['file'])['sha256'] != entry['sha256']:
            raise ValueError('Vendored Food-port implementation drift')
    protocol = paths.read(root/'protocol.json')
    source_path = Path(protocol['source']['path'])
    if fingerprint(source_path)['sha256'] != protocol['source']['sha256']:
        raise ValueError('Frozen source drift')
    source = paths.rows(source_path)
    if not source or len({r['id'] for r in source}) != len(source):
        raise ValueError('Plan source must have unique nonempty membership')
    warm = paths.read(fallback/'manifest.json')
    if warm['status'] != 'completed' or warm['source']['sha256'] != protocol['source']['sha256']:
        raise ValueError('Warm brand memory must belong to this exact completed source run')
    config = None if config_path is None else yaml.safe_load(Path(config_path).read_text(encoding='utf-8'))
    if config is not None and (not isinstance(config, dict) or not isinstance(config.get('vocab'), dict)
                               or not isinstance(config.get('rules'), list)):
        raise ValueError('Candidate config requires vocabulary mapping and executable rules list')
    scope = _cohort_scope(config)
    cohort, cohort_provenance = _cohort_source(source, scope)
    registry, origins = _registry(cohort, fallback, rules_for('food', ('consumer_packaged',)),
                                  exclude_placeholders=scope == 'original_source')
    write(output/'source-only-registry.json', {'names': registry, 'provenance': origins,
          'authority': 'Unverified original fields and citation-validated brand nodes; no model placement answers or gold'})
    free, routed, trace, nodes = [], [], [], {}
    if config_path is None:
        routed = [r['id'] for r in source]
        trace = [{'id': r['id'], 'route': 'agent_evidence', 'reason': 'retained_route_all_agent'} for r in source]
        stats = {}
    else:
        config_path = Path(config_path)
        rules = [evaluator.Rule(**r) for r in config['rules']]
        final_rules = _final_free_rules(rules)
        for rule in rules:
            if rule.stage not in propose.FACTS or rule.status not in ('active', 'shadow', 'proposal', 'retired'):
                raise ValueError('Unsupported executable rule stage or status')
        vpath = output/'vocab.yaml'
        vpath.write_text(yaml.safe_dump(config['vocab'], sort_keys=False), encoding='utf-8')
        names = parse.Brands(registry, tuple(config['vocab'].get('brand_drop_suffixes') or ()),
                            shop_brand=bool((config['vocab'].get('settings') or {}).get('shop_brand')))
        items = [pipeline.Item(id=r['id'], title=r['title'], source=r.get('source') or '',
                    brand_field=r.get('brand'), maker_field=r['fields']['raw_source'].get('manufacturer_name'),
                    url=r['fields']['raw_source'].get('url'), variant_field=r['fields']['raw_source'].get('variant_name')) for r in cohort]
        source_by_id = {r['id']: r for r in cohort}
        selected_ids = {r['id'] for r in source}
        token = _SOURCE_ROWS.set(source_by_id)
        try:
            stats = pipeline.run(items, names, vocab.load(vpath), rules)
        finally:
            _SOURCE_ROWS.reset(token)
        for item in items:
            if item.id not in selected_ids:
                continue
            decision = _free_decision(item, source_by_id[item.id], final_rules)
            needs_agent, route, reason = decision['routed'], decision['route'], decision['reason']
            trace.append({'id': item.id, 'free_candidate_path': item.path, 'route': route,
                          'reason': reason, 'step': item.step, 'rule': item.rule,
                          'cluster_n': item.cluster_n, 'routed': needs_agent,
                          'final_free_hook': decision['final_free_hook']})
            if needs_agent:
                routed.append(item.id)
                continue
            parent_id = None
            for index, label in enumerate(item.path):
                path = list(item.path[:index+1])
                nid = 'food:free:' + hashlib.sha256(json.dumps(path, ensure_ascii=False).encode()).hexdigest()[:20]
                nodes.setdefault(nid, Node(id=nid, domain='food', name=label, path=path,
                    level=('brand', 'model', 'variant')[index], parent_id=parent_id,
                    fields={'status': 'proposal', 'source_listing_id': item.id,
                            'generator': 'source_only_food_port'}).model_dump(mode='json'))
                parent_id = nid
            free.append({'id': item.id, 'path': list(item.path), 'node_id': parent_id,
                         'route': 'deterministic', 'reason': reason, 'confidence': None,
                         'by': 'food_port_free_pipeline', 'status': 'proposal',
                         'execution_status': 'completed_free_pipeline'})
    for node in nodes.values():
        node['children'] = [n['id'] for n in nodes.values() if n['parent_id'] == node['id']]
    ids = {r['id'] for r in source}
    if {r['id'] for r in free} & set(routed) or {r['id'] for r in free} | set(routed) != ids:
        raise ValueError('Free and routed partitions must disjointly cover the source')
    plan = {'free_placements': free, 'routed_ids': routed, 'nodes': list(nodes.values()),
            'source_only_registry': registry, 'registry_provenance': fingerprint(output/'source-only-registry.json'),
            'source': fingerprint(source_path), 'source_port': provenance, 'lattice': stats,
            'config': fingerprint(Path(config_path)) if config_path is not None else None,
            'retained_route_all': config_path is None, 'fresh_model_calls': 0,
            'cached_fallback_answers_used': 0, 'gold_reads': 0, 'production_admission': False,
            'adapter': fingerprint(Path(__file__)), 'cohort': cohort_provenance}
    write(output/'plan.json', plan)
    paths.dump_rows(output/'rule-events.jsonl', trace)
    return plan


def evaluate(proposal: dict, root: Path, baseline: Path, output: Path, *, base_config=None) -> dict:
    """Apply a genuine config proposal, replay both arms, score paired frozen gold.

    All output lives in a fresh isolated directory. Shared/default configuration
    never changes; rollback.yaml contains the original executable configuration.
    """
    root, baseline, output = Path(root), Path(baseline), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    provenance = contract()['source']
    for item in provenance['files']:
        if fingerprint(Path(__file__).with_name('ported')/item['file'])['sha256'] != item['sha256']:
            raise ValueError('Vendored Food-port implementation drift')
    protocol = paths.read(root/'protocol.json')
    source_path = Path(protocol['source']['path'])
    if fingerprint(source_path)['sha256'] != protocol['source']['sha256']:
        raise ValueError('Frozen source drift')
    baseline_manifest = paths.read(baseline/'manifest.json')
    if baseline_manifest['status'] != 'completed' or baseline_manifest['source']['sha256'] != protocol['source']['sha256']:
        raise ValueError('Fallback must be a completed source-only run on exactly this source snapshot')
    source = paths.rows(source_path)
    cache = {r['id']: r for r in paths.rows(baseline/'placements.jsonl')}
    if len(cache) != len(source) or set(cache) != {r['id'] for r in source}:
        raise ValueError('Cached fallback/source membership mismatch')
    specs = rules_for('food', ('consumer_packaged',))
    vpath = ROOT/'domains/food/vocab.yaml'
    doc = yaml.safe_load(vpath.read_text(encoding='utf-8')) or {}
    rules = evaluator.load(ROOT/'rules/food', ROOT/'rules/global')
    retained = {}
    if base_config is not None:
        retained = yaml.safe_load(Path(base_config).read_text(encoding='utf-8'))
        doc = retained['vocab']
        rules = [evaluator.Rule(**r) for r in retained['rules']]
    scope = _cohort_scope(retained)
    cohort, cohort_provenance = _cohort_source(source, scope)
    registry, origins = _registry(cohort, baseline, specs, exclude_placeholders=scope == 'original_source')
    write(output/'source-only-registry.json', {'names': registry, 'provenance': origins,
          'authority': 'unverified original fields and citation-revalidated model proposals; never gold'})
    config = copy.deepcopy(retained) | {'vocab': doc, 'rules': [asdict(r) for r in rules], 'cohort_scope': scope}
    (output/'rollback.yaml').write_text(yaml.safe_dump(config, sort_keys=False), encoding='utf-8')
    write(output/'proposal.json', proposal)
    feedback = set(protocol['partition']['feedback_ids'])
    titles = {}
    spread_source = cohort if scope == 'original_source' else source
    spread_brands = parse.Brands(registry)
    considered = 0
    for row in spread_source:
        if scope == 'selected' and row['id'] not in feedback:
            continue
        considered += 1
        # Support is source-only; never borrow the gold's brand assignment.
        key = spread_brands.find(parse.parse(row['title']), row.get('brand'), None, row.get('source'))[0]
        if key:
            titles.setdefault(key, []).append(' '+' '.join(vocab.tokens(row['title']))+' ')
    support_provenance = {'cohort_scope': scope, 'source_rows_considered': considered,
                          'source_brand_groups': len(titles), 'gold_brand_assignments_used': False,
                          'original_source': cohort_provenance.get('original_source')}
    write(output/'proposal-support-provenance.json', support_provenance)
    bench = SimpleNamespace(d='food', spread=lambda phrase: sum(any(' '+phrase+' ' in title for title in ts)
                                                               for ts in titles.values()))
    runtime_proposal = proposal
    if proposal.get('kind') == 'new_check' and proposal.get('check') in food_checks.CHECKS:
        runtime_proposal = proposal | {'kind': 'code_rule', 'payload_json': '{"params":{}}'}
    if proposal.get('kind') == 'new_check' and runtime_proposal is proposal:
        refusal = 'Missing check requires implementation with documented positive/negative cases, then an actual controlled evaluation'
        write(output/'implementation-proposal.json', {'status': 'implementation_needed', 'proposal': proposal,
              'requirements': ['Specify input facts and failure mechanism', 'Provide positive and negative cases before implementation',
                               'Run the registered check in shadow against authorized gold; no fabricated code']})
        result = {'status': 'implementation_needed', 'reason': refusal, 'fresh_model_calls': 0, 'production_admission': False,
                  'cohort': cohort_provenance, 'proposal_phrase_support': support_provenance}
        write(output/'report.json', result)
        return result
    try:
        normalised = _normalise(runtime_proposal)
        write(output/'normalised-port-proposal.json', normalised)
        candidate_doc, candidate_rules, applied = propose.apply(bench, normalised, doc, rules)
    except (propose.Refused, ValueError, TypeError) as error:
        result = {'status': 'refused', 'reason': str(error), 'fresh_model_calls': 0, 'production_admission': False,
                  'cohort': cohort_provenance, 'proposal_phrase_support': support_provenance,
                  'missing_check_next_step': 'Submit kind=new_check with positive/negative cases' if 'unknown check' in str(error) else None}
        write(output/'report.json', result)
        return result
    (output/'candidate-config.yaml').write_text('# EXPERIMENTAL ONLY; production_admission=false\n'+
        yaml.safe_dump(config | {'vocab': candidate_doc, 'rules': [asdict(r) for r in candidate_rules]}, sort_keys=False), encoding='utf-8')
    # Run both executable configurations before gold is opened by the scorer.
    before = _runtime(source, registry, doc, rules, cache, output/'reference', cohort=cohort, cohort_provenance=cohort_provenance)
    after = _runtime(source, registry, candidate_doc, candidate_rules, cache, output/'candidate', cohort=cohort, cohort_provenance=cohort_provenance)
    before_metrics = paths.score(root, output/'reference', paths.rows(output/'reference/placements.jsonl'), baseline)
    after_metrics = paths.score(root, output/'candidate', paths.rows(output/'candidate/placements.jsonl'), output/'reference')
    retained_metrics = paths.read(baseline/'metrics.json')
    keep = after_metrics['identity_path_exact'] > before_metrics['identity_path_exact'] and all(
        after_metrics[k] >= max(before_metrics[k], retained_metrics[k])
        for k in ('identity_path_exact', 'strict_full_path_exact', 'brand_correct'))
    unchanged = sum(a['path'] == b['path'] and a['route'] == b['route'] for a,b in zip(
        paths.rows(output/'reference/placements.jsonl'), paths.rows(output/'candidate/placements.jsonl')))
    result = {'status': 'evaluated_offline_executable_config', 'source_port': provenance,
        'proposal_kind': proposal['kind'], 'applied': applied, 'before': before_metrics, 'after': after_metrics,
        'paired': after_metrics['paired'], 'runtime_before': before, 'runtime_after': after,
        'unchanged_rows': unchanged, 'fresh_model_calls': 0, 'production_admission': False,
        'keep_for_development': keep,
        'decision_reason': ('Exact gain without sacrificing retained-baseline exact, strict, or brand recovery' if keep else
                            'No qualifying improvement over both the executable reference and retained source-only pipeline'),
        'retained_pipeline_metrics': retained_metrics,
        'reference_scope': 'New deterministic-plus-cached-fallback reference, not a replacement for the retained pipeline',
        'gold_scope': 'Previously inspected development feedback/scoring; no sealed gate',
        'runtime_brands': 'Citation-revalidated source-only warm-start memory plus original source brand fields',
        'actual_cost_claim': None, 'counterfactual_route_delta': after['counterfactual_agent_routes']-before['counterfactual_agent_routes'],
        'shared_defaults_mutated': False, 'rollback': fingerprint(output/'rollback.yaml'),
        'cohort': cohort_provenance,
        'proposal_phrase_support': support_provenance,
        'source': fingerprint(source_path), 'fallback': fingerprint(baseline/'placements.jsonl'),
        'adapter': fingerprint(Path(__file__)), 'local_checks': fingerprint(Path(food_checks.__file__)),
        'registry': fingerprint(output/'source-only-registry.json')}
    write(output/'report.json', result)
    write(output/'artifact-index.json', [fingerprint(p) for p in sorted(output.rglob('*'))
                                         if p.is_file() and p != output/'artifact-index.json'])
    return result


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--proposal', type=Path, required=True)
    ap.add_argument('--root', type=Path, required=True)
    ap.add_argument('--baseline', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    print(json.dumps(evaluate(paths.read(a.proposal), a.root, a.baseline, a.output), ensure_ascii=False))
