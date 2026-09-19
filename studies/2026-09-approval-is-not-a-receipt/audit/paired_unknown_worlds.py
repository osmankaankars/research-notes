"""Two supplemental diagnostic worlds, outside the frozen 120-case cohort.

The visible request is identical, including its revision from 100 to 60 units.
Only the supplier's initial acceptance differs. Neither has final lookup evidence.
"""
from dataclasses import asdict
from pathlib import Path
import copy
import hashlib
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from receiptbench.scenarios import Case
from receiptbench.runner import run_case

ROOT=Path(__file__).resolve().parents[1]

def main():
    dest=ROOT/'results'/'paired-unknown-worlds'
    if dest.exists(): raise FileExistsError('Use a clean directory; diagnostic results already exist')
    dest.mkdir()
    original=next(c for c in json.loads((ROOT/'protocol/cases_eval.json').read_text()) if c['case_id']=='eval-F10-00')
    cases=[];outputs=[]
    for label,mode in [('accepted','drop_after_once'),('not_accepted','drop_before_once')]:
        d=copy.deepcopy(original);d['case_id']='diagnostic-revision-'+label
        d['capability']='OPAQUE';d['retention_ticks']=None
        for v in d['visible_input']['supplier_contracts'].values():
            v['capability']='OPAQUE';v['retention_ticks']=None;v['confirmed_cancellation_fences_recreation']=False
        d['hidden_schedule']['faults'][0]['mode']=mode
        cases.append(d)
        outputs.append(run_case(Case(**d),'intent_scoped',dest/label))
    a=(dest/'accepted'/'observable_history.json').read_bytes()
    b=(dest/'not_accepted'/'observable_history.json').read_bytes()
    assert a==b,'Different public histories would invalidate the diagnostic'
    assert all(r['safe_unresolved'] and not r['completed_correctly'] and r['invalid_effects']==0 for r in outputs)
    assert all(r['final_unknown_liability_minor']==200000 for r in outputs)
    counts=[]
    for label in ('accepted','not_accepted'):
        ledger=[json.loads(x) for x in (dest/label/'provider_ledger.jsonl').read_text().splitlines()]
        counts.append(sum(x['operation']['quantity'] for x in ledger if x['kind']=='CREATE'))
    assert counts==[100,0]
    (dest/'cases.json').write_text(json.dumps(cases,indent=2)+'\n')
    report={'role':'Supplemental exact-pair diagnostic, constructed after main evaluation; not additional independent evaluation cases',
       'same_visible_request':'100 units from A revised to 60 from B',
       'identical_observation_action_report_bytes':True,
       'observation_history_sha256':hashlib.sha256(a).hexdigest(),
       'actual_supplier_quantity':{'accepted':counts[0],'not_accepted':counts[1]},
       'terminal_status_both':'safe_unresolved','reserved_possible_liability_minor_both':200000,
       'new_model_calls':0,'human_participants':0}
    (dest/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__': main()
