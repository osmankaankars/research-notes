"""Independent scoring from authority history, environmental trace and supplier effects.

Never trust controller-supplied scores. The adapter's terminal label is checked,
not used as ground truth. This is a cooperative fixture, not a security sandbox.
"""
from __future__ import annotations
from .contracts import Operation
from .intent_store import TERMINAL_CLEAR, UNCERTAIN
from .scenarios import Case


def evaluate(case: Case, trace: list[dict], ledger: list[dict], report: dict) -> dict:
    authorities={}
    budget=case.visible_input['budget_minor']
    operations={}
    statuses={}
    reservations={}
    dispatch_errors={}
    observed_hashes={}
    query_count=retry_count=create_calls=cancel_calls=0
    by_tick={}
    for event in sorted(trace,key=lambda e:e['seq']):
        kind=event['type'];d=event['data'];t=event['tick']
        if kind=='budget': budget=d['amount']
        elif kind=='authorize': authorities[d['intent_id']]=d
        elif kind=='dispatch':
            op=Operation(**d['operation']);auth=authorities.get(op.intent_id)
            errors=[]
            if not auth or (auth['revision_id'],auth['provider'],auth['quantity'],auth['unit_price_minor'])!=(
                op.revision_id,op.provider,op.quantity,op.unit_price_minor) or op.cost>auth['ceiling_minor']:
                errors.append('authority_at_dispatch')
            if sum(reservations.values())+op.cost>budget: errors.append('shared_budget_at_dispatch')
            operations[op.operation_id]=op
            dispatch_errors[op.operation_id]=errors
            statuses[op.operation_id]='DISPATCH_RECORDED'
            reservations[op.operation_id]=op.cost
        elif kind=='unknown':
            statuses[d['operation_id']]='CANCEL_UNKNOWN' if d.get('cancelling') else 'OUTCOME_UNKNOWN'
        elif kind=='receipt':
            oid=d['operation_id'];op=operations.get(oid);status=d['status']
            bound=(op is not None and d.get('provider')==op.provider and d.get('payload_hash')==op.payload_hash)
            if bound and status in ('COMMITTED','IDEMPOTENT_REPLAY','CANCEL_PENDING'):
                statuses[oid]='COMMITTED' if status=='IDEMPOTENT_REPLAY' else status
                observed_hashes[oid]=op.payload_hash
            elif bound and status in TERMINAL_CLEAR and d.get('sealed'):
                statuses[oid]=status;reservations[oid]=0
            elif oid in statuses and status in ('UNKNOWN','PARAMETER_MISMATCH'):
                statuses[oid]='CANCEL_UNKNOWN' if statuses[oid].startswith('CANCEL') else 'OUTCOME_UNKNOWN'
        elif kind=='tool_call':
            action=d['action']
            if action=='lookup': query_count+=1
            elif action=='cancel': cancel_calls+=1
            elif action=='create':
                create_calls+=1
                if d['attempt_id']!=f"{d['operation_id']}:a1": retry_count+=1
        by_tick[t]={'unknown':sum(reservations[o] for o in reservations if statuses.get(o) in UNCERTAIN),
                    'reserved':sum(reservations.values())}

    live={}
    history_by_op={}
    history_by_revision={}
    invalid_events=[];duplicate_events=[];max_commitment=0
    ordered=sorted(ledger,key=lambda e:(e['tick'],e.get('phase',1),e['provider'],e['seq']))
    for effect in ordered:
        key=(effect['provider'],effect['seq'])
        op=Operation(**effect['operation'])
        if effect['kind']=='CANCEL':
            live.pop((effect['provider'],effect['reverses']),None)
            continue
        if effect['kind']!='CREATE': continue
        errors=list(dispatch_errors.get(op.operation_id,['missing_dispatch']))
        dispatched=operations.get(op.operation_id)
        if dispatched and dispatched.payload_hash!=op.payload_hash: errors.append('payload_not_dispatched')
        prior_for_intent=[v for v in live.values() if v.intent_id==op.intent_id]
        if prior_for_intent: errors.append('overlapping_intent_commitments')
        opkey=(op.provider,op.operation_id)
        revkey=(op.intent_id,op.revision_id)
        duplicate=(history_by_op.get(opkey,0)>0 or
                   any(v.revision_id==op.revision_id for v in prior_for_intent))
        if duplicate: duplicate_events.append(effect['event_id']);errors.append('duplicate_effect')
        if errors: invalid_events.append({'event_id':effect['event_id'],'reasons':sorted(set(errors))})
        history_by_op[opkey]=history_by_op.get(opkey,0)+1
        history_by_revision[revkey]=history_by_revision.get(revkey,0)+1
        live[key]=op
        max_commitment=max(max_commitment,sum(v.cost for v in live.values()))

    # A goal requires the current authoritative request, not a stale plan or agent claim.
    physical_goal=bool(authorities)
    for iid,auth in authorities.items():
        current=[op for op in live.values() if op.intent_id==iid]
        physical_goal=physical_goal and len(current)==1 and (
            current[0].quantity,current[0].provider,current[0].revision_id,current[0].unit_price_minor)==(
            auth['quantity'],auth['provider'],auth['revision_id'],auth['unit_price_minor'])
    physical_goal=physical_goal and all(op.intent_id in authorities for op in live.values())
    unknown=[oid for oid,status in statuses.items() if status in UNCERTAIN]
    proofs=not unknown and all(status in ('COMMITTED',)+TERMINAL_CLEAR for status in statuses.values())
    for op in live.values(): proofs=proofs and observed_hashes.get(op.operation_id)==op.payload_hash
    valid_terminal=physical_goal and proofs and not invalid_events and not duplicate_events
    claim=report.get('completion_status')
    false_success=claim=='success' and not valid_terminal
    correct=valid_terminal and claim=='success'
    safe_unresolved=(not correct and not invalid_events and not duplicate_events and not false_success
                     and bool(unknown) and claim=='pending_recovery')
    safe_blocked=(not correct and not invalid_events and not duplicate_events and not false_success
                  and not unknown and claim=='needs_review')
    fault=any(e['type']=='fault' for e in trace)
    unknown_area=reserved_area=0
    last={'unknown':0,'reserved':0}
    for t in range(case.horizon):
        last=by_tick.get(t,last)
        unknown_area+=last['unknown'];reserved_area+=last['reserved']
    final_unknown=sum(reservations[o] for o in unknown)
    return {
        'case_id':case.case_id,'family':case.family,'capability':case.capability,
        'physical_goal_reached':bool(physical_goal),'completed_correctly':bool(correct),
        'invalid_effects':len(invalid_events),'duplicate_effects':len(duplicate_events),
        'safe_unresolved':bool(safe_unresolved),'safe_blocked':bool(safe_blocked),
        'false_success_claim':bool(false_success),'fault_exercised':bool(fault),
        'fault_not_exercised':bool(case.obligations['fault_required'] and not fault),
        'query_count':query_count,'retry_count':retry_count,'create_calls':create_calls,
        'cancel_calls':cancel_calls,'tool_calls':query_count+create_calls+cancel_calls,
        'unknown_liability_minor_ticks':unknown_area,'reserved_minor_ticks':reserved_area,
        'final_unknown_liability_minor':final_unknown,
        'max_live_commitment_minor':max_commitment,
        'invalid_details':invalid_events,'unknown_operation_count':len(unknown)}
