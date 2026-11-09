"""Immutable Food development-system versions; execution and paired gates belong to the caller."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import yaml

REPO = Path(__file__).resolve().parents[2]
ROUTING_MODES = {'agent_all', 'rules_then_agent', 'executable_then_agent'}


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _fingerprint(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size}


def _verify(record):
    actual = _fingerprint(record['path'])
    if any(actual[k] != record[k] for k in ('sha256', 'bytes')):
        raise ValueError(f'System component drift: {record["path"]}')


def _exclusive(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)+'\n').encode('utf-8')


def _snapshot(root, value, *, suffix=None):
    origin = str(Path(value).resolve()) if isinstance(value, (str, Path)) else None
    data = Path(value).read_bytes() if origin else _json_bytes(value)
    extension = suffix or (Path(value).suffix if origin else '.json')
    target = root/'system-state/components'/(hashlib.sha256(data).hexdigest()+extension)
    try:
        _exclusive(target, data)
    except FileExistsError:
        if target.read_bytes() != data:
            raise ValueError(f'Content-addressed component collision: {target}')
    return _fingerprint(target) | {'origin_path': origin}


def _frozen_inputs(root):
    protocol = _read(root/'protocol.json')
    source = _fingerprint(protocol['source']['path'])
    scorer = _fingerprint(root/'frozen_scorer.py')
    if source['sha256'] != protocol['source']['sha256'] or scorer['sha256'] != protocol['scorer']['sha256']:
        raise ValueError('Frozen source/scorer differs from the run protocol')
    return source, scorer


def _no_gold_catalog(root, value):
    """Reject explicit answer catalogs/references in executable configuration, never inspect gold itself."""
    protocol = _read(root/'protocol.json')
    forbidden_paths = {str(Path(protocol['gold_rulings']['path']).resolve()),
                       str((root/'frozen-brands.parquet').resolve()), str((root/'frozen-aliases.tsv').resolve())}
    forbidden_keys = {'gold_catalog', 'gold_lookup', 'gold_rulings', 'expected_paths', 'pedia_labels', 'target_catalog'}
    def check(item):
        if isinstance(item, dict):
            if set(item) & forbidden_keys:
                raise ValueError('Gold/target catalogs cannot be executable system state')
            for child in item.values():
                check(child)
        elif isinstance(item, list):
            for child in item:
                check(child)
        elif isinstance(item, str) and item in forbidden_paths:
            raise ValueError('Scoring-only files cannot become runtime catalogs')
    check(value)


def _config(root, value):
    if value is None:
        return None
    if isinstance(value, (str, Path)):
        path = Path(value)
        if path.suffix.lower() in ('.json', '.yaml', '.yml'):
            _no_gold_catalog(root, yaml.safe_load(path.read_text(encoding='utf-8')))
    else:
        _no_gold_catalog(root, value)
    return _snapshot(root, value)


def _tool_reports(root, reports):
    retained = []
    for path in reports:
        report = _read(path)
        if not report.get('accepted'):
            raise ValueError('Refused tool report cannot become active development state')
        source = _fingerprint(report['source'])
        code = Path(report['source']).read_text(encoding='utf-8')
        if hashlib.sha256(code.encode('utf-8')).hexdigest() != report['source_sha256']:
            raise ValueError('Candidate tool implementation changed after qualification')
        frozen_source = _snapshot(root, report['source'])
        frozen_report = report | {'source': frozen_source['path'], 'original_source': source}
        retained.append(_snapshot(root, frozen_report))
    return retained


def _role(root, path, reports):
    data = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    reports = list(reports) or data.get('tool_reports', [])
    frozen_reports = _tool_reports(root, reports)
    if frozen_reports:
        data = data | {'tool_reports': [r['path'] for r in frozen_reports]}
        component = _config(root, data)
        component['origin_path'] = str(Path(path).resolve())
    else:
        component = _config(root, path)
    return component, frozen_reports


def _baseline(root, path):
    path = Path(path).resolve()
    files = {name: _fingerprint(path/name) for name in
             ('manifest.json', 'placements.jsonl', 'metrics.json', 'hypothesis.json') if (path/name).exists()}
    if not {'manifest.json', 'placements.jsonl', 'metrics.json'} <= set(files):
        raise ValueError('Retained baseline requires actual completed execution and metrics')
    manifest = _read(path/'manifest.json')
    if manifest.get('status') not in ('completed', 'completed_integrated_development'):
        raise ValueError('Incomplete/failed baseline cannot become system state')
    source, _ = _frozen_inputs(root)
    if manifest.get('source', {}).get('sha256') != source['sha256']:
        raise ValueError('Baseline was not executed on this frozen source sample')
    return {'path': str(path), 'files': files}


def _publish(root, state):
    directory = root/'system-state'
    version_path = directory/f'v{state["version"]:06d}.json'
    _exclusive(version_path, _json_bytes(state))  # A concurrent/stale version cannot overwrite a winner.
    pointer = _fingerprint(version_path) | {'version': state['version']}
    temporary = directory/f'.current-{uuid4().hex}.json'
    _exclusive(temporary, _json_bytes(pointer))
    os.replace(temporary, directory/'current.json')
    return state


def initialize(root, *, baseline_output, placer_card, validator_setup, extraction=None, lattice=None,
               vocab=None, active_executable_config=None, routing_mode='agent_all',
               placer_tool_reports=(), validator_tool_reports=()):
    root = Path(root).resolve()
    if (root/'system-state/current.json').exists():
        raise FileExistsError('System state already initialized; load or retain a gated candidate')
    if routing_mode not in ROUTING_MODES:
        raise ValueError(f'Unknown routing mode: {routing_mode}')
    source, scorer = _frozen_inputs(root)
    card, placer_tools = _role(root, placer_card, placer_tool_reports)
    setup, validator_tools = _role(root, validator_setup, validator_tool_reports)
    state = {'schema_version': 1, 'version': 1, 'parent_version': None,
             'created_utc': datetime.now(timezone.utc).isoformat(), 'production_admission': False,
             'source': source, 'scorer': scorer,
             'extraction': _snapshot(root, extraction or REPO/'domains/food/place_paths.py'),
             'lattice': _snapshot(root, lattice or REPO/'taxo/lattice/count.py'),
             'vocab': _config(root, vocab or REPO/'domains/food/vocab.yaml'),
             'active_executable_config': _config(root, active_executable_config), 'routing_mode': routing_mode,
             'placer': {'card': card, 'tool_reports': placer_tools},
             'validator': {'setup': setup, 'tool_reports': validator_tools},
             'baseline_output': _baseline(root, baseline_output), 'gate_evidence': None}
    return _publish(root, state)


def load(root, *, verify=True):
    root = Path(root).resolve()
    pointer = _read(root/'system-state/current.json')
    _verify(pointer)
    state = _read(pointer['path'])
    if state['version'] != pointer['version']:
        raise ValueError('Current pointer and versioned system state disagree')
    if verify:
        source, scorer = _frozen_inputs(root)
        if source != state['source'] or scorer != state['scorer']:
            raise ValueError('System state belongs to a different frozen source/scorer')
        def walk(value):
            if isinstance(value, dict):
                if {'path', 'sha256', 'bytes'} <= set(value):
                    _verify(value)
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
        walk(state)
    return state


def retain_candidate(root, changes, *, expected_version, gate_evidence_path):
    """Persist the caller's actually executed candidate after its paired development gates pass."""
    root = Path(root).resolve()
    current = load(root)
    if current['version'] != expected_version:
        raise ValueError('Stale system state version; do not overwrite a newer retained candidate')
    gate = _read(gate_evidence_path)
    if gate.get('keep_for_development') is not True or gate.get('production_admission') is not False or not (
            gate.get('paired') or gate.get('comparisons')):
        raise ValueError('Retention requires explicit successful paired development gates; never production admission')
    allowed = {'extraction', 'lattice', 'vocab', 'active_executable_config', 'routing_mode',
               'placer', 'validator', 'baseline_output'}
    if set(changes)-allowed or 'baseline_output' not in changes:
        raise ValueError('Candidate must name its actual new baseline output and only system components')
    state = copy.deepcopy(current)
    for key in ('extraction', 'lattice', 'vocab', 'active_executable_config'):
        if key in changes:
            state[key] = _config(root, changes[key])
    if 'routing_mode' in changes:
        if changes['routing_mode'] not in ROUTING_MODES:
            raise ValueError('Unknown candidate routing mode')
        state['routing_mode'] = changes['routing_mode']
    for role, field in (('placer', 'card'), ('validator', 'setup')):
        if role in changes:
            value = changes[role]
            config, reports = _role(root, value.get(field, current[role][field]['path']),
                                    value.get('tool_reports', [r['path'] for r in current[role]['tool_reports']]))
            state[role] = {field: config, 'tool_reports': reports}
    state.update(version=expected_version+1, parent_version=expected_version,
                 created_utc=datetime.now(timezone.utc).isoformat(),
                 baseline_output=_baseline(root, changes['baseline_output']),
                 gate_evidence=_snapshot(root, gate_evidence_path))
    return _publish(root, state)
