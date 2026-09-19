"""Durable local dispatch, authority history, receipts and liabilities."""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import json
import sqlite3
from .database import ClosingConnection
from .contracts import Operation, Receipt, DispatchRejected, canonical

TERMINAL_CLEAR = ('FINAL_NO_EFFECT', 'CANCELLED_CONFIRMED')
UNCERTAIN = ('DISPATCH_RECORDED', 'OUTCOME_UNKNOWN', 'CANCEL_PENDING', 'CANCEL_UNKNOWN')

class IntentStore:
    def __init__(self, path: Path, initial_budget: int | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript('''
                CREATE TABLE IF NOT EXISTS budget(singleton INTEGER PRIMARY KEY CHECK(singleton=1),amount INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS revisions(
                    intent_id TEXT NOT NULL, revision_id INTEGER NOT NULL, quantity INTEGER NOT NULL,
                    ceiling_minor INTEGER NOT NULL, provider TEXT NOT NULL, unit_price_minor INTEGER NOT NULL,
                    PRIMARY KEY(intent_id,revision_id));
                CREATE TABLE IF NOT EXISTS operations(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, operation_id TEXT UNIQUE NOT NULL,
                    intent_id TEXT NOT NULL, revision_id INTEGER NOT NULL, payload TEXT NOT NULL,
                    payload_hash TEXT NOT NULL, state TEXT NOT NULL, reservation INTEGER NOT NULL,
                    dispatch_tick INTEGER NOT NULL, last_action TEXT NOT NULL DEFAULT '',
                    last_tick INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS receipts(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, operation_id TEXT NOT NULL,
                    tick INTEGER NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, tick INTEGER NOT NULL,
                    type TEXT NOT NULL, data TEXT NOT NULL);
            ''')
            if not con.execute('SELECT 1 FROM budget').fetchone():
                amount = 1000000 if initial_budget is None else initial_budget
                if type(amount) is not int or amount < 0:
                    raise ValueError('Budget must be nonnegative integer minor units')
                con.execute('INSERT INTO budget VALUES(1,?)', (amount,))
                self._event(con, 0, 'budget', {'amount':amount})

    def connect(self):
        con = sqlite3.connect(self.path, timeout=10, factory=ClosingConnection)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA synchronous=FULL')
        return con

    def _event(self, con, tick, kind, data):
        con.execute('INSERT INTO events(tick,type,data) VALUES(?,?,?)', (tick,kind,canonical(data)))

    def authorize(self, intent_id: str, revision_id: int, quantity: int, ceiling_minor: int,
                  *, provider: str='A', unit_price_minor: int=2000, tick: int=0):
        Operation(provider,'validate',intent_id,revision_id,quantity,unit_price_minor)
        if type(ceiling_minor) is not int or ceiling_minor < 0:
            raise ValueError('Invalid authorization ceiling')
        record = {'intent_id':intent_id,'revision_id':revision_id,'quantity':quantity,
                  'ceiling_minor':ceiling_minor,'provider':provider,'unit_price_minor':unit_price_minor}
        with self.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            old = con.execute('SELECT * FROM revisions WHERE intent_id=? AND revision_id=?',
                              (intent_id,revision_id)).fetchone()
            if old:
                if dict(old) != record:
                    raise ValueError('Authorization revision is immutable')
                return
            latest = con.execute('SELECT MAX(revision_id) FROM revisions WHERE intent_id=?', (intent_id,)).fetchone()[0]
            if latest is not None and revision_id <= latest:
                raise ValueError('Authorization revisions must increase')
            con.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?)', tuple(record.values()))
            self._event(con,tick,'authorize',record)

    def set_budget(self, amount: int, *, tick: int=0):
        if type(amount) is not int or amount < 0:
            raise ValueError('Budget must be nonnegative integer')
        with self.connect() as con:
            con.execute('UPDATE budget SET amount=?', (amount,))
            self._event(con,tick,'budget',{'amount':amount})

    def current_requests(self) -> list[dict]:
        with self.connect() as con:
            return [dict(r) for r in con.execute('''SELECT r.* FROM revisions r
                WHERE revision_id=(SELECT MAX(revision_id) FROM revisions WHERE intent_id=r.intent_id)
                ORDER BY intent_id''')]

    def operations(self, intent_id: str | None=None) -> list[dict]:
        with self.connect() as con:
            sql = 'SELECT * FROM operations' + (' WHERE intent_id=?' if intent_id else '') + ' ORDER BY seq'
            rows = [dict(r) for r in con.execute(sql, (intent_id,) if intent_id else ())]
        for row in rows:
            row['payload'] = json.loads(row['payload'])
        return rows

    def new_operation(self, request: dict) -> Operation:
        count = len([o for o in self.operations(request['intent_id']) if o['revision_id']==request['revision_id']])
        return Operation(request['provider'], f"{request['intent_id']}:r{request['revision_id']}:o{count+1}",
                         request['intent_id'],request['revision_id'],request['quantity'],request['unit_price_minor'])

    def record_dispatch(self, op: Operation, *, tick: int=0, strategy: str='intent_scoped'):
        with self.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            old = con.execute('SELECT * FROM operations WHERE operation_id=?',(op.operation_id,)).fetchone()
            if old:
                if old['payload_hash'] != op.payload_hash:
                    raise ValueError('Operation payload is immutable')
                return
            auth = con.execute('SELECT * FROM revisions WHERE intent_id=? ORDER BY revision_id DESC LIMIT 1',
                               (op.intent_id,)).fetchone()
            if not auth:
                raise DispatchRejected('No authority')
            if strategy != 'request_only':
                valid = (auth['revision_id']==op.revision_id and auth['quantity']==op.quantity
                         and auth['provider']==op.provider and auth['unit_price_minor']==op.unit_price_minor
                         and op.cost<=auth['ceiling_minor'])
                if not valid:
                    raise DispatchRejected('Current authorization does not cover this payload')
                reserved = con.execute('SELECT COALESCE(SUM(reservation),0) FROM operations').fetchone()[0]
                budget = con.execute('SELECT amount FROM budget').fetchone()[0]
                if reserved+op.cost>budget:
                    raise DispatchRejected('Shared funds already committed or reserved')
            if strategy=='intent_scoped' and con.execute(
                'SELECT 1 FROM operations WHERE intent_id=? AND reservation>0', (op.intent_id,)).fetchone():
                raise DispatchRejected('Prior commitment for this intent is not cleared')
            con.execute('''INSERT INTO operations(operation_id,intent_id,revision_id,payload,payload_hash,
                state,reservation,dispatch_tick) VALUES(?,?,?,?,?,?,?,?)''',
                (op.operation_id,op.intent_id,op.revision_id,canonical(asdict(op)),op.payload_hash,
                 'DISPATCH_RECORDED',op.cost,tick))
            self._event(con,tick,'dispatch',{'operation':asdict(op),'strategy':strategy})

    def mark_unknown(self, operation_id: str, *, tick: int=0, cancelling: bool=False):
        with self.connect() as con:
            con.execute('UPDATE operations SET state=? WHERE operation_id=?',
                        ('CANCEL_UNKNOWN' if cancelling else 'OUTCOME_UNKNOWN',operation_id))
            self._event(con,tick,'unknown',{'operation_id':operation_id,'cancelling':cancelling})

    def observe_receipt(self, operation_id: str, receipt: Receipt, *, tick: int=0):
        allowed = ('COMMITTED','IDEMPOTENT_REPLAY','UNKNOWN','FINAL_NO_EFFECT',
                   'CANCEL_PENDING','CANCELLED_CONFIRMED','PARAMETER_MISMATCH')
        if receipt.status not in allowed:
            raise ValueError('Unknown receipt type')
        with self.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT * FROM operations WHERE operation_id=?',(operation_id,)).fetchone()
            if not row:
                raise ValueError('Receipt has no local operation')
            op = Operation(**json.loads(row['payload']))
            if receipt.operation_id!=operation_id or receipt.provider!=op.provider:
                raise ValueError('Receipt identity mismatch')
            if receipt.status not in ('UNKNOWN','PARAMETER_MISMATCH') and receipt.payload_hash!=op.payload_hash:
                raise ValueError('Receipt payload mismatch')
            if receipt.status in TERMINAL_CLEAR and not receipt.sealed:
                raise ValueError('An unsealed observation cannot release a liability')
            state = receipt.status
            if state=='IDEMPOTENT_REPLAY': state='COMMITTED'
            if state in ('UNKNOWN','PARAMETER_MISMATCH'):
                state = 'CANCEL_UNKNOWN' if row['state'].startswith('CANCEL') else 'OUTCOME_UNKNOWN'
            reservation = 0 if state in TERMINAL_CLEAR else row['reservation']
            con.execute('UPDATE operations SET state=?,reservation=? WHERE operation_id=?',
                        (state,reservation,operation_id))
            con.execute('INSERT INTO receipts(operation_id,tick,payload) VALUES(?,?,?)',
                        (operation_id,tick,canonical(asdict(receipt))))
            self._event(con,tick,'receipt',asdict(receipt))

    def note_call(self, operation_id: str, action: str, tick: int) -> str:
        with self.connect() as con:
            con.execute('UPDATE operations SET last_action=?,last_tick=?,attempts=attempts+1 WHERE operation_id=?',
                        (action,tick,operation_id))
            row = con.execute('SELECT attempts FROM operations WHERE operation_id=?',(operation_id,)).fetchone()
            attempt_id=f'{operation_id}:a{row[0]}'
            self._event(con,tick,'tool_call',{'operation_id':operation_id,'action':action,'attempt_id':attempt_id})
            return attempt_id

    def note(self, kind: str, data: dict, tick: int):
        with self.connect() as con:
            self._event(con,tick,kind,data)

    def unresolved_liability(self, intent_id: str | None=None) -> int:
        return sum(r['reservation'] for r in self.operations(intent_id) if r['state'] in UNCERTAIN)

    def reserved_total(self) -> int:
        return sum(r['reservation'] for r in self.operations())

    def replacement_is_permitted(self, intent_id: str) -> bool:
        return not any(r['reservation'] for r in self.operations(intent_id))

    def events(self) -> list[dict]:
        with self.connect() as con:
            rows = [dict(r) for r in con.execute('SELECT * FROM events ORDER BY seq')]
        for r in rows: r['data']=json.loads(r['data'])
        return rows
