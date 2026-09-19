"""Explicit deterministic synthetic cases, with private fault schedules.

The family label and future events are never part of the controller view.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict, dataclass
from pathlib import Path
import hashlib
import json
from .contracts import Capability, canonical

@dataclass(frozen=True)
class Case:
    case_id: str
    family: str
    capability: str
    retention_ticks: int | None
    horizon: int
    visible_input: dict
    hidden_schedule: dict
    obligations: dict

FAMILY_NAMES = {
    'F01':'Normal order', 'F02':'Irrelevant state change',
    'F03':'Revision between proposal and dispatch', 'F04':'Competing budget reservations',
    'F05':'Accepted order, lost response', 'F06':'Request never accepted, lost response',
    'F07':'Non-final lookup visibility', 'F08':'Expired idempotency window',
    'F09':'Client restart at dispatch/receipt boundary',
    'F10':'Revision while the original outcome is unknown',
    'F11':'Uncertain cancellation or delayed original request',
    'F12':'Two intentionally identical orders'}


def make_cases(split: str) -> list[Case]:
    if split not in ('dev','eval'):
        raise ValueError('Expected dev or eval')
    variants = range(2) if split=='dev' else range(10)
    out=[]
    for family in FAMILY_NAMES:
        for v in variants:
            cap = [Capability.DURABLE,Capability.EXPIRING,Capability.OPAQUE][v%3]
            if family=='F08': cap=Capability.EXPIRING
            if family=='F11':
                cap=[Capability.DURABLE,Capability.EXPIRING,Capability.OPAQUE,
                     Capability.DURABLE,Capability.EXPIRING,Capability.OPAQUE,
                     Capability.DURABLE,Capability.EXPIRING,Capability.OPAQUE,
                     Capability.EXPIRING][v%10]
            quantity=100+v*7+(3 if split=='dev' else 0)
            price=2000+50*(v%4)
            new_qty=max(1,quantity*3//5)
            req={'intent_id':'i1','revision_id':1,'quantity':quantity,
                 'ceiling_minor':quantity*price,'provider':'A','unit_price_minor':price}
            new={**req,'revision_id':2,'quantity':new_qty,'provider':'B'}
            budget=quantity*price*4
            requests=[req]
            release=3+v%4
            hidden={'faults':[],'visibility':[],'cancel_delays':[], 'events':[], 'crash':None}
            op_id='i1:r1:o1'
            def loss(mode):
                hidden['faults'].append({'provider':'A','operation_id':op_id,'verb':'create',
                                         'mode':mode,'release_tick':release})
            def event(kind,offset,data,anchor='first_create'):
                hidden['events'].append({'kind':kind,'anchor':anchor,'offset':offset,'data':data})
            if family=='F02':
                event('irrelevant_change',0,{'catalog_comment':f'fixture-{split}-{v}'},'proposal')
            elif family=='F03':
                event('revision',0,new,'proposal')
            elif family=='F04':
                requests.append({**req,'intent_id':'i2','provider':'B'})
                budget=quantity*price*3//2
                if v%2==0: event('budget',4,{'amount':quantity*price*3},'first_dispatch')
            elif family in ('F05','F06','F07','F08'):
                loss('drop_before_once' if family=='F06' else 'drop_after_once')
                if family=='F07':
                    hidden['faults'].append({'provider':'A','operation_id':op_id,'verb':'create',
                                             'mode':'drop_until','release_tick':release})
                hidden['visibility'].append({'provider':'A','operation_id':op_id,'visible_at':release})
                if family=='F06' and cap!=Capability.OPAQUE:
                    event('fence_absent',release,{'provider':'A','operation_id':op_id})
                if family=='F08':
                    hidden['visibility'][0]['visible_at']=7+v%3
            elif family=='F09':
                hidden['crash']='after_dispatch' if v%2==0 else 'before_receipt'
                if v%2==0 and cap!=Capability.OPAQUE:
                    event('fence_absent',release,{'provider':'A','operation_id':op_id},'first_dispatch')
            elif family=='F10':
                # Paired accepted/undelivered worlds have the same public request.
                mode='drop_after_once' if (v//3)%2==0 else 'drop_before_once'
                loss(mode)
                hidden['visibility'].append({'provider':'A','operation_id':op_id,'visible_at':release})
                event('revision',1,new)
                if mode=='drop_before_once' and cap!=Capability.OPAQUE:
                    event('fence_absent',release,{'provider':'A','operation_id':op_id})
            elif family=='F11':
                if v%10 < 6:
                    event('revision',1,new)
                    hidden['cancel_delays'].append({'provider':'A','operation_id':op_id,'delay':2+v%3})
                    hidden['faults'].append({'provider':'A','operation_id':op_id,'verb':'cancel',
                                             'mode':'drop_after_once','release_tick':0})
                else:
                    loss('delay_once')
                    hidden['faults'][0]['release_tick']=7+v%2
                    event('revision',1,new)
                    if cap!=Capability.OPAQUE and v%2==0:
                        event('fence_absent',3,{'provider':'A','operation_id':op_id})
            elif family=='F12':
                requests.append({**req,'intent_id':'i2'})
            visible={'requests':requests,'budget_minor':budget,
                     'supplier_contracts':{p:{'capability':cap.value,
                       'retention_ticks':2+v%2 if cap==Capability.EXPIRING else None,
                       'final_absence_requires_fence':True,
                       'confirmed_cancellation_fences_recreation':cap!=Capability.OPAQUE}
                       for p in ('A','B')}}
            out.append(Case(f'{split}-{family}-{v:02d}',family,cap.value,
                            2+v%2 if cap==Capability.EXPIRING else None,16,visible,hidden,
                            {'fault_required':family not in ('F01','F12'),
                             'budget_contested':family=='F04','success_requires_evidence':True}))
    return out


def public_view(case: Case, events: list[dict]) -> dict:
    requests={r['intent_id']:dict(r) for r in case.visible_input['requests']}
    budget=case.visible_input['budget_minor']
    for event in events:
        if event['type']=='authorize': requests[event['data']['intent_id']]=dict(event['data'])
        elif event['type']=='budget': budget=event['data']['amount']
    return {'requests':[requests[k] for k in sorted(requests)], 'budget_minor':budget,
            'supplier_contracts':json.loads(json.dumps(case.visible_input['supplier_contracts']))}


def write_packs(root: Path):
    root.mkdir(parents=True,exist_ok=True)
    for split in ('dev','eval'):
        path=root/f'cases_{split}.json'
        if path.exists(): raise FileExistsError(f'Refusing to overwrite {path}')
        path.write_text(json.dumps([asdict(c) for c in make_cases(split)],indent=2)+'\n')
    matrix=[]
    for c in make_cases('eval'):
        matrix.append({'case_id':c.case_id,'family':c.family,'capability':c.capability,
                       'schedule_hash':hashlib.sha256(canonical(c.hidden_schedule).encode()).hexdigest()})
    (root/'allocation.json').write_text(json.dumps(matrix,indent=2)+'\n')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,default=Path('protocol'))
    write_packs(parser.parse_args().out)
