import tempfile
import unittest
from pathlib import Path
import json
try:
    from receiptbench.runner import run_case, run_pack
except ImportError:
    run_case = None
from receiptbench.scenarios import make_cases

class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(run_case,'Matched runner is not implemented')
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.n=0
        self.cases=make_cases('dev')

    def unique(self):
        self.n+=1
        return self.root/f'run{self.n}'

    def case(self,family):
        return next(c for c in self.cases if c.family==family)

    def test_clean_completion_all_strategies(self):
        for strategy in ('request_only','operation_scoped','intent_scoped'):
            self.assertTrue(run_case(self.case('F01'),strategy,self.unique())['completed_correctly'])

    def test_request_only_exposes_duplicate_hazard(self):
        result=run_case(self.case('F05'),'request_only',self.unique())
        self.assertGreater(result['duplicate_effects'],0)
        self.assertTrue(result['fault_exercised'])

    def test_strong_recovers_revision_after_lost_reply(self):
        result=run_case(self.case('F10'),'intent_scoped',self.unique())
        self.assertTrue(result['completed_correctly'])
        self.assertEqual(result['invalid_effects'],0)

    def test_operation_scope_does_not_solve_cross_revision_workflow(self):
        result=run_case(self.case('F10'),'operation_scoped',self.unique())
        self.assertFalse(result['completed_correctly'])
        self.assertGreater(result['invalid_effects'],0)

    def test_relevant_pre_dispatch_change_is_not_applied_stale(self):
        result=run_case(self.case('F03'),'intent_scoped',self.unique())
        self.assertTrue(result['completed_correctly'])
        self.assertEqual(result['invalid_effects'],0)
        weak=run_case(self.case('F03'),'request_only',self.unique())
        self.assertGreater(weak['invalid_effects'],0)

    def test_irrelevant_change_does_not_block_completion(self):
        result=run_case(self.case('F02'),'intent_scoped',self.unique())
        self.assertTrue(result['completed_correctly'])

    def test_restart_uses_persisted_dispatch(self):
        result=run_case(self.case('F09'),'intent_scoped',self.unique())
        self.assertTrue(result['completed_correctly'])
        self.assertTrue(result['fault_exercised'])

    def test_opaque_paired_worlds_stay_unknown(self):
        from dataclasses import replace
        pair=[]
        for f in ('F05','F06'):
            c=self.case(f)
            visible=json.loads(json.dumps(c.visible_input))
            for contract in visible['supplier_contracts'].values():
                contract['capability']='OPAQUE';contract['retention_ticks']=None
                contract['confirmed_cancellation_fences_recreation']=False
            hidden=json.loads(json.dumps(c.hidden_schedule));hidden['events']=[]
            c=replace(c,capability='OPAQUE',retention_ticks=None,visible_input=visible,hidden_schedule=hidden)
            out=self.unique()
            row=run_case(c,'intent_scoped',out)
            self.assertTrue(row['safe_unresolved'])
            self.assertFalse(row['completed_correctly'])
            self.assertEqual(row['invalid_effects'],0)
            pair.append(json.loads((out/'observable_history.json').read_text()))
        self.assertEqual(pair[0],pair[1])

    def test_always_block_cannot_win_by_avoiding_the_fault(self):
        row=run_case(self.case('F05'),'always_block',self.unique())
        self.assertFalse(row['completed_correctly'])
        self.assertTrue(row['fault_not_exercised'])
        self.assertFalse(run_case(self.case('F01'),'always_block',self.unique())['completed_correctly'])

    def test_always_retry_exposes_duplicate_even_without_transport_fault(self):
        row=run_case(self.case('F01'),'always_retry',self.unique())
        self.assertGreater(row['duplicate_effects'],0)

    def test_deterministic_results_and_no_case_leakage(self):
        a=run_case(self.case('F10'),'intent_scoped',self.unique())
        run_case(self.case('F05'),'request_only',self.unique())
        b=run_case(self.case('F10'),'intent_scoped',self.unique())
        self.assertEqual(a,b)

    def test_future_private_events_do_not_change_past_actions(self):
        from dataclasses import replace
        case=self.case('F01')
        hidden=json.loads(json.dumps(case.hidden_schedule))
        revised={**case.visible_input['requests'][0],'revision_id':2,'quantity':60,'provider':'B'}
        hidden['events'].append({'kind':'revision','anchor':'first_create','offset':5,'data':revised})
        other=replace(case,hidden_schedule=hidden)
        first=self.unique();second=self.unique()
        run_case(case,'intent_scoped',first);run_case(other,'intent_scoped',second)
        a=json.loads((first/'observable_history.json').read_text())
        b=json.loads((second/'observable_history.json').read_text())
        self.assertEqual(a[:5],b[:5])

    def test_refuse_existing_output(self):
        out=self.unique()
        run_case(self.case('F01'),'intent_scoped',out)
        with self.assertRaises(FileExistsError):
            run_case(self.case('F01'),'intent_scoped',out)

    def test_competing_budget_keeps_reservations_and_later_progresses(self):
        result=run_case(self.case('F04'),'intent_scoped',self.unique())
        self.assertTrue(result['completed_correctly'])
        self.assertEqual(result['invalid_effects'],0)

    def test_duplicate_authorized_intents_both_complete(self):
        row=run_case(self.case('F12'),'intent_scoped',self.unique())
        self.assertTrue(row['completed_correctly'])
        self.assertEqual(row['duplicate_effects'],0)

    def test_cancel_confirmation_before_replacement(self):
        row=run_case(self.case('F11'),'intent_scoped',self.unique())
        self.assertTrue(row['completed_correctly'])
        self.assertEqual(row['invalid_effects'],0)

if __name__=='__main__':
    unittest.main()
