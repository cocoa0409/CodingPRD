"""In-memory data store.

Every collection starts empty on each boot; nothing is seeded, preloaded or
hardcoded. Entities only ever come into existence through the declared API
surface. Keys beginning with ``_`` are server-internal and never serialized.
"""

import uuid

import clock

# --- §2.5 collections -------------------------------------------------------
CUSTOMERS = {}
FULFILLMENT_CENTERS = {}
SUPPLIERS = {}
SUPPLY_LOTS = {}
SOURCING_BIDS = {}
CONVENTIONAL_QUOTES = {}
BOX_ORDERS = {}
BOX_BUILD_ITEMS = {}
COLD_CHAIN_PACKS = {}
QUALITY_CLAIMS = {}
SUBSCRIPTIONS = {}

ALL_COLLECTIONS = (
    CUSTOMERS,
    FULFILLMENT_CENTERS,
    SUPPLIERS,
    SUPPLY_LOTS,
    SOURCING_BIDS,
    CONVENTIONAL_QUOTES,
    BOX_ORDERS,
    BOX_BUILD_ITEMS,
    COLD_CHAIN_PACKS,
    QUALITY_CLAIMS,
    SUBSCRIPTIONS,
)

SEQUENCE = {"value": 0}


def next_sequence():
    SEQUENCE["value"] += 1
    return SEQUENCE["value"]


def new_id():
    return str(uuid.uuid4())


def new_row(fields=None, immutable=False):
    """Mint a row carrying the §2.5 common properties.

    ``immutable`` rows (ColdChainPack) carry only ``id`` and ``created_at``;
    every other resource also carries ``updated_at`` and ``version``.
    """
    row = {"id": new_id(), "created_at": clock.now_iso(), "_seq": next_sequence()}
    if not immutable:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    if fields:
        row.update(fields)
    return row


def touch(row):
    """Refresh the §2.5 mutation properties; immutable rows are left alone."""
    if "version" not in row:
        return
    row["updated_at"] = clock.now_iso()
    row["version"] = row.get("version", 1) + 1


def serialise(row):
    """Strip server-internal keys for the response payload."""
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def serialise_many(rows):
    return [serialise(r) for r in rows]


def by_created(rows):
    """§2.3 default ordering: creation timestamp ascending."""
    return sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))


def created_before(left, right):
    """True when ``left`` was created strictly earlier than ``right``."""
    return (left.get("created_at", ""), left.get("_seq", 0)) < \
           (right.get("created_at", ""), right.get("_seq", 0))


def of(collection, **filters):
    """Rows matching every supplied equality filter."""
    out = []
    for row in collection.values():
        if all(row.get(k) == v for k, v in filters.items()):
            out.append(row)
    return out