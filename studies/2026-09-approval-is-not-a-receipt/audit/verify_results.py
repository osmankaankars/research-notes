"""Independent saved-evidence checks. Does not call the benchmark evaluator.

Run from the study root. Core runtime and frozen evaluation inputs remain unchanged.
"""
from pathlib import Path
from collections import Counter
import csv
import hashlib
import json
import sqlite3
import math

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results' / 'audit'


def load_lines(path):
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def read_table(path, table):
    db = sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in db.execute('SELECT * FROM ' + table)]
    finally:
        db.close()


def write_csv(path, rows):
    with path.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)


def coverage(case, trace):
    """Audit component reach, not a new pass/fail score or a counterfactual."""
    family = case['family']
    kinds = {e['data'].get('kind') for e in trace if e['type'] == 'fault'}
    tools = [e['data']['action'] for e in trace if e['type'] == 'tool_call']
    faults = case['hidden_schedule']['faults']
    required = []
    if family == 'F02': required = [('unrelated_change', 'irrelevant_change' in kinds)]
    elif family == 'F03': required = [('revision_before_dispatch', 'revision' in kinds)]
    elif family == 'F04': required = [('budget_contention', 'shared_budget_contention' in kinds)]
    elif family in ('F05', 'F06', 'F07', 'F08'):
        required = [('initial_delivery_loss', bool(kinds & {'drop_after_once','drop_before_once'}))]
        if family == 'F07': required += [('lookup_attempted', 'lookup' in tools)]
        if family == 'F08':
            early = [e['tick'] for e in trace if e['type']=='unknown']
            required += [('outcome_unknown_through_retention', bool(early) and any(
                e['type']=='state_sample' and e['data']['unknown_minor']>0 and
                e['tick'] >= min(early) + case['retention_ticks'] for e in trace))]
    elif family == 'F09': required = [('crash_boundary', any('crash' in str(k) for k in kinds))]
    elif family == 'F10': required = [('initial_delivery_loss', bool(kinds & {'drop_after_once','drop_before_once'})),
                                      ('revision_during_recovery', 'revision' in kinds)]
    elif family == 'F11':
        required = [('request_revision', 'revision' in kinds)]
        if any(f['verb']=='cancel' for f in faults):
            required += [('cancellation_attempted', 'cancel' in tools),
                         ('cancellation_response_lost', 'drop_after_once' in kinds)]
        else: required += [('delayed_original_injected', 'delay_once' in kinds)]
    return required


def audit_episode(ep):
    case=json.loads((ep/'case.json').read_text())
    r=json.loads((ep/'outcome.json').read_text())
    trace=load_lines(ep/'trace.jsonl')
    independent=[]
    for p in ('A','B'):
        for raw in read_table(ep/f'supplier_{p}.db','effects'):
            independent.append({'event_id':f"{p}:{raw['seq']}", 'kind':raw['kind'],
                'operation':json.loads(raw['payload']), 'operation_id':raw['operation_id'],
                'phase':raw['phase'], 'provider':p, 'reverses':raw['reverses'],
                'seq':raw['seq'], 'tick':raw['tick']})
    exported=load_lines(ep/'provider_ledger.jsonl')
    assert independent==exported, (ep,'ledger export differs from database')
    rows=read_table(ep/'intent.db','events')
    events=[{'seq':x['seq'],'tick':x['tick'],'type':x['type'],'data':json.loads(x['data'])} for x in rows]
    assert events==trace,(ep,'event export differs from database')
    active={}
    for e in sorted(independent,key=lambda x:(x['tick'],x['phase'],x['provider'],x['seq'])):
        if e['kind']=='CREATE': active[(e['provider'],e['seq'])]=e['operation']
        elif e['kind']=='CANCEL':
            assert (e['provider'],e['reverses']) in active,(ep,'cancel references no live effect')
            del active[(e['provider'],e['reverses'])]
        else: raise AssertionError('unknown effect kind')
    latest={}
    for x in read_table(ep/'intent.db','revisions'):
        if x['intent_id'] not in latest or x['revision_id']>latest[x['intent_id']]['revision_id']:
            latest[x['intent_id']]=x
    goal=True
    for iid,req in latest.items():
        a=[o for o in active.values() if o['intent_id']==iid]
        goal = goal and len(a)==1 and all(a[0][k]==req[k] for k in
                   ('provider','quantity','revision_id','unit_price_minor'))
    goal=bool(goal and all(o['intent_id'] in latest for o in active.values()))
    assert r['physical_goal_reached']==goal,(ep,'physical goal mismatch')
    ops=read_table(ep/'intent.db','operations')
    unknown=[x for x in ops if x['state'] in ('DISPATCH_RECORDED','OUTCOME_UNKNOWN','CANCEL_UNKNOWN','CANCEL_PENDING')]
    assert r['final_unknown_liability_minor']==sum(x['reservation'] for x in unknown),(ep,'unknown reservation mismatch')
    samples=[e for e in trace if e['type']=='state_sample']
    assert len(samples)==case['horizon'],(ep,'incomplete episode')
    assert sum(e['data']['unknown_minor'] for e in samples)==r['unknown_liability_minor_ticks'],(ep,'liability area mismatch')
    assert sum(e['data']['reserved_minor'] for e in samples)==r['reserved_minor_ticks'],(ep,'reserved area mismatch')
    calls=Counter(e['data']['action'] for e in trace if e['type']=='tool_call')
    assert calls['create']==r['create_calls'] and calls['cancel']==r['cancel_calls'] and calls['lookup']==r['query_count']
    assert sum(calls.values())==r['tool_calls']
    assert not (r['completed_correctly'] and (r['safe_unresolved'] or r['safe_blocked']))
    if r['completed_correctly']:
        assert goal and not unknown and not r['invalid_effects'] and not r['duplicate_effects']
    components=coverage(case,trace)
    c={'case_id':r['case_id'],'strategy':r['strategy'],'family':case['family'],
       'required_components':';'.join(k for k,b in components),
       'unreached_components':';'.join(k for k,b in components if not b),
       'all_planned_components_reached':all(b for k,b in components) if components else 'not_applicable',
       'outcome_correct':r['completed_correctly'],'safe_unresolved':r['safe_unresolved']}
    return r,c


def main():
    OUT.mkdir(exist_ok=True)
    frozen=json.loads((ROOT/'protocol/frozen_manifest.json').read_text())
    for name,digest in frozen['files'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest, 'Changed frozen file: '+name
    data={};cov=[]
    for mode in ('direct','http'):
        base=ROOT/'results'/f'eval-{mode}'
        collected=[]
        for ep in sorted((base/'episodes').iterdir()):
            row,c=audit_episode(ep); collected.append(row)
            c['transport']=mode;cov.append(c)
        data[mode]={(r['case_id'],r['strategy']):r for r in collected}
        expected=360 if mode=='direct' else 78
        assert len(data[mode])==len(collected)==expected
        table=list(csv.DictReader((base/'summary.csv').open()))
        for s in table:
            rows=[r for r in collected if r['strategy']==s['strategy'] and (s['capability']=='ALL' or r['capability']==s['capability'])]
            assert int(s['cases'])==len(rows)
            for field in ('completed_correctly','safe_unresolved','safe_blocked','invalid_effects','duplicate_effects',
                          'false_success_claim','tool_calls','query_count','retry_count','unknown_liability_minor_ticks'):
                assert int(s[field])==sum(int(r[field]) for r in rows),(mode,s,field)
            assert int(s['episodes_with_invalid_effects'])==sum(r['invalid_effects']>0 for r in rows)
            assert math.isclose(float(s['mean_tool_calls']),sum(r['tool_calls'] for r in rows)/len(rows),rel_tol=1e-12)
        # Compare flat export independently from JSON outcome records.
        flat=list(csv.DictReader((base/'cases.csv').open()))
        assert len(flat)==expected
        for x in flat:
            row=data[mode][(x['case_id'],x['strategy'])]
            for key,value in row.items():
                if key=='invalid_details':continue
                assert x[key]==str(value),(mode,x['case_id'],key)
    for key,row in data['http'].items():
        assert row==data['direct'][key],(key,'transport parity mismatch')
    paired=[]
    for case_id in sorted({k[0] for k in data['direct']}):
        a=data['direct'][(case_id,'operation_scoped')];b=data['direct'][(case_id,'intent_scoped')]
        paired.append({'case_id':case_id,'family':a['family'],'capability':a['capability'],
          'completion_difference':int(b['completed_correctly'])-int(a['completed_correctly']),
          'invalid_effect_difference':b['invalid_effects']-a['invalid_effects'],
          'unresolved_difference':int(b['safe_unresolved'])-int(a['safe_unresolved']),
          'additional_calls':b['tool_calls']-a['tool_calls']})
    write_csv(OUT/'hazard_coverage.csv',cov)
    write_csv(OUT/'paired_executor_differences.csv',paired)
    not_reached=[c for c in cov if c['transport']=='direct' and c['all_planned_components_reached'] is False]
    report={'primary_episodes_checked':len(data['direct']),'http_episodes_checked':len(data['http']),
      'logical_transport_matches':len(data['http']), 'frozen_files_unchanged':len(frozen['files']),
      'new_model_calls':0,'checks':'Raw SQLite ledger and event exports; independent physical goals; reservations; all means/counts; HTTP parity',
      'complete_component_reach':{'direct_all_reached':sum(c['transport']=='direct' and c['all_planned_components_reached'] is True for c in cov),
        'direct_not_all_reached':len(not_reached),
        'direct_not_applicable':sum(c['transport']=='direct' and c['all_planned_components_reached']=='not_applicable' for c in cov)},
      'coverage_caveat':'The primary fault_exercised boolean means any environment fault observed, not that every compound fault stage was reached. Unreached components stay in hazard_coverage.csv and are not passed stress recoveries.',
      'paired_E2_minus_E1':{'additional_completions':sum(x['completion_difference'] for x in paired),
        'invalid_effect_change':sum(x['invalid_effect_difference'] for x in paired),
        'additional_calls':sum(x['additional_calls'] for x in paired)},
      'independence_boundary':'Separate arithmetic and direct database inspection, not an external or fresh-context human review.'}
    (OUT/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__': main()
