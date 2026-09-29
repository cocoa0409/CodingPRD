"""In-memory store. Starts empty on every boot; nothing is ever seeded."""
from datetime import datetime

import util
from errors import ApiError

# Logical clock origin (PRD 2.4). Never wall time.
CLOCK_ORIGIN = datetime(2026, 8, 1, 0, 0, 0, 0)

HOME_STATE_CODE = "MN"
STATE_CODES = ["MN", "TX", "NY", "WI", "FL", "CA", "PA"]

participants = {}
cases = {}
paternity_actions = {}
orders = {}
employers = {}
withholding_orders = {}
charges = {}
payments = {}
modification_reviews = {}
enforcement_actions = {}
interstate_referrals = {}
compromise_offers = {}

clock = CLOCK_ORIGIN
_seq = 0


def now():
    """The current logical clock instant."""
    return clock


def set_clock(instant):
    global clock
    clock = instant


def next_seq():
    global _seq
    _seq += 1
    return _seq


def stamp_new(row):
    """Attach id/created_at plus the mutable audit trio."""
    ts = now()
    row.setdefault("id", util.new_id())
    row["created_at"] = ts
    row["updated_at"] = ts
    row["version"] = 1
    row["_seq"] = next_seq()
    return row


def stamp_new_immutable(row):
    """ObligationCharge / PaymentTransaction: id + created_at only (PRD 2.4)."""
    row.setdefault("id", util.new_id())
    row["created_at"] = now()
    row["_seq"] = next_seq()
    return row


def touch(row):
    """Any mutation refreshes updated_at and increments version (PRD 2.4)."""
    if row is None:
        return None
    row["updated_at"] = now()
    row["version"] = row.get("version", 0) + 1
    return row


def ordered(rows):
    """Default ordering: ascending created_at, unconditionally (PRD 2.3)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def get_or_404(store, key, error_id):
    row = store.get(key) if isinstance(key, str) else None
    if row is None:
        raise ApiError(error_id)
    return row


def reset():
    """Test/debug helper. Not invoked at import time."""
    global clock, _seq
    for store in (participants, cases, paternity_actions, orders, employers,
                  withholding_orders, charges, payments, modification_reviews,
                  enforcement_actions, interstate_referrals, compromise_offers):
        store.clear()
    clock = CLOCK_ORIGIN
    _seq = 0


# -------------------------------------------------------------- traversal
def case_charges(case_id):
    return ordered([c for c in charges.values() if c["case_id"] == case_id])


def order_charges(order_id):
    return ordered([c for c in charges.values() if c["order_id"] == order_id])


def case_orders(case_id):
    return ordered([o for o in orders.values() if o["case_id"] == case_id])


def case_payments(case_id):
    return ordered([p for p in payments.values() if p["case_id"] == case_id])


def case_actions(case_id):
    return ordered([a for a in enforcement_actions.values() if a["case_id"] == case_id])


def case_referrals(case_id):
    return ordered([r for r in interstate_referrals.values() if r["case_id"] == case_id])


def case_offers(case_id):
    return ordered([o for o in compromise_offers.values() if o["case_id"] == case_id])


def case_paternity_action(case_id):
    rows = [p for p in paternity_actions.values() if p["case_id"] == case_id]
    return ordered(rows)[0] if rows else None


def order_iwos(order_id):
    return ordered([i for i in withholding_orders.values() if i["order_id"] == order_id])


def case_iwos(case_id):
    ids = {o["id"] for o in orders.values() if o["case_id"] == case_id}
    return ordered([i for i in withholding_orders.values() if i["order_id"] in ids])


def participant_cases(participant_id):
    return ordered([c for c in cases.values()
                    if c["custodial_party_id"] == participant_id
                    or c["noncustodial_party_id"] == participant_id])


def obligor_cases(participant_id):
    return ordered([c for c in cases.values()
                    if c["noncustodial_party_id"] == participant_id])
