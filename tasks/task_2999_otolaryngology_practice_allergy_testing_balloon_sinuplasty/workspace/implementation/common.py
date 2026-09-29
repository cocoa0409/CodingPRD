"""Shared request plumbing: rows, representations, lookups, cascades."""
import calc
import shape
import store
from errors import ApiError

VERSIONED = set(store.COLLECTIONS) - {"reaction_events"}


class Ctx(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def begin(roles):
    user_id, role = shape.authenticate(roles)
    return Ctx(user_id, role)


# --- row lifecycle -----------------------------------------------------------
def new_row(collection, fields):
    row = {"id": store.new_id()}
    row.update(fields)
    row["created_at"] = store.iso(store.now())
    if collection in VERSIONED:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row["_seq"] = store.next_seq()
    store.db[collection][row["id"]] = row
    return row


def touch(row):
    row["updated_at"] = store.iso(store.now())
    row["version"] = row["version"] + 1


def find(collection, row_id):
    row = store.db[collection].get(row_id)
    if row is None:
        raise ApiError(store.NOT_FOUND[collection])
    return row


def find_ref(collection, row_id):
    """Body-reference resolution (rung 5) — same 404 catalogue as rung 4."""
    return find(collection, row_id)


# --- representations ---------------------------------------------------------
def public(collection, row):
    if collection == "patients":
        row["age_months"] = calc.age_months(row)
    elif collection == "supply_lots":
        calc.refresh_lot(row)
    return dict((k, v) for k, v in row.items() if not k.startswith("_"))


def public_row(collection, row):
    return public(collection, row)


def sorted_rows(collection, predicate=None):
    items = store.rows(collection)
    if predicate is not None:
        items = [r for r in items if predicate(r)]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return items


def paginate(items, limit, offset):
    return items[offset:offset + limit]


def matches(row, filters):
    for key, value in filters.items():
        if row.get(key) != value:
            return False
    return True


# --- convenience joins ------------------------------------------------------
def policy_of_patient(patient):
    return store.db["payer_policies"][patient["payer_policy_id"]]


def patient_of_dose(dose):
    vial = store.db["immunotherapy_vials"][dose["immunotherapy_vial_id"]]
    return store.db["patients"][vial["patient_id"]]


# --- cascade fragments ------------------------------------------------------
def resize_ordered_orders(patient):
    """Reaction cascade hop three: re-derive observation on ORDERED orders."""
    policy = policy_of_patient(patient)
    for order in sorted_rows("allergy_test_orders",
                             lambda r: r["patient_id"] == patient["id"]
                             and r["status"] == "ORDERED"):
        order["observation_required_minutes"] = calc.observation_minutes(
            patient, policy, order["method"]
        )
        touch(order)


def flag_supervision_targets(patient):
    """Reaction cascade hop four: vials and bookings acquire their flags."""
    for vial in sorted_rows("immunotherapy_vials",
                            lambda r: r["patient_id"] == patient["id"]
                            and r["status"] in ("LABEL_VERIFIED", "IN_USE")):
        vial["requires_supervised_administration"] = True
        touch(vial)
    for booking in sorted_rows("procedure_bookings",
                               lambda r: r["patient_id"] == patient["id"]
                               and r["status"] == "SCHEDULED"):
        booking["requires_physician_presence"] = True
        touch(booking)


def set_shortfall_flags(lot, value):
    """Supply cascade hop three (and its reversal)."""
    for booking in sorted_rows("procedure_bookings",
                               lambda r: r["supply_lot_id"] == lot["id"]
                               and r["status"] == "SCHEDULED"):
        if value and booking["planned_device_count"] <= 0:
            continue
        if booking["supply_shortfall_flag"] == value:
            continue
        booking["supply_shortfall_flag"] = value
        touch(booking)


def lot_exhaustion_check(lot):
    """ACTIVE -> EXHAUSTED when available reaches zero, with hop three."""
    available = calc.refresh_lot(lot)
    if lot["status"] == "ACTIVE" and available == 0:
        lot["status"] = "EXHAUSTED"
        set_shortfall_flags(lot, True)


def lot_replenish_check(lot):
    """EXHAUSTED -> ACTIVE when availability returns, clearing the flags."""
    available = calc.refresh_lot(lot)
    if lot["status"] == "EXHAUSTED" and available > 0:
        lot["status"] = "ACTIVE"
        set_shortfall_flags(lot, False)


def retire_scope_cascade(scope):
    """Reprocessing-failure hop three."""
    for booking in sorted_rows("procedure_bookings",
                               lambda r: r["endoscope_asset_id"] == scope["id"]
                               and r["status"] == "SCHEDULED"):
        booking["scope_reassignment_required"] = True
        touch(booking)


def derive_immunotherapy_status(step):
    return "BUILD_UP" if step <= 6 else "MAINTENANCE"
