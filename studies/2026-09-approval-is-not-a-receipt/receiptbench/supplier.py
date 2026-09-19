"""Independent SQLite supplier and environment-owned transport fault boundary.

The provider is cooperative. FINAL_NO_EFFECT and CANCELLED_CONFIRMED in this
fixture include an explicit persistent fence against late creates of that same
operation. An ordinary empty lookup is UNKNOWN, never a final absence claim.
"""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import json
import sqlite3
from .database import ClosingConnection
from .contracts import Capability, Operation, Receipt, OutcomeUnknown, canonical


def read_ledger(path: Path) -> list[dict]:
    """Evaluator-only interface. The controller gets neither this nor a DB path."""
    with sqlite3.connect(path, factory=ClosingConnection) as con:
        con.row_factory = sqlite3.Row
        rows = [dict(r) for r in con.execute('SELECT * FROM effects ORDER BY seq')]
    for row in rows:
        row['operation'] = json.loads(row.pop('payload'))
        row['event_id'] = f"{row['provider']}:{row['seq']}"
    return rows


class Supplier:
    def __init__(self, path: Path, capability: Capability, retention_ticks: int | None,
                 *, provider: str = 'A'):
        self.path = Path(path)
        self.capability = Capability(capability)
        self.retention_ticks = retention_ticks
        self.provider = provider
        if self.capability == Capability.EXPIRING and (
            type(retention_ticks) is not int or retention_ticks < 1
        ):
            raise ValueError('Expiring contract requires a positive retention')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript('''
                CREATE TABLE IF NOT EXISTS configuration(k TEXT PRIMARY KEY,v TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS effects(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT NOT NULL,
                    kind TEXT NOT NULL, operation_id TEXT NOT NULL, payload TEXT NOT NULL,
                    tick INTEGER NOT NULL, phase INTEGER NOT NULL, reverses INTEGER);
                CREATE TABLE IF NOT EXISTS request_keys(
                    operation_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL,
                    expires_at INTEGER, created_tick INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS cancellations(
                    cancellation_id TEXT PRIMARY KEY, operation_id TEXT NOT NULL,
                    due INTEGER NOT NULL, finished INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS tombstones(
                    operation_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL,
                    status TEXT NOT NULL, tick INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS visibility(
                    operation_id TEXT PRIMARY KEY, visible_at INTEGER NOT NULL DEFAULT 0,
                    cancel_delay INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS faults(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, operation_id TEXT NOT NULL,
                    verb TEXT NOT NULL, mode TEXT NOT NULL, release_tick INTEGER NOT NULL,
                    hits INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS pending_delivery(
                    operation_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                    attempt_id TEXT NOT NULL, due INTEGER NOT NULL, finished INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS fault_events(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, tick INTEGER NOT NULL,
                    operation_id TEXT NOT NULL, verb TEXT NOT NULL, mode TEXT NOT NULL);
            ''')
            current = canonical({'capability': self.capability.value,
                                 'retention_ticks': retention_ticks, 'provider': provider})
            row = con.execute("SELECT v FROM configuration WHERE k='contract'").fetchone()
            if row and row['v'] != current:
                raise ValueError('Cannot reopen a supplier with a different contract')
            con.execute("INSERT OR IGNORE INTO configuration VALUES('contract',?)", (current,))

    def connect(self):
        con = sqlite3.connect(self.path, timeout=10, factory=ClosingConnection)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA synchronous=FULL')
        return con

    def _receipt(self, con, op_id, status, payload_hash='', sealed=False, reason=''):
        version = con.execute('SELECT COALESCE(MAX(seq),0) FROM effects').fetchone()[0]
        return Receipt(status, self.provider, op_id, payload_hash, 0 if status == 'UNKNOWN' else version, sealed, reason)

    def create(self, op: Operation, attempt_id: str, tick: int, *, phase: int = 1) -> Receipt:
        if op.provider != self.provider or not attempt_id:
            raise ValueError('Provider/attempt mismatch')
        with self.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            tomb = con.execute('SELECT * FROM tombstones WHERE operation_id=?',
                               (op.operation_id,)).fetchone()
            if tomb:
                if tomb['payload_hash'] != op.payload_hash:
                    return self._receipt(con, op.operation_id, 'PARAMETER_MISMATCH', tomb['payload_hash'])
                return self._receipt(con, op.operation_id, tomb['status'], op.payload_hash, True)
            key = con.execute('SELECT * FROM request_keys WHERE operation_id=?',
                              (op.operation_id,)).fetchone()
            if key and key['expires_at'] is not None and tick >= key['expires_at']:
                con.execute('DELETE FROM request_keys WHERE operation_id=?', (op.operation_id,))
                key = None
            if key:
                if key['payload_hash'] != op.payload_hash:
                    return self._receipt(con, op.operation_id, 'PARAMETER_MISMATCH', key['payload_hash'])
                return self._receipt(con, op.operation_id, 'IDEMPOTENT_REPLAY', op.payload_hash)
            con.execute('INSERT INTO effects(provider,kind,operation_id,payload,tick,phase) '
                        'VALUES(?,?,?,?,?,?)',
                        (self.provider, 'CREATE', op.operation_id, canonical(asdict(op)), tick, phase))
            if self.capability != Capability.OPAQUE:
                expiry = tick + self.retention_ticks if self.retention_ticks is not None else None
                con.execute('INSERT INTO request_keys VALUES(?,?,?,?)',
                            (op.operation_id, op.payload_hash, expiry, tick))
            return self._receipt(con, op.operation_id, 'COMMITTED', op.payload_hash)

    def lookup(self, operation_id: str, tick: int) -> Receipt:
        self.advance(tick)
        with self.connect() as con:
            visibility = con.execute('SELECT visible_at FROM visibility WHERE operation_id=?',
                                     (operation_id,)).fetchone()
            if self.capability == Capability.OPAQUE or (visibility and tick < visibility[0]):
                return self._receipt(con, operation_id, 'UNKNOWN', reason='NONFINAL_LOOKUP')
            tomb = con.execute('SELECT * FROM tombstones WHERE operation_id=?', (operation_id,)).fetchone()
            if tomb:
                return self._receipt(con, operation_id, tomb['status'], tomb['payload_hash'], True)
            effect = con.execute("SELECT payload FROM effects WHERE operation_id=? AND kind='CREATE' LIMIT 1",
                                 (operation_id,)).fetchone()
            if effect:
                pending = con.execute('SELECT 1 FROM cancellations WHERE operation_id=? AND finished=0',
                                      (operation_id,)).fetchone()
                status = 'CANCEL_PENDING' if pending else 'COMMITTED'
                return self._receipt(con, operation_id, status, Operation(**json.loads(effect[0])).payload_hash)
            return self._receipt(con, operation_id, 'UNKNOWN', reason='NONFINAL_ABSENCE')

    def fence_absent(self, op: Operation, tick: int):
        """Environment's explicitly negotiated close-if-absent provider primitive."""
        if self.capability == Capability.OPAQUE:
            raise ValueError('Opaque provider has no final-absence capability')
        with self.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            if con.execute("SELECT 1 FROM effects WHERE operation_id=? AND kind='CREATE'",
                           (op.operation_id,)).fetchone():
                raise ValueError('Existing effect is not absent')
            con.execute('INSERT OR IGNORE INTO tombstones VALUES(?,?,?,?)',
                        (op.operation_id, op.payload_hash, 'FINAL_NO_EFFECT', tick))

    def set_visibility(self, operation_id: str, visible_at: int):
        with self.connect() as con:
            con.execute('INSERT INTO visibility(operation_id,visible_at) VALUES(?,?) '
                        'ON CONFLICT(operation_id) DO UPDATE SET visible_at=excluded.visible_at',
                        (operation_id, visible_at))

    def set_cancel_delay(self, operation_id: str, delay: int):
        if type(delay) is not int or delay < 0:
            raise ValueError('Invalid cancel delay')
        with self.connect() as con:
            con.execute('INSERT INTO visibility(operation_id,cancel_delay) VALUES(?,?) '
                        'ON CONFLICT(operation_id) DO UPDATE SET cancel_delay=excluded.cancel_delay',
                        (operation_id, delay))

    def request_cancel(self, operation_id: str, cancellation_id: str, tick: int) -> Receipt:
        with self.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            old = con.execute('SELECT * FROM cancellations WHERE cancellation_id=?',
                              (cancellation_id,)).fetchone()
            if old and old['operation_id'] != operation_id:
                return self._receipt(con, operation_id, 'PARAMETER_MISMATCH')
            effect = con.execute("SELECT payload FROM effects WHERE operation_id=? AND kind='CREATE' LIMIT 1",
                                 (operation_id,)).fetchone()
            if not effect:
                return self._receipt(con, operation_id, 'UNKNOWN', reason='CANCEL_HAS_NO_PROOF')
            payload_hash = Operation(**json.loads(effect[0])).payload_hash
            if self.capability == Capability.OPAQUE:
                return self._receipt(con, operation_id, 'CANCEL_PENDING', payload_hash,
                                     reason='NO_FINAL_CANCELLATION_CONTRACT')
            row = con.execute('SELECT cancel_delay FROM visibility WHERE operation_id=?',
                              (operation_id,)).fetchone()
            delay = row[0] if row else 0
            con.execute('INSERT OR IGNORE INTO cancellations(cancellation_id,operation_id,due) VALUES(?,?,?)',
                        (cancellation_id, operation_id, tick + delay))
        self.advance(tick)
        # A direct acknowledged cancellation can be authoritative before the status index updates.
        with self.connect() as con:
            tomb = con.execute('SELECT * FROM tombstones WHERE operation_id=?', (operation_id,)).fetchone()
            if tomb:
                return self._receipt(con, operation_id, tomb['status'], tomb['payload_hash'], True)
            return self._receipt(con, operation_id, 'CANCEL_PENDING', payload_hash)

    def advance(self, tick: int):
        """Process scheduled remote arrivals/cancellations; invisible to controllers."""
        with self.connect() as con:
            deliveries = [dict(r) for r in con.execute(
                'SELECT * FROM pending_delivery WHERE due<=? AND finished=0', (tick,))]
        for delivery in deliveries:
            self.create(Operation(**json.loads(delivery['payload'])), delivery['attempt_id'], tick, phase=0)
            with self.connect() as con:
                con.execute('UPDATE pending_delivery SET finished=1 WHERE operation_id=?',
                            (delivery['operation_id'],))
        with self.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            for cancel in list(con.execute('SELECT * FROM cancellations WHERE due<=? AND finished=0', (tick,))):
                op_id = cancel['operation_id']
                effects = list(con.execute("SELECT * FROM effects WHERE operation_id=? AND kind='CREATE'", (op_id,)))
                for effect in effects:
                    if not con.execute("SELECT 1 FROM effects WHERE kind='CANCEL' AND reverses=?", (effect['seq'],)).fetchone():
                        con.execute('INSERT INTO effects(provider,kind,operation_id,payload,tick,phase,reverses) '
                                    'VALUES(?,?,?,?,?,?,?)',
                                    (self.provider, 'CANCEL', op_id, effect['payload'], tick, 0, effect['seq']))
                if effects:
                    op = Operation(**json.loads(effects[0]['payload']))
                    con.execute('INSERT OR REPLACE INTO tombstones VALUES(?,?,?,?)',
                                (op_id, op.payload_hash, 'CANCELLED_CONFIRMED', tick))
                con.execute('UPDATE cancellations SET finished=1 WHERE cancellation_id=?',
                            (cancel['cancellation_id'],))

    def configure_fault(self, operation_id: str, verb: str, mode: str, release_tick: int = 0):
        with self.connect() as con:
            con.execute('INSERT INTO faults(operation_id,verb,mode,release_tick) VALUES(?,?,?,?)',
                        (operation_id, verb, mode, release_tick))

    def fault_for(self, operation_id: str, verb: str, tick: int):
        with self.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            for row in con.execute('SELECT * FROM faults WHERE operation_id=? AND verb=? ORDER BY id',
                                   (operation_id, verb)):
                if row['mode'].endswith('_once') and row['hits']:
                    continue
                if row['mode'] == 'drop_until' and tick >= row['release_tick']:
                    continue
                con.execute('UPDATE faults SET hits=hits+1 WHERE id=?', (row['id'],))
                con.execute('INSERT INTO fault_events(tick,operation_id,verb,mode) VALUES(?,?,?,?)',
                            (tick, operation_id, verb, row['mode']))
                return dict(row)
        return None

    def fault_events(self) -> list[dict]:
        with self.connect() as con:
            return [dict(r) for r in con.execute('SELECT * FROM fault_events ORDER BY seq')]


class SupplierEndpoint:
    """Transport-neutral service handler. The HTTP adapter closes real sockets on loss."""
    def __init__(self, supplier: Supplier):
        self.supplier = supplier
        self.capability = supplier.capability
        self.retention_ticks = supplier.retention_ticks

    def create(self, op: Operation, attempt_id: str, tick: int) -> Receipt:
        self.supplier.advance(tick)
        fault = self.supplier.fault_for(op.operation_id, 'create', tick)
        if fault and fault['mode'] == 'drop_before_once':
            raise OutcomeUnknown('response unavailable')
        if fault and fault['mode'] == 'delay_once':
            with self.supplier.connect() as con:
                con.execute('INSERT OR IGNORE INTO pending_delivery(operation_id,payload,attempt_id,due) VALUES(?,?,?,?)',
                            (op.operation_id, canonical(asdict(op)), attempt_id, fault['release_tick']))
            raise OutcomeUnknown('response unavailable')
        receipt = self.supplier.create(op, attempt_id, tick)
        if fault and fault['mode'] in ('drop_after_once', 'drop_until'):
            raise OutcomeUnknown('response unavailable')
        return receipt

    def lookup(self, operation_id: str, tick: int) -> Receipt:
        return self.supplier.lookup(operation_id, tick)

    def request_cancel(self, operation_id: str, cancellation_id: str, tick: int) -> Receipt:
        fault = self.supplier.fault_for(operation_id, 'cancel', tick)
        result = self.supplier.request_cancel(operation_id, cancellation_id, tick)
        if fault:
            raise OutcomeUnknown('response unavailable')
        return result
