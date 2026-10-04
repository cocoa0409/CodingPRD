"""In-memory object store, logical clock and identifier helpers.

Nothing is persisted: a fresh process starts with every map empty. The
implementation encodes the system (state machines, calculations, validations)
and never owns data — every entity a caller sees was created through the API.
"""

import uuid

# The logical clock's startup default, per PRD §2.5. The server must never
# substitute real wall-clock time for it before the clock is explicitly set.
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

# Fixed number of entities in the graph (PRD §2.4: "every one of the fourteen
# resources"); used only to sanity-check the map registry, not to seed.
ENTITY_KINDS = (
    "manufacturers",
    "drugs",
    "pharmacies",
    "licenses",
    "prices",
    "patients",
    "prescribers",
    "prescriptions",
    "requests",
    "orders",
    "shipments",
    "claims",
    "comparisons",
    "substantiations",
)


class Store:
    """A flat bag of maps keyed by entity id, plus the logical clock."""

    def __init__(self):
        self.manufacturers = {}
        self.drugs = {}
        self.pharmacies = {}
        self.licenses = {}
        self.prices = {}
        self.patients = {}
        self.prescribers = {}
        self.prescriptions = {}
        self.requests = {}
        self.orders = {}
        self.shipments = {}
        self.claims = {}
        self.comparisons = {}
        self.substantiations = {}
        self.current_utc = DEFAULT_CLOCK_ISO


store = Store()


def new_id():
    """A plain UUID with no type prefix or separator convention (PRD §2.4)."""
    return str(uuid.uuid4())