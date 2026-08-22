"""In-memory store. Every collection starts empty on every boot — nothing is
seeded, preloaded or hardcoded; all state is created by clients through the
declared endpoints."""

from datetime import datetime, timezone

from util import new_id, wall_now, fmt_iso

# PRD 2.5 — until the clock is explicitly moved it reads exactly this instant.
CLOCK_EPOCH_RAW = "2026-08-01T00:00:00Z"
CLOCK_EPOCH_DT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.properties = {}
        self.rate_cards = {}
        self.rate_card_lines = {}
        self.inventory_assets = {}
        self.sponsors = {}
        self.contracts = {}
        self.entitlements = {}
        self.bookings = {}
        self.proofs = {}
        self.staff_members = {}
        self.staff_assignments = {}
        self.surveys = {}
        self.clock_raw = CLOCK_EPOCH_RAW
        self.clock_dt = CLOCK_EPOCH_DT
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    # -- clock -------------------------------------------------------------
    def now(self):
        return self.clock_dt

    def now_raw(self):
        return self.clock_raw

    def set_clock(self, raw, parsed):
        self.clock_raw = raw
        self.clock_dt = parsed


store = Store()


# --------------------------------------------------------------------------
# row helpers
# --------------------------------------------------------------------------
def new_row(versioned=True):
    """A fresh row with identity + audit fields (PRD 2.4)."""
    created = wall_now()
    row = {
        "id": new_id(),
        "created_at": fmt_iso(created),
        "_seq": store.next_seq(),
        "_created": created,
    }
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def touch(row):
    """Record a mutation: refresh updated_at and bump version by exactly 1."""
    row["updated_at"] = wall_now_iso_now()
    row["version"] = row.get("version", 0) + 1
    return row


def wall_now_iso_now():
    return fmt_iso(wall_now())


def set_fields(row, **changes):
    """Apply changes, returning True when at least one value actually moved."""
    changed = False
    for key, value in changes.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    return changed


def touch_if(row, changed):
    if changed:
        touch(row)
    return changed


def ordered(rows):
    """PRD 2.3 — list results are ordered by created_at ascending."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# --------------------------------------------------------------------------
# graph navigation helpers
# --------------------------------------------------------------------------
def rate_cards_of_property(property_id):
    return [rc for rc in store.rate_cards.values() if rc["property_id"] == property_id]


def published_rate_cards(property_id):
    return [rc for rc in rate_cards_of_property(property_id) if rc["status"] == "PUBLISHED"]


def lines_of_card(rate_card_id):
    return ordered([l for l in store.rate_card_lines.values() if l["rate_card_id"] == rate_card_id])


def contracts_of_property(property_id):
    return [c for c in store.contracts.values() if c["property_id"] == property_id]


def contracts_of_sponsor(sponsor_id):
    return [c for c in store.contracts.values() if c["sponsor_id"] == sponsor_id]


def entitlements_of_contract(contract_id):
    return ordered([e for e in store.entitlements.values() if e["contract_id"] == contract_id])


def bookings_of_entitlement(entitlement_id):
    return ordered([b for b in store.bookings.values() if b["entitlement_id"] == entitlement_id])


def bookings_of_asset(inventory_asset_id):
    return ordered([b for b in store.bookings.values() if b["inventory_asset_id"] == inventory_asset_id])


def bookings_of_contract(contract_id):
    ids = set(e["id"] for e in store.entitlements.values() if e["contract_id"] == contract_id)
    return ordered([b for b in store.bookings.values() if b["entitlement_id"] in ids])


def proofs_of_booking(asset_booking_id):
    return ordered([p for p in store.proofs.values() if p["asset_booking_id"] == asset_booking_id])


def assignments_of_booking(asset_booking_id):
    return ordered([a for a in store.staff_assignments.values() if a["asset_booking_id"] == asset_booking_id])


def assignments_of_member(staff_member_id):
    return ordered([a for a in store.staff_assignments.values() if a["staff_member_id"] == staff_member_id])


def surveys_of_contract(contract_id):
    return ordered([s for s in store.surveys.values() if s["contract_id"] == contract_id])


def contract_of_entitlement(entitlement):
    return store.contracts.get(entitlement["contract_id"])


def contract_of_booking(booking):
    ent = store.entitlements.get(booking["entitlement_id"])
    if ent is None:
        return None
    return store.contracts.get(ent["contract_id"])
