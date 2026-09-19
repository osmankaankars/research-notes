"""Wire contracts. No inference, credentials, or production connections."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json

class Capability(str, Enum):
    DURABLE = 'DURABLE'
    EXPIRING = 'EXPIRING'
    OPAQUE = 'OPAQUE'


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


@dataclass(frozen=True)
class Operation:
    provider: str
    operation_id: str
    intent_id: str
    revision_id: int
    quantity: int
    unit_price_minor: int

    def __post_init__(self):
        for name in ('provider', 'operation_id', 'intent_id'):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or len(value) > 128:
                raise ValueError(f'{name} must be a nonempty short string')
        for name in ('revision_id', 'quantity', 'unit_price_minor'):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f'{name} must be a positive integer')

    @property
    def payload_hash(self) -> str:
        return hashlib.sha256(canonical(asdict(self)).encode()).hexdigest()

    @property
    def cost(self) -> int:
        return self.quantity * self.unit_price_minor


@dataclass(frozen=True)
class Receipt:
    status: str
    provider: str
    operation_id: str
    payload_hash: str = ''
    ledger_version: int = 0
    sealed: bool = False
    reason: str = ''

    @classmethod
    def from_dict(cls, data: dict) -> 'Receipt':
        return cls(**data)


class OutcomeUnknown(ConnectionError):
    """No reliable response was received; this is not evidence of failure."""

class DispatchRejected(ValueError):
    """A local dispatch is outside the applicable authority or resource limit."""
