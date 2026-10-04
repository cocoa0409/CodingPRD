"""content_compensation_credit and archive_credit_ledger_invariant (§3.6)."""
from core import config as C

BASE_CREDIT_CENTS = 50000
NOMINAL_DURATION_SECONDS = 180
CONTRIBUTING_CLASS_FACTOR_BPS = {
    "CLASS_A": 10000,
    "CLASS_B": 9500,
    "CLASS_C": 8500,
    "CLASS_D": 8000,
}
REVISION_MULTIPLIER_STEP_BPS = 500
MIN_REVISION_MULTIPLIER_BPS = 5000
CONFERENCE_RATE_CENTS = 60000
DURATION_FACTOR_CAP_BPS = 20000
CAP_CENTS = 250000

PUBLISHED_BRANCH = ("LICENSED", "USED")


def duration_factor_bps(duration_seconds):
    computed = C.floor_div(
        C.d(duration_seconds or 0) * C.d(10000), C.d(NOMINAL_DURATION_SECONDS)
    )
    return min(DURATION_FACTOR_CAP_BPS, computed)


def compensation_credit_cents(contribution, station):
    """Three multiplies, each rounded half up; the published branch floors at
    the flat conference rate and the whole figure is capped."""
    duration_bps = duration_factor_bps(contribution.get("duration_seconds"))
    base_credit = C.r2c(C.d(BASE_CREDIT_CENTS) * C.d(duration_bps) / C.d(10000))
    cls = (station or {}).get("membership_class") or "CLASS_D"
    class_bps = C.d(CONTRIBUTING_CLASS_FACTOR_BPS.get(cls, 8000))
    class_credit = C.r2c(C.d(base_credit) * class_bps / C.d(10000))
    revision_count = int(contribution.get("revision_count") or 0)
    multiplier_bps = max(
        MIN_REVISION_MULTIPLIER_BPS,
        10000 - revision_count * REVISION_MULTIPLIER_STEP_BPS,
    )
    shelf_credit = C.r2c(C.d(class_credit) * C.d(multiplier_bps) / C.d(10000))
    if contribution.get("contribution_status") in PUBLISHED_BRANCH:
        raw = max(shelf_credit, CONFERENCE_RATE_CENTS)
    else:
        raw = shelf_credit
    return int(min(raw, CAP_CENTS))


def recompute_compensation(store, contribution):
    station = store.member_stations.get(contribution.get("station_id"))
    value = compensation_credit_cents(contribution, station)
    contribution["compensation_credit_cents"] = int(value)
    return int(value)


# --- archive_credit_ledger_invariant -----------------------------------------
INITIAL_SUM_CENTS = 0


def credit_conservation_sum(store, program):
    total = int(program.get("preliminary_license_credit_cents") or 0)
    for station in store.member_stations.values():
        credited = station.get("_credited_programs") or {}
        if program["id"] in credited:
            total += int(station.get("contribution_credit_cents") or 0)
            total += int(station.get("applied_relief_cents") or 0)
    return total


def conservation_holds(store, program):
    return credit_conservation_sum(store, program) == INITIAL_SUM_CENTS


def note_credited_program(station, program_id):
    credited = station.setdefault("_credited_programs", {})
    credited[program_id] = int(credited.get(program_id, 0)) + 1