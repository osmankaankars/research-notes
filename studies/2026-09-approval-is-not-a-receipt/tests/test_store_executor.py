import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from receiptbench.contracts import Capability, Operation, Receipt, DispatchRejected
from receiptbench.supplier import Supplier, SupplierEndpoint, read_ledger
try:
    from receiptbench.intent_store import IntentStore
    from receiptbench.executor import Executor
except ImportError:
    IntentStore = None

class StoreExecutorTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(IntentStore, 'Intent store and executor are not implemented')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = IntentStore(self.root/'intent.db', initial_budget=1000000)
        self.store.authorize('i1', 1, 100, 200000, provider='A', unit_price_minor=2000, tick=0)
        self.op = Operation('A', 'i1:r1:o1', 'i1', 1, 100, 2000)
        self.a = Supplier(self.root/'a.db', Capability.DURABLE, None, provider='A')
        self.b = Supplier(self.root/'b.db', Capability.DURABLE, None, provider='B')
        self.clients = {'A': SupplierEndpoint(self.a), 'B': SupplierEndpoint(self.b)}

    def test_database_context_closes_connection(self):
        import sqlite3
        con = self.store.connect()
        with con:
            con.execute('SELECT 1')
        with self.assertRaises(sqlite3.ProgrammingError):
            con.execute('SELECT 1')

    def test_revision_cannot_erase_unknown_liability(self):
        self.store.record_dispatch(self.op, tick=0)
        self.store.mark_unknown(self.op.operation_id, tick=0)
        self.store.authorize('i1', 2, 60, 200000, provider='B', unit_price_minor=2000, tick=1)
        reopened = IntentStore(self.store.path)
        self.assertEqual(reopened.unresolved_liability('i1'), 200000)
        self.assertFalse(reopened.replacement_is_permitted('i1'))

    def test_old_revision_rejected_at_dispatch(self):
        self.store.authorize('i1', 2, 60, 200000, provider='B', unit_price_minor=2000, tick=1)
        with self.assertRaises(DispatchRejected):
            self.store.record_dispatch(self.op, tick=2)

    def test_revision_after_dispatch_does_not_retroactively_delete_it(self):
        self.store.record_dispatch(self.op, tick=0)
        self.store.authorize('i1', 2, 60, 200000, provider='B', unit_price_minor=2000, tick=1)
        self.assertEqual(self.store.operations('i1')[0]['payload']['quantity'], 100)
        self.assertEqual(self.store.reserved_total(), 200000)

    def test_concurrent_dispatch_cannot_overreserve_shared_budget(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        self.store.set_budget(300000, tick=0)
        self.store.authorize('i2', 1, 100, 200000, provider='A', unit_price_minor=2000, tick=0)
        barrier=threading.Barrier(2)
        def dispatch(op):
            barrier.wait(timeout=5)
            try:
                IntentStore(self.store.path).record_dispatch(op,tick=1)
                return 'recorded'
            except DispatchRejected:
                return 'blocked'
        op2=replace(self.op,operation_id='i2:r1:o1',intent_id='i2')
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(dispatch,[self.op,op2]))
        self.assertEqual(sorted(results),['blocked','recorded'])
        self.assertEqual(self.store.reserved_total(),200000)

    def test_shared_budget_reserves_unknown_requests(self):
        self.store.set_budget(300000, tick=0)
        self.store.record_dispatch(self.op, tick=0)
        self.store.authorize('i2', 1, 100, 200000, provider='A', unit_price_minor=2000, tick=1)
        with self.assertRaises(DispatchRejected):
            self.store.record_dispatch(replace(self.op, operation_id='i2:r1:o1', intent_id='i2'), tick=1)

    def test_existing_operation_payload_cannot_change(self):
        self.store.record_dispatch(self.op)
        with self.assertRaises(ValueError):
            self.store.record_dispatch(replace(self.op, quantity=60))

    def test_duplicate_authorization_version_is_immutable(self):
        with self.assertRaises(ValueError):
            self.store.authorize('i1', 1, 99, 200000)

    def test_unsealed_absence_is_not_accepted_as_final(self):
        self.store.record_dispatch(self.op)
        with self.assertRaises(ValueError):
            self.store.observe_receipt(self.op.operation_id,
                Receipt('FINAL_NO_EFFECT', 'A', self.op.operation_id, self.op.payload_hash))
        self.assertEqual(self.store.reserved_total(), 200000)

    def test_receipt_cannot_be_rebound_to_other_payload(self):
        self.store.record_dispatch(self.op)
        with self.assertRaises(ValueError):
            self.store.observe_receipt(self.op.operation_id, Receipt('COMMITTED', 'A', self.op.operation_id, 'wrong'))

    def test_cancel_request_is_not_a_cancellation(self):
        self.store.record_dispatch(self.op)
        self.store.observe_receipt(self.op.operation_id,
            Receipt('COMMITTED', 'A', self.op.operation_id, self.op.payload_hash))
        self.store.observe_receipt(self.op.operation_id,
            Receipt('CANCEL_PENDING', 'A', self.op.operation_id, self.op.payload_hash))
        self.assertFalse(self.store.replacement_is_permitted('i1'))
        self.assertEqual(self.store.reserved_total(), 200000)

    def test_final_no_effect_releases_reserved_liability(self):
        self.store.record_dispatch(self.op)
        self.a.fence_absent(self.op, 1)
        self.store.observe_receipt(self.op.operation_id, self.a.lookup(self.op.operation_id, 2))
        self.assertEqual(self.store.reserved_total(), 0)

    def test_replay_does_not_reserve_twice(self):
        self.store.record_dispatch(self.op)
        self.store.record_dispatch(self.op, tick=1)
        self.assertEqual(self.store.reserved_total(), 200000)

    def test_clean_executor_completes(self):
        executor = Executor('intent_scoped', self.store, self.clients)
        executor.step({'tick':0, 'requests':self.store.current_requests()})
        self.assertEqual(executor.report()['completion_status'], 'success')
        self.assertEqual(len(read_ledger(self.a.path)), 1)

    def test_strong_executor_resolves_old_order_before_replacement(self):
        self.a.configure_fault(self.op.operation_id, 'create', 'drop_after_once')
        executor = Executor('intent_scoped', self.store, self.clients)
        executor.step({'tick':0, 'requests':self.store.current_requests()})
        self.store.authorize('i1', 2, 60, 200000, provider='B', unit_price_minor=2000, tick=1)
        reopened = IntentStore(self.store.path)
        executor = Executor('intent_scoped', reopened, self.clients)
        for tick in range(1, 8):
            executor.step({'tick':tick, 'requests':reopened.current_requests()})
        self.assertEqual(executor.report()['completion_status'], 'success')
        self.assertEqual([x['kind'] for x in read_ledger(self.a.path)], ['CREATE', 'CANCEL'])
        self.assertEqual([x['operation']['quantity'] for x in read_ledger(self.b.path)], [60])

    def test_operation_scope_does_not_coordinate_revisions(self):
        self.a.configure_fault(self.op.operation_id, 'create', 'drop_after_once')
        executor = Executor('operation_scoped', self.store, self.clients)
        executor.step({'tick':0, 'requests':self.store.current_requests()})
        self.store.authorize('i1', 2, 60, 200000, provider='B', unit_price_minor=2000, tick=1)
        executor.step({'tick':1, 'requests':self.store.current_requests()})
        self.assertEqual(len(read_ledger(self.a.path)), 1)
        self.assertEqual(len(read_ledger(self.b.path)), 1)

    def test_crash_before_io_reuses_persisted_operation(self):
        self.store.record_dispatch(self.op, tick=0)
        executor = Executor('intent_scoped', IntentStore(self.store.path), self.clients)
        for tick in range(1, 4):
            executor.step({'tick':tick, 'requests':self.store.current_requests()})
        self.assertEqual(executor.report()['completion_status'], 'success')
        self.assertEqual(len(read_ledger(self.a.path)), 1)

    def test_opaque_timeout_remains_unknown_after_restart(self):
        a = Supplier(self.root/'opaque.db', Capability.OPAQUE, None, provider='A')
        a.configure_fault(self.op.operation_id, 'create', 'drop_after_once')
        clients = {'A':SupplierEndpoint(a), 'B':self.clients['B']}
        Executor('intent_scoped', self.store, clients).step({'tick':0, 'requests':self.store.current_requests()})
        executor = Executor('intent_scoped', IntentStore(self.store.path), clients)
        for tick in range(1, 5):
            executor.step({'tick':tick, 'requests':self.store.current_requests()})
        self.assertEqual(executor.report()['completion_status'], 'pending_recovery')
        self.assertEqual(self.store.reserved_total(), 200000)

if __name__ == '__main__':
    unittest.main()
