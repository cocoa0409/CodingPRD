"""Fields that are re-derived on every read (PRD 2.9) and the JSON serializers.

Recomputation on read is not a mutation: it never bumps `version` and never
refreshes `updated_at`.
"""
import calc
import clock
import db

UNASSIGNED_FULFILMENT = ("ZONE_CLEARED", "IN_PRODUCTION", "READY", "REMAKE_QUEUED")
CASH_STOP_STATUSES = ("DELIVERED", "REMADE")
COUNTED_STOP_STATUSES = ("PENDING", "DELIVERED", "REMADE")
BAG_RELEASED_DISPATCH = ("RETURNED", "SETTLED", "RECALLED", "CANCELLED")


# --- zone versions ------------------------------------------------------------

def zone_window_contains(version, instant):
    return version["effective_from"] <= instant < version["effective_to"]


def in_force_zone_version(store_id, instant=None):
    """The ACTIVE version of the store whose half-open window contains the clock."""
    if instant is None:
        instant = clock.now()
    candidates = [
        v
        for v in db.zone_versions.values()
        if v["store_id"] == store_id
        and v["status"] == "ACTIVE"
        and zone_window_contains(v, instant)
    ]
    if not candidates:
        return None
    return db.ordered(candidates)[-1]


def zone_version_by_number(store_id, version_number):
    for version in db.zone_versions.values():
        if version["store_id"] == store_id and version["version_number"] == version_number:
            return version
    return None


def pricing_zone_version(address):
    """The version used for mileage-to-minutes conversion on a stop insertion."""
    version = in_force_zone_version(address["store_id"])
    if version is not None:
        return version
    return zone_version_by_number(address["store_id"], address["evaluated_zone_version_number"])


# --- service addresses --------------------------------------------------------

def effective_zone_state(address):
    if address["override_state"] is not None and address["override_until"] is not None:
        if address["override_until"] > clock.now():
            return address["override_state"]
    return address["zone_state"]


# --- drivers ------------------------------------------------------------------

def driver_stops(driver_id):
    dispatch_ids = {d["id"] for d in db.dispatches.values() if d["driver_id"] == driver_id}
    return [s for s in db.stops.values() if s["dispatch_id"] in dispatch_ids]


def driver_collected_cents(driver_id):
    return sum(
        s["cash_collected_cents"]
        for s in driver_stops(driver_id)
        if s["status"] in CASH_STOP_STATUSES
    )


def driver_dropped_cents(driver_id):
    return sum(
        d["amount_cents"]
        for d in db.safe_drops.values()
        if d["driver_id"] == driver_id and d["status"] == "RECORDED"
    )


def driver_cash_on_hand(driver_id):
    return driver_collected_cents(driver_id) - driver_dropped_cents(driver_id)


def driver_cash_posture(driver):
    store = db.stores.get(driver["store_id"])
    limit = store["cash_limit_cents"] if store else 0
    return "DROP_REQUIRED" if driver_cash_on_hand(driver["id"]) >= limit else "CLEAR"


def driver_accrued_cents(driver_id):
    return sum(
        line["amount_cents"]
        for line in db.lines.values()
        if line["driver_id"] == driver_id and line["status"] == "ACCRUED"
    )


def newest_mvr_check(driver_id):
    """Greatest created_at, ties broken by the greater checked_on."""
    pulls = [p for p in db.mvr_checks.values() if p["driver_id"] == driver_id]
    if not pulls:
        return None
    return sorted(pulls, key=lambda p: (p["created_at"], p["checked_on"], p["_seq"]))[-1]


def driver_mvr_points(driver_id):
    newest = newest_mvr_check(driver_id)
    return newest["violation_points"] if newest else 0


def newest_insurance(driver_id):
    certificates = [c for c in db.insurance_verifications.values() if c["driver_id"] == driver_id]
    if not certificates:
        return None
    return db.ordered(certificates)[-1]


def driver_insurance_status(driver_id):
    newest = newest_insurance(driver_id)
    if newest is None:
        return "NONE"
    if newest["status"] == "VERIFIED":
        return "VERIFIED"
    return "REJECTED"


def insurance_covers(driver_id, instant):
    newest = newest_insurance(driver_id)
    if newest is None or newest["status"] != "VERIFIED":
        return False
    return newest["coverage_from"] <= instant < newest["coverage_to"]


# --- stores -------------------------------------------------------------------

def store_drivers(store_id):
    return [d for d in db.drivers.values() if d["store_id"] == store_id]


def store_cash_collected(store_id):
    return sum(driver_collected_cents(d["id"]) for d in store_drivers(store_id))


def store_safe_deposit(store_id):
    return sum(driver_dropped_cents(d["id"]) for d in store_drivers(store_id))


def store_driver_cash_total(store_id):
    return sum(driver_cash_on_hand(d["id"]) for d in store_drivers(store_id))


def unassigned_order_count(store_id):
    return sum(
        1
        for o in db.orders.values()
        if o["store_id"] == store_id and o["fulfillment_status"] in UNASSIGNED_FULFILMENT
    )


def active_zone_version_number(store_id):
    version = in_force_zone_version(store_id)
    return version["version_number"] if version else None


# --- dispatches ---------------------------------------------------------------

def dispatch_stops(dispatch_id):
    return sorted(
        [s for s in db.stops.values() if s["dispatch_id"] == dispatch_id],
        key=lambda s: s["sequence"],
    )


def counted_stops(dispatch_id):
    return [s for s in dispatch_stops(dispatch_id) if s["status"] in COUNTED_STOP_STATUSES]


def committed_hot_bag_slots(dispatch):
    if dispatch["status"] in BAG_RELEASED_DISPATCH:
        return 0
    return sum(s["hot_bag_slots"] for s in counted_stops(dispatch["id"]))


def dispatch_store(dispatch):
    driver = db.drivers.get(dispatch["driver_id"])
    if driver is None:
        return None
    return db.stores.get(driver["store_id"])
