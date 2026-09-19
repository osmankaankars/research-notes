"""Matched local execution. No model APIs; HTTP mode is loopback only."""
from __future__ import annotations
import argparse
from dataclasses import asdict
from pathlib import Path
import csv
import hashlib
import json
import platform
import time
from .contracts import Capability, Operation, canonical
from .supplier import Supplier, SupplierEndpoint, read_ledger
from .intent_store import IntentStore
from .executor import Executor, STRATEGIES
from .scenarios import Case, public_view
from .evaluator import evaluate

ROOT=Path(__file__).resolve().parent.parent

class SimulatedCrash(RuntimeError):
    pass

class World:
    """Environment-owned controls, never included in controller observations."""
    def __init__(self,case: Case,root: Path,transport: str):
        self.case=case;self.root=root;self.fired=set();self.anchors={};self.crashed=False
        self.services=[];self.fault_cursors={'A':0,'B':0};self.contention_seen=False
        self.store=IntentStore(root/'intent.db',initial_budget=case.visible_input['budget_minor'])
        for r in case.visible_input['requests']:
            self.store.authorize(**r,tick=0)
        self.suppliers={p:Supplier(root/f'supplier_{p}.db',Capability(case.capability),case.retention_ticks,provider=p)
                        for p in ('A','B')}
        schedule=case.hidden_schedule
        for spec in schedule['faults']:
            self.suppliers[spec['provider']].configure_fault(spec['operation_id'],spec['verb'],spec['mode'],spec['release_tick'])
        for spec in schedule['visibility']:
            self.suppliers[spec['provider']].set_visibility(spec['operation_id'],spec['visible_at'])
        for spec in schedule['cancel_delays']:
            self.suppliers[spec['provider']].set_cancel_delay(spec['operation_id'],spec['delay'])
        if transport=='direct':
            self.clients={p:SupplierEndpoint(s) for p,s in self.suppliers.items()}
        elif transport=='http':
            from .http_supplier import HttpSupplierProcess
            self.clients={}
            try:
                for p,s in self.suppliers.items():
                    service=HttpSupplierProcess(s.path,s.capability,s.retention_ticks,p)
                    service.start();self.services.append(service)
                    self.clients[p]=service.client
            except Exception:
                self.close();raise
        else:
            raise ValueError('transport must be direct or http')

    def executor(self,strategy):
        e=Executor(strategy,self.store,self.clients)
        def after_dispatch(op,tick):
            self.anchors.setdefault('first_dispatch',tick)
            if not self.crashed and self.case.hidden_schedule['crash']=='after_dispatch':
                self.crashed=True
                self.store.note('fault',{'kind':'client_crash_after_dispatch'},tick)
                raise SimulatedCrash()
        def before_receipt(op,receipt,tick):
            if not self.crashed and self.case.hidden_schedule['crash']=='before_receipt':
                self.crashed=True
                self.store.note('fault',{'kind':'client_crash_before_receipt'},tick)
                raise SimulatedCrash()
        e.after_dispatch=after_dispatch;e.before_receipt=before_receipt
        return e

    def _anchors(self):
        for ev in self.store.events():
            if ev['type']=='dispatch': self.anchors.setdefault('first_dispatch',ev['tick'])
            if ev['type']=='tool_call' and ev['data']['action']=='create':
                self.anchors.setdefault('first_create',ev['tick'])

    def events(self,tick,*,proposal=False):
        self._anchors()
        if proposal: self.anchors.setdefault('proposal',tick)
        for n,ev in enumerate(self.case.hidden_schedule['events']):
            if n in self.fired or (ev['anchor']=='proposal')!=proposal: continue
            anchor=self.anchors.get(ev['anchor'])
            if anchor is None or tick<anchor+ev['offset']: continue
            kind=ev['kind'];d=ev['data'];self.fired.add(n)
            if kind=='revision':
                self.store.authorize(**d,tick=tick)
            elif kind=='budget':
                self.store.set_budget(d['amount'],tick=tick)
            elif kind=='fence_absent':
                row=next((r for r in self.store.operations() if r['operation_id']==d['operation_id']),None)
                if row:
                    try:
                        self.suppliers[d['provider']].fence_absent(Operation(**row['payload']),tick)
                    except ValueError:
                        # An earlier safe retry may have obtained the effect before closure.
                        self.store.note('environment',{'kind':'close_if_absent_found_effect'},tick)
            elif kind!='irrelevant_change':
                raise ValueError('Unknown scheduled event')
            self.store.note('fault',{'kind':kind,'boundary':ev['anchor']},tick)

    def advance(self,tick):
        for s in self.suppliers.values(): s.advance(tick)
        self.events(tick)

    def drain(self,tick):
        self._anchors()
        for p,s in self.suppliers.items():
            entries=s.fault_events()
            for ev in entries[self.fault_cursors[p]:]:
                self.store.note('fault',{'kind':ev['mode'],'provider':p,'operation_id':ev['operation_id']},tick)
            self.fault_cursors[p]=len(entries)
        if self.case.obligations.get('budget_contested') and not self.contention_seen:
            requests=self.store.current_requests()
            total=sum(r['quantity']*r['unit_price_minor'] for r in requests)
            budget=public_view(self.case,self.store.events())['budget_minor']
            dispatches=[e for e in self.store.events() if e['type']=='dispatch']
            blocked=any(e['type']=='blocked' for e in self.store.events())
            if total>budget and (len(dispatches)>1 or blocked):
                self.contention_seen=True
                self.store.note('fault',{'kind':'shared_budget_contention'},tick)

    def close(self):
        for service in self.services: service.stop()
        self.services=[]


def run_case(case: Case,strategy: str,root: Path,*,transport: str='direct') -> dict:
    root=Path(root)
    root.mkdir(parents=True,exist_ok=False)
    wall=time.perf_counter()
    world=World(case,root,transport)
    observable=[];report={'completion_status':'needs_review'}
    effective='request_only' if strategy=='always_retry' else strategy
    executor=None if strategy=='always_block' else world.executor(effective)
    try:
        for tick in range(case.horizon):
            world.advance(tick)
            view=public_view(case,world.store.events());view['tick']=tick
            view['known_operations']=[{k:r[k] for k in ('operation_id','revision_id','payload','state','reservation')}
                                      for r in world.store.operations()]
            if strategy!='always_block': world.events(tick,proposal=True)
            try:
                if strategy=='always_block':
                    action={'action':'blocked','status':'NEEDS_REVIEW'}
                elif strategy=='always_retry':
                    # Test-only diagnostic, never included as a competitive method.
                    req=view['requests'][0];op=world.store.new_operation(req)
                    world.store.record_dispatch(op,tick=tick,strategy='request_only')
                    action=executor._call(op,'create',tick)
                else:
                    action=executor.step(view)
            except SimulatedCrash:
                world.store=IntentStore(root/'intent.db')
                executor=world.executor(effective)
                action={'action':'client_restart','status':'OUTCOME_UNKNOWN'}
            world.drain(tick)
            report=executor.report() if executor else {'completion_status':'needs_review'}
            world.store.note('state_sample',{
                'reserved_minor':world.store.reserved_total(),
                'unknown_minor':world.store.unresolved_liability(),
                'report':report},tick)
            observable.append({'observation':view,'action':action,'report':report})
        trace=world.store.events()
        ledger=[effect for s in world.suppliers.values() for effect in read_ledger(s.path)]
        result=evaluate(case,trace,ledger,report)
        result.update({'strategy':strategy})
        for name,rows in [('trace',trace),('provider_ledger',ledger)]:
            (root/f'{name}.jsonl').write_text(''.join(canonical(row)+'\n' for row in rows))
        (root/'observable_history.json').write_text(json.dumps(observable,indent=2)+'\n')
        (root/'outcome.json').write_text(json.dumps(result,indent=2)+'\n')
        (root/'case.json').write_text(json.dumps(asdict(case),indent=2)+'\n')
        (root/'runtime.json').write_text(json.dumps({'transport':transport,'wall_seconds':time.perf_counter()-wall,
                                                   'human_participants':0,'model_calls':0},indent=2)+'\n')
        return result
    finally:
        world.close()


def summarize(rows: list[dict]) -> list[dict]:
    out=[]
    for group in ['ALL']+sorted({r['capability'] for r in rows}):
        for strategy in STRATEGIES:
            selected=[r for r in rows if r['strategy']==strategy and (group=='ALL' or r['capability']==group)]
            if not selected: continue
            n=len(selected)
            counts={k:sum(int(r[k]) for r in selected) for k in
                    ('completed_correctly','safe_unresolved','safe_blocked','invalid_effects','duplicate_effects',
                     'false_success_claim','fault_exercised','fault_not_exercised','tool_calls','query_count','retry_count',
                     'unknown_liability_minor_ticks')}
            counts['failed_episodes']=n-counts['completed_correctly']-counts['safe_unresolved']-counts['safe_blocked']
            counts['episodes_with_invalid_effects']=sum(r['invalid_effects']>0 for r in selected)
            counts['episodes_with_duplicates']=sum(r['duplicate_effects']>0 for r in selected)
            counts['mean_tool_calls']=counts['tool_calls']/n
            out.append({'capability':group,'strategy':strategy,'cases':n,**counts})
    return out


def write_csv(path: Path,rows: list[dict]):
    if not rows: raise ValueError('No rows')
    with path.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)


def freeze(root: Path=ROOT):
    files={}
    for sub in ('receiptbench','tests','protocol'):
        for p in sorted((root/sub).glob('**/*')):
            if p.is_file() and p.suffix in ('.py','.json') and p.name!='frozen_manifest.json':
                files[str(p.relative_to(root))]=hashlib.sha256(p.read_bytes()).hexdigest()
    manifest={'purpose':'Local pre-evaluation freeze; not public preregistration', 'files':files,
              'seeded_outcomes_exist_at_freeze':False,'model_calls':0}
    path=root/'protocol/frozen_manifest.json'
    if path.exists(): raise FileExistsError('Freeze already exists')
    path.write_text(json.dumps(manifest,indent=2)+'\n')
    return path


def verify_freeze(root: Path=ROOT):
    manifest=json.loads((root/'protocol/frozen_manifest.json').read_text())
    for name,digest in manifest['files'].items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=digest:
            raise ValueError(f'Frozen source/input changed: {name}')


def run_pack(cases_path: Path,output: Path,*,transport: str='direct',check_frozen: bool=True) -> Path:
    if check_frozen: verify_freeze()
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    cases=[Case(**d) for d in json.loads(Path(cases_path).read_text())]
    rows=[];wall=time.perf_counter()
    for case in cases:
        for strategy in STRATEGIES:
            row=run_case(case,strategy,output/'episodes'/f'{case.case_id}_{strategy}',transport=transport)
            rows.append(row)
    scalar=[{k:v for k,v in r.items() if k!='invalid_details'} for r in rows]
    write_csv(output/'cases.csv',scalar)
    write_csv(output/'summary.csv',summarize(rows))
    byfamily=[]
    for family in sorted({r['family'] for r in rows}):
        for r in summarize([r for r in rows if r['family']==family]):
            if r['capability']=='ALL': byfamily.append({'family':family,**r})
    write_csv(output/'by_family.csv',byfamily)
    metadata={'cases':len(cases),'episodes':len(rows),'transport':transport,
              'input_sha256':hashlib.sha256(Path(cases_path).read_bytes()).hexdigest(),
              'frozen_manifest_sha256':hashlib.sha256((ROOT/'protocol/frozen_manifest.json').read_bytes()).hexdigest()
                    if (ROOT/'protocol/frozen_manifest.json').exists() else None,
              'python':platform.python_version(),'wall_seconds':time.perf_counter()-wall,
              'model_calls':0,'human_participants':0,'additional_api_and_hosting_spend':0}
    (output/'manifest.json').write_text(json.dumps(metadata,indent=2)+'\n')
    return output

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--cases',type=Path,default=Path('protocol/cases_eval.json'))
    parser.add_argument('--out',type=Path)
    parser.add_argument('--transport',choices=('direct','http'),default='direct')
    parser.add_argument('--freeze',action='store_true')
    args=parser.parse_args()
    if args.freeze: print(freeze())
    elif args.out: print(run_pack(args.cases,args.out,transport=args.transport))
    else: parser.error('--out or --freeze is required')
