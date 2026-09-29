"""
Lightweight typing aliases and small record containers shared by the suite.

These are convenience aliases only: nothing here performs validation, and no test
depends on them structurally. They exist so fixture signatures read clearly.
"""

from typing import Any, Dict, List, NamedTuple, Optional, Tuple

# A parsed JSON object taken from the ``data`` field of a success envelope.
Json = Dict[str, Any]

# A list of parsed JSON objects taken from an array response.
JsonList = List[Json]

# The header dictionary handed to every api_client call.
Headers = Dict[str, str]

# The (data, meta) pair returned by the paginated validator.
Page = Tuple[JsonList, Json]


class DonorChain(NamedTuple):
    """A donor advanced to a known point plus the ids created along the way."""

    donor: Json
    donor_id: str
    screening_record_ids: List[str]
    panel_id: Optional[str]


class RecoveryChain(NamedTuple):
    """A completed recovery and the tissues it produced."""

    donor_id: str
    technician_id: str
    recovery: Json
    recovery_id: str
    tissues: JsonList


class GradedTissue(NamedTuple):
    """A tissue with both evaluations recorded, optionally classified."""

    tissue_id: str
    tissue: Json
    donor_id: str
    recovery_id: str
    evaluator_technician_id: str


class RequestChain(NamedTuple):
    """A surgeon plus one open request."""

    surgeon_id: str
    surgeon: Json
    request_id: str
    request: Json


class ShipmentChain(NamedTuple):
    """An allocation carried all the way to a dispatched shipment."""

    tissue_id: str
    surgeon_id: str
    request_id: str
    allocation_id: str
    shipment_id: str
    shipment: Json


__all__ = [
    "Json",
    "JsonList",
    "Headers",
    "Page",
    "DonorChain",
    "RecoveryChain",
    "GradedTissue",
    "RequestChain",
    "ShipmentChain",
]
