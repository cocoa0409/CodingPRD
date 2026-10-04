"""In-memory data store. Starts EMPTY on every boot — no seeding, ever."""

import uuid
from datetime import datetime, timezone

from errors import ApiError, ERR_INVALID_REQUEST

API_PREFIX = "/route-settlement"

# The logical clock's startup default. Before any clock-setting call the logical
# clock reads exactly this instant and MUST NOT fall back to real wall-clock time.
DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

# Every primary resource that carries the standard common field set.
COMMON_FIELD_TYPES = {
    "ServiceProvider",
    "ServiceArea",
    "RouteAssignment",
    "Agreement",
    "Vehicle",
    "Driver",
    "InsurancePolicy",
    "SettlementPeriod",
    "PerformanceMetric",
    "ChargebackClaim",
    "PeakSeasonDeclaration",
    "FuelIndexRate",
}

# Declared without the common field set: only `id` and `created_at` exist.
BARE_FIELD_TYPES = {"StopObservation", "SettlementDeduction", "Dispute"}

# /route-settlement/vehicles -> "Vehicle"
PATH_TO_TYPE = {
    "service-providers": "ServiceProvider",
    "service-areas": "ServiceArea",
    "route-assignments": "RouteAssignment",
    "agreements": "Agreement",
    "vehicles": "Vehicle",
    "drivers": "Driver",
    "insurance-policies": "InsurancePolicy",
    "settlement-periods": "SettlementPeriod",
    "performance-metrics": "PerformanceMetric",
    "chargeback-claims": "ChargebackClaim",
    "peak-season-declarations": "PeakSeasonDeclaration",
    "fuel-index-rates": "FuelIndexRate",
    "stop-observations": "StopObservation",
    "deductions": "SettlementDeduction",
    "disputes": "Dispute",
}


class Store:
    def __init__(self):
        self.rows = {}
        self.clock = DEFAULT_CLOCK
        self.duty_shift_seq = 0
        self.insert_seq = 0

    def next_seq(self):
        """Monotonic insertion counter.

        Ordering rules pin `created_at` ascending as the tie-break and never let
        the server-minted UUID participate, so two rows sharing an instant are
        ordered by the order the server created them.
        """
        self.insert_seq += 1
        return self.insert_seq

    def table(self, entity_type):
        return self.rows.setdefault(entity_type, {})

    def get(self, entity_type, row_id):
        return self.rows.get(entity_type, {}).get(row_id)

    def insert(self, entity_type, row):
        row.setdefault("_seq", self.next_seq())
        row.setdefault("created_at_dt", self.clock)
        if entity_type in COMMON_FIELD_TYPES:
            row.setdefault("id", str(uuid.uuid4()))
            now = iso_now(self.clock)
            row.setdefault("created_at", now)
            row.setdefault("updated_at", now)
            row.setdefault("version", 1)
        else:
            row.setdefault("id", str(uuid.uuid4()))
            row.setdefault("created_at", iso_now(self.clock))
        self.table(entity_type)[row["id"]] = row
        return row

    def touch(self, entity_type, row):
        """Refresh updated_at and bump version by one (common-field rows only)."""
        if entity_type in COMMON_FIELD_TYPES:
            row["updated_at"] = iso_now(self.clock)
            row["version"] = int(row.get("version", 1)) + 1
        return row

    def all(self, entity_type):
        return list(self.rows.get(entity_type, {}).values())


def iso_now(clock):
    """ISO 8601 UTC with three fractional digits: 2026-09-01T00:00:00.000Z"""
    return clock.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime.

    Accepts a trailing Z or an explicit offset; a naive value is read as UTC.
    Raises ApiError(ERR_INVALID_REQUEST) for anything unparseable.
    """
    if value is None:
        raise ApiError(ERR_INVALID_REQUEST, "timestamp is required")
    if isinstance(value, datetime):
        dt = value
    else:
        if not isinstance(value, str):
            raise ApiError(ERR_INVALID_REQUEST, "timestamp must be an ISO 8601 string")
        text = value.strip()
        if not text:
            raise ApiError(ERR_INVALID_REQUEST, "timestamp must not be empty")
        normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
        try:
            dt = datetime.fromisoformat(normalized)
        except ValueError:
            raise ApiError(ERR_INVALID_REQUEST, "timestamp is not ISO 8601: %s" % text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


db = Store()