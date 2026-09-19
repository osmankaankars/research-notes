import unittest
from dataclasses import asdict
from receiptbench.contracts import Operation
try:
    from receiptbench.scenarios import Case, make_cases, public_view
    from receiptbench.evaluator import evaluate
except ImportError:
    evaluate = None

class ScenarioEvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(evaluate,'Scenario and evaluator contracts are not implemented')
        self.case = make_cases('dev')[0]
        r = self.case.visible_input['requests'][0]
        self.op = Operation(r['provider'],'op1',r['intent_id'],r['revision_id'],r['quantity'],r['unit_price_minor'])
        self.trace = [
            {'seq':1,'tick':0,'type':'budget','data':{'amount':self.case.visible_input['budget_minor']}},
            {'seq':2,'tick':0,'type':'authorize','data':r},
            {'seq':3,'tick':0,'type':'dispatch','data':{'operation':asdict(self.op)}}]
        self.ledger = [{'seq':1,'provider':'A','kind':'CREATE','operation_id':'op1','operation':asdict(self.op),
                        'tick':0,'phase':1,'reverses':None,'event_id':'A:1'}]

    def add_receipt(self):
        self.trace.append({'seq':4,'tick':0,'type':'receipt','data':{'status':'COMMITTED','provider':'A',
            'operation_id':'op1','payload_hash':self.op.payload_hash,'sealed':False}})

    def test_success_label_cannot_override_empty_ledger(self):
        row=evaluate(self.case, self.trace, [], {'completion_status':'success','commit_valid':True})
        self.assertFalse(row['completed_correctly'])
        self.assertTrue(row['false_success_claim'])

    def test_verified_clean_completion(self):
        self.add_receipt()
        row=evaluate(self.case,self.trace,self.ledger,{'completion_status':'success'})
        self.assertTrue(row['completed_correctly'])
        self.assertEqual(row['invalid_effects'],0)

    def test_receipt_without_matching_effect_cannot_complete(self):
        self.add_receipt()
        self.assertFalse(evaluate(self.case,self.trace,[],{'completion_status':'success'})['completed_correctly'])

    def test_authorized_old_effect_is_not_retroactively_invalid(self):
        self.add_receipt()
        r={**self.case.visible_input['requests'][0],'revision_id':2,'quantity':1}
        self.trace.append({'seq':5,'tick':1,'type':'authorize','data':r})
        row=evaluate(self.case,self.trace,self.ledger,{'completion_status':'pending_recovery'})
        self.assertEqual(row['invalid_effects'],0)
        self.assertFalse(row['completed_correctly'])

    def test_unapproved_old_payload_is_invalid_even_if_cancelled(self):
        r={**self.case.visible_input['requests'][0],'revision_id':2,'quantity':1}
        self.trace.insert(2,{'seq':2.5,'tick':0,'type':'authorize','data':r})
        self.ledger.append({**self.ledger[0],'seq':2,'kind':'CANCEL','tick':1,'reverses':1,'event_id':'A:2'})
        row=evaluate(self.case,self.trace,self.ledger,{'completion_status':'needs_review'})
        self.assertEqual(row['invalid_effects'],1)

    def test_duplicate_is_not_erased_by_cancellation(self):
        self.add_receipt()
        self.ledger.append({**self.ledger[0],'seq':2,'tick':1,'event_id':'A:2'})
        self.ledger.append({**self.ledger[0],'seq':3,'kind':'CANCEL','tick':2,'reverses':2,'event_id':'A:3'})
        row=evaluate(self.case,self.trace,self.ledger,{'completion_status':'success'})
        self.assertEqual(row['duplicate_effects'],1)
        self.assertFalse(row['completed_correctly'])

    def test_distinct_intents_with_identical_quantities_are_legitimate(self):
        self.add_receipt()
        r={**self.case.visible_input['requests'][0],'intent_id':'other'}
        op2=Operation('A','op2','other',1,r['quantity'],r['unit_price_minor'])
        self.trace.extend([
            {'seq':5,'tick':1,'type':'authorize','data':r},
            {'seq':6,'tick':1,'type':'dispatch','data':{'operation':asdict(op2)}},
            {'seq':7,'tick':1,'type':'receipt','data':{'status':'COMMITTED','provider':'A','operation_id':'op2',
             'payload_hash':op2.payload_hash,'sealed':False}}])
        self.ledger.append({**self.ledger[0],'seq':2,'operation_id':'op2','operation':asdict(op2),'tick':1,'event_id':'A:2'})
        row=evaluate(self.case,self.trace,self.ledger,{'completion_status':'success'})
        self.assertTrue(row['completed_correctly'])
        self.assertEqual(row['duplicate_effects'],0)

    def test_adapter_metadata_is_not_a_score(self):
        plain=evaluate(self.case,self.trace,self.ledger,{'completion_status':'needs_review'})
        fake=evaluate(self.case,self.trace,self.ledger,{'completion_status':'needs_review','invalid_effects':0,'score':1})
        self.assertEqual(plain,fake)

    def test_public_view_omits_hidden_outcomes(self):
        import json
        for case in make_cases('dev'):
            view=public_view(case,[])
            self.assertNotIn('hidden_schedule',view)
            self.assertNotIn('family',view)
            self.assertNotIn('obligations',view)
            self.assertNotIn('drop_after_once',json.dumps(view))

    def test_fixed_counts_and_unique_cases(self):
        cases=make_cases('eval')
        self.assertEqual(len(cases),120)
        self.assertEqual(len({c.case_id for c in cases}),120)
        self.assertEqual(len(make_cases('dev')),24)
        for family in {c.family for c in cases}:
            self.assertEqual(sum(c.family==family for c in cases),10)

    def test_unexercised_fault_not_scored_as_stress_success(self):
        case=next(c for c in make_cases('dev') if c.family=='F05')
        row=evaluate(case,self.trace,[],{'completion_status':'needs_review'})
        self.assertFalse(row['fault_exercised'])
        self.assertTrue(row['fault_not_exercised'])

if __name__=='__main__':
    unittest.main()
