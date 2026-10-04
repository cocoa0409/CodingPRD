"""In-memory data store, entity serialisation and clock/identity plumbing.

Storage is a plain dict-of-dicts keyed by id.  It is never written to disk and
it starts empty on every boot: nothing here seeds, preloads or registers any
entity.  Every record a test needs is built through the declared API surface.
"""

import threading

from errors import ApiError, not_found
from utils import DEFAULT_CLOCK, d, fmt, new_id, parse_iso, round2, week_of

# ---------------------------------------------------------------------------
# Role model (PRD §2.1 / SCAFFOLD §1.7)
# ---------------------------------------------------------------------------
ROLES = (
    "EnrollmentOps",
    "ClinicalOps",
    "Clinician",
    "BillingOps",
    "Member",
    "EligibilityService",
    "OutreachService",
    "ClinicalReviewService",
)

# Roles whose X-User-ID is an opaque operator identity, tied to no entity.
OPAQUE_ROLES = (
    "EnrollmentOps",
    "ClinicalOps",
    "BillingOps",
    "EligibilityService",
    "OutreachService",
    "ClinicalReviewService",
)

# Roles whose X-User-ID is the id of a persisted entity.
ENTITY_ROLES = {"Clinician": "Clinician", "Member": "Member"}

_ENTITIES = (
    "ClientAccount",
    "ProgramTrack",
    "Member",
    "EligibilityFile",
    "Enrollment",
    "ClinicalReview",
    "ExerciseSession",
    "ClaimLine",
    "OutreachContact",
    "Clinician",
    "Appointment",
    "OutcomeMeasurement",
    "FeeInvoice",
    "CareTransition",
)

# Entities that carry the full id/created_at/updated_at/version set (PRD §2.5).
VERSIONED = (
    "ClientAccount",
    "Member",
    "EligibilityFile",
    "Enrollment",
    "ClinicalReview",
    "ExerciseSession",
    "ClaimLine",
    "OutreachContact",
    "Appointment",
    "OutcomeMeasurement",
    "FeeInvoice",
    "CareTransition",
)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    # -- lifecycle ---------------------------------------------------------
    def reset(self):
        self.records = {name: {} for name in _ENTITIES}
        self.order = {name: [] for name in _ENTITIES}
        self.clock = DEFAULT_CLOCK
        self.week_cursors = {}

    # -- access ------------------------------------------------------------

    def all(self, entity):
        return [self.records[entity][i] for i in self.order[entity]]

    def get(self, entity, ident):
        row = self.records[entity].get(ident)
        if row is None:
            return None
        return row

    def need(self, entity, ident, label=None):
        row = self.get(entity, ident)
        if row is None:
            raise not_found(label or entity)
        return row

    # -- mutation ----------------------------------------------------------
    def insert(self, entity, row):
        ident = row["id"]
        self.records[entity][ident] = row
        self.order[entity].append(ident)
        return row

    def touch(self, entity, row):
        """Refresh updated_at and bump version -- ordinary derived mutation.

        ProgramTrack and Clinician deliberately carry neither updated_at nor
        version (PRD 2.5), so the refresh is guarded on the field existing.
        """
        if "updated_at" in row:
            row["updated_at"] = fmt(self.clock)
        if "version" in row:
            row["version"] = row["version"] + 1
        return row

    def client_cursor(self, client_id):
        return self.week_cursors.get(client_id, 0)

    def set_client_cursor(self, client_id, value):
        self.week_cursors[client_id] = value


STORE = Store()


def current_week():
    return week_of(STORE.clock)


def set_clock(value):
    clock = parse_iso(value)
    if clock is None:
        raise ApiError(
            "ERR_INVALID_REFERENCE", "current_utc must be an ISO 8601 instant."
        )
    STORE.clock = clock
    return STORE.clock


def new_record(entity, fields):
    """Build a record skeleton: id, created_at, plus version/updated_at."""
    row = dict(fields)
    row["id"] = new_id()
    row["created_at"] = fmt(STORE.clock)
    if entity in VERSIONED:
        row["updated_at"] = fmt(STORE.clock)
        row["version"] = 1
    return row


def create(entity, fields, increments=()):
    row = new_record(entity, fields)
    STORE.insert(entity, row)
    for target, record in increments:
        STORE.touch(target, record)
    return row


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def member_red_flag_weight(member):
    """sum over red_flag_multipliers of (multiplier - 1.0), 2 dp, half up."""
    total = d(0)
    for multiplier in member.get("red_flag_multipliers") or []:
        total += d(multiplier) - d(1)
    return round2(total)


__all__ = [
    "STORE",
    "Store",
    "ROLES",
    "OPAQUE_ROLES",
    "ENTITY_ROLES",
    "VERSIONED",
    "create",
    "current_week",
    "fmt",
    "member_red_flag_weight",
    "new_id",
    "new_record",
    "parse_iso",
    "set_clock",
    "week_of",
]