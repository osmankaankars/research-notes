import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
try:
    from receiptbench.contracts import Capability, Operation
    from receiptbench.supplier import Supplier, read_ledger
except ImportError:
    Supplier = None

class SupplierTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(Supplier, 'Supplier contract is not implemented')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'supplier.db'
        self.s = Supplier(self.path, Capability.DURABLE, None, provider='A')
        self.op = Operation('A', 'op1', 'intent1', 1, 100, 2000)

    def test_same_key_has_one_effect(self):
        self.assertEqual(self.s.create(self.op, 'a1', 0).status, 'COMMITTED')
        self.assertEqual(self.s.create(self.op, 'a2', 1).status, 'IDEMPOTENT_REPLAY')
        self.assertEqual(len(read_ledger(self.path)), 1)

    def test_payload_hash_ignores_attempt_and_is_immutable(self):
        before = self.op.payload_hash
        self.s.create(self.op, 'a1', 0)
        self.s.create(self.op, 'a2', 2)
        self.assertEqual(self.s.lookup('op1', 2).payload_hash, before)
        self.assertNotEqual(replace(self.op, quantity=60).payload_hash, before)

    def test_changed_payload_rejected(self):
        self.s.create(self.op, 'a1', 0)
        self.assertEqual(self.s.create(replace(self.op, quantity=60), 'a2', 1).status,
                         'PARAMETER_MISMATCH')
        self.assertEqual(len(read_ledger(self.path)), 1)

    def test_retention_boundary_can_duplicate(self):
        s = Supplier(Path(self.tmp.name)/'expiry.db', Capability.EXPIRING, 2, provider='A')
        s.create(self.op, 'a1', 0)
        self.assertEqual(s.create(self.op, 'a2', 1).status, 'IDEMPOTENT_REPLAY')
        self.assertEqual(s.create(self.op, 'a3', 2).status, 'COMMITTED')
        self.assertEqual(len(read_ledger(s.path)), 2)

    def test_opaque_does_not_claim_deduplication(self):
        s = Supplier(Path(self.tmp.name)/'opaque.db', Capability.OPAQUE, None, provider='A')
        s.create(self.op, 'a1', 0)
        s.create(self.op, 'a2', 1)
        self.assertEqual(s.lookup('op1', 1).status, 'UNKNOWN')
        self.assertEqual(len(read_ledger(s.path)), 2)

    def test_distinct_intents_are_not_deduplicated_by_quantity(self):
        self.s.create(self.op, 'a1', 0)
        self.s.create(replace(self.op, operation_id='op2', intent_id='intent2'), 'a2', 1)
        self.assertEqual(len(read_ledger(self.path)), 2)

    def test_empty_lookup_is_not_final(self):
        self.assertEqual(self.s.lookup('op1', 0).status, 'UNKNOWN')
        self.assertEqual(self.s.create(self.op, 'late', 5).status, 'COMMITTED')

    def test_fenced_absence_rejects_late_request(self):
        self.s.fence_absent(self.op, 1)
        self.assertEqual(self.s.lookup('op1', 2).status, 'FINAL_NO_EFFECT')
        self.assertEqual(self.s.create(self.op, 'late', 5).status, 'FINAL_NO_EFFECT')
        self.assertEqual(read_ledger(self.path), [])

    def test_cannot_fence_existing_effect_as_absent(self):
        self.s.create(self.op, 'a1', 0)
        with self.assertRaises(ValueError):
            self.s.fence_absent(self.op, 1)

    def test_cancellation_pending_retains_effect(self):
        self.s.create(self.op, 'a1', 0)
        self.s.set_cancel_delay('op1', 3)
        self.assertEqual(self.s.request_cancel('op1', 'c1', 1).status, 'CANCEL_PENDING')
        self.assertEqual(len(read_ledger(self.path)), 1)
        self.s.advance(4)
        self.assertEqual(self.s.lookup('op1', 4).status, 'CANCELLED_CONFIRMED')
        self.assertEqual([e['kind'] for e in read_ledger(self.path)], ['CREATE', 'CANCEL'])

    def test_reopen_preserves_key_and_effect(self):
        self.s.create(self.op, 'a1', 0)
        s = Supplier(self.path, Capability.DURABLE, None, provider='A')
        self.assertEqual(s.create(self.op, 'a2', 4).status, 'IDEMPOTENT_REPLAY')
        self.assertEqual(len(read_ledger(self.path)), 1)

    def test_cancelled_operation_cannot_resurrect_in_durable_contract(self):
        self.s.create(self.op, 'a1', 0)
        self.s.request_cancel('op1', 'c1', 1)
        self.assertEqual(self.s.create(self.op, 'a2', 5).status, 'CANCELLED_CONFIRMED')
        self.assertEqual(len(read_ledger(self.path)), 2)

    def test_quantities_must_be_positive_integers(self):
        for q in (0, -1, 1.5, True):
            with self.subTest(q=q), self.assertRaises(ValueError):
                replace(self.op, quantity=q)

    def test_opaque_unknown_reply_does_not_leak_hidden_ledger_version(self):
        from dataclasses import asdict
        a = Supplier(Path(self.tmp.name)/'world1.db', Capability.OPAQUE, None, provider='A')
        b = Supplier(Path(self.tmp.name)/'world2.db', Capability.OPAQUE, None, provider='A')
        a.create(self.op, 'a1', 0)
        self.assertEqual(asdict(a.lookup('op1', 1)), asdict(b.lookup('op1', 1)))

    def test_provider_identity_checked(self):
        with self.assertRaises(ValueError):
            self.s.create(replace(self.op, provider='B'), 'a1', 0)

if __name__ == '__main__':
    unittest.main()
