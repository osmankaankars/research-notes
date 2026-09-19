import json
import os
import tempfile
import unittest
import multiprocessing as mp
from pathlib import Path
from dataclasses import replace
from receiptbench.contracts import Capability, Operation, OutcomeUnknown
from receiptbench.supplier import Supplier, read_ledger
from receiptbench.intent_store import IntentStore
from receiptbench.executor import Executor
from receiptbench.scenarios import make_cases
from receiptbench.runner import run_case
try:
    from receiptbench.http_supplier import HttpSupplierProcess, HttpSupplierClient
except ImportError:
    HttpSupplierProcess=None


def crashed_client(path, endpoint, cap, retention, request, op, send):
    store=IntentStore(Path(path),initial_budget=1000000)
    store.authorize(**request,tick=0)
    operation=Operation(**op)
    store.record_dispatch(operation,tick=0)
    if send:
        client=HttpSupplierClient(endpoint,Capability(cap),retention)
        attempt=store.note_call(operation.operation_id,'create',0)
        client.create(operation,attempt,0)
    # Intentionally bypass Python cleanup after durable local/remote commits.
    os._exit(23)

class HttpRestartTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(HttpSupplierProcess,'Loopback transport not implemented')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.op=Operation('A','i1:r1:o1','i1',1,100,2000)
        self.s=Supplier(self.root/'a.db',Capability.DURABLE,None,provider='A')
        self.service=HttpSupplierProcess(self.s.path,Capability.DURABLE,None,'A')
        self.service.start();self.addCleanup(self.service.stop)
        self.c=self.service.client

    def test_lost_reply_after_commit_has_an_actual_effect(self):
        self.s.configure_fault(self.op.operation_id,'create','drop_after_once')
        with self.assertRaises(OutcomeUnknown): self.c.create(self.op,'a1',0)
        self.assertEqual(len(read_ledger(self.s.path)),1)
        self.assertEqual(self.c.create(self.op,'a2',1).status,'IDEMPOTENT_REPLAY')
        self.assertEqual(len(read_ledger(self.s.path)),1)

    def test_lost_reply_before_commit_has_no_effect(self):
        self.s.configure_fault(self.op.operation_id,'create','drop_before_once')
        with self.assertRaises(OutcomeUnknown): self.c.create(self.op,'a1',0)
        self.assertEqual(read_ledger(self.s.path),[])
        self.assertEqual(self.c.lookup(self.op.operation_id,1).status,'UNKNOWN')

    def test_stale_lookup_is_nonfinal(self):
        self.c.create(self.op,'a1',0)
        self.s.set_visibility(self.op.operation_id,4)
        self.assertEqual(self.c.lookup(self.op.operation_id,1).status,'UNKNOWN')
        self.assertEqual(self.c.lookup(self.op.operation_id,4).status,'COMMITTED')

    def test_cancellation_lost_reply_is_not_assumed_failed(self):
        self.c.create(self.op,'a1',0)
        self.s.set_cancel_delay(self.op.operation_id,3)
        self.s.configure_fault(self.op.operation_id,'cancel','drop_after_once')
        with self.assertRaises(OutcomeUnknown): self.c.request_cancel(self.op.operation_id,'c1',1)
        self.assertEqual(self.c.lookup(self.op.operation_id,2).status,'CANCEL_PENDING')
        self.assertEqual(self.c.lookup(self.op.operation_id,4).status,'CANCELLED_CONFIRMED')

    def test_supplier_process_restart_retains_deduplication(self):
        self.c.create(self.op,'a1',0)
        self.service.stop();self.service.start()
        self.assertEqual(self.service.client.create(self.op,'a2',2).status,'IDEMPOTENT_REPLAY')
        self.assertEqual(len(read_ledger(self.s.path)),1)

    def test_actual_client_process_exit_before_receipt_persistence(self):
        self._restart_client(send=True)

    def test_actual_client_process_exit_before_network_send(self):
        self._restart_client(send=False)

    def _restart_client(self,send):
        from dataclasses import asdict
        req={'intent_id':'i1','revision_id':1,'quantity':100,'ceiling_minor':200000,'provider':'A','unit_price_minor':2000}
        path=self.root/'intent.db'
        p=mp.get_context('spawn').Process(target=crashed_client,args=(str(path),self.c.base_url,
             'DURABLE',None,req,asdict(self.op),send))
        p.start();p.join(10)
        if p.is_alive(): p.terminate();p.join();self.fail('Child did not exit')
        self.assertEqual(p.exitcode,23)
        store=IntentStore(path)
        self.assertEqual(store.unresolved_liability('i1'),200000)
        e=Executor('intent_scoped',store,{'A':self.c})
        for tick in range(1,5): e.step({'tick':tick,'requests':store.current_requests()})
        self.assertEqual(e.report()['completion_status'],'success')
        self.assertEqual(len(read_ledger(self.s.path)),1)

    def test_cross_revision_http_parity(self):
        case=next(c for c in make_cases('dev') if c.family=='F10')
        direct=run_case(case,'intent_scoped',self.root/'direct')
        http=run_case(case,'intent_scoped',self.root/'http',transport='http')
        self.assertEqual(direct,http)

    def test_reject_external_hosts_and_nonloopback_dns(self):
        for url in ('https://example.com','http://localhost:8000','http://127.0.0.1.evil:3','http://user@127.0.0.1:8'):
            with self.subTest(url=url),self.assertRaises(ValueError):
                HttpSupplierClient(url,Capability.DURABLE,None)

if __name__=='__main__':
    unittest.main()
