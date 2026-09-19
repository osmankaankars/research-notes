"""A common deterministic controller with three conventional executor scopes.

No scenario-family branching, private truth, learned personas, or model calls.
request_only is a diagnostic weak ablation, not a competitive baseline.
operation_scoped is explicitly not a cross-revision workflow.
"""
from __future__ import annotations
from .contracts import Capability, Operation, OutcomeUnknown, DispatchRejected
from .intent_store import IntentStore, TERMINAL_CLEAR, UNCERTAIN

STRATEGIES = ('request_only','operation_scoped','intent_scoped')

class Executor:
    def __init__(self, strategy: str, store: IntentStore, supplier_client: dict):
        if strategy not in STRATEGIES:
            raise ValueError('Unknown strategy')
        self.strategy = strategy
        self.store = store
        self.clients = supplier_client
        self.after_dispatch = None
        self.before_receipt = None

    def _reconcile(self, row: dict, tick: int, *, obsolete: bool=False) -> dict:
        op=Operation(**row['payload'])
        client=self.clients[op.provider]
        # Only durable deduplication permits replay with unbounded original delivery.
        can_retry=(not obsolete and row['last_action']=='lookup' and
                   row['state'] in ('DISPATCH_RECORDED','OUTCOME_UNKNOWN') and
                   client.capability==Capability.DURABLE)
        return self._call(op, 'create' if can_retry else 'lookup', tick)

    def _call(self, op: Operation, action: str, tick: int) -> dict:
        attempt_id=self.store.note_call(op.operation_id,action,tick)
        client=self.clients[op.provider]
        try:
            if action=='create':
                receipt=client.create(op,attempt_id,tick)
            elif action=='cancel':
                receipt=client.request_cancel(op.operation_id,f'{op.operation_id}:cancel',tick)
            else:
                receipt=client.lookup(op.operation_id,tick)
            if self.before_receipt:
                self.before_receipt(op,receipt,tick)
            self.store.observe_receipt(op.operation_id,receipt,tick=tick)
            return {'action':action,'operation_id':op.operation_id,'status':receipt.status}
        except OutcomeUnknown:
            self.store.mark_unknown(op.operation_id,tick=tick,cancelling=action=='cancel')
            return {'action':action,'operation_id':op.operation_id,'status':'OUTCOME_UNKNOWN'}

    def step(self, observation: dict) -> dict:
        tick=observation['tick']
        for request in observation['requests']:
            rows=self.store.operations(request['intent_id'])
            # The common proposal is to satisfy the latest authorized revision.
            # E2 gates it on ALL prior liabilities; E1 gates just its operation.
            if self.strategy=='intent_scoped':
                prior=[r for r in rows if r['revision_id']!=request['revision_id'] and
                       r['state'] not in TERMINAL_CLEAR]
                if prior:
                    row=prior[0]
                    if row['state']=='COMMITTED':
                        return self._call(Operation(**row['payload']),'cancel',tick)
                    return self._reconcile(row,tick,obsolete=True)
            current=[r for r in rows if r['revision_id']==request['revision_id'] and r['state'] not in TERMINAL_CLEAR]
            if any(r['state']=='COMMITTED' for r in current):
                continue
            if current and self.strategy!='request_only':
                return self._reconcile(current[0],tick)
            op=self.store.new_operation(request)
            try:
                self.store.record_dispatch(op,tick=tick,strategy=self.strategy)
            except DispatchRejected as exc:
                self.store.note('blocked',{'intent_id':op.intent_id,'reason':str(exc)},tick)
                return {'action':'blocked','intent_id':op.intent_id,'status':'NEEDS_REVIEW'}
            if self.after_dispatch:
                self.after_dispatch(op,tick)
            return self._call(op,'create',tick)
        return {'action':'idle','status':self.report()['completion_status']}

    def report(self) -> dict:
        all_done=True
        for request in self.store.current_requests():
            rows=self.store.operations(request['intent_id'])
            matched=any(r['revision_id']==request['revision_id'] and r['state']=='COMMITTED' for r in rows)
            if self.strategy=='intent_scoped':
                matched=matched and not any(r['state'] not in TERMINAL_CLEAR and
                         (r['revision_id']!=request['revision_id'] or r['state']!='COMMITTED') for r in rows)
            all_done=all_done and matched
        state='success' if all_done else ('pending_recovery' if self.store.unresolved_liability() else 'needs_review')
        return {'completion_status':state}
