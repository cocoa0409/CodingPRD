"""The weekly operations checkpoint (PRD §2.4, calculations.run_ops_week_advance).

Per elapsed week (oldest first), flocks of this complex in {GROWING, LAYING,
MOLT} are processed in creation order with the normative step order:
(1) auto-deplete at 80 weeks, (2) molt completion, (3) GROWING -> LAYING,
(4) lay accrual on the transitioned state, (5) mortality, (6) age += 1.
Then — for any week count including zero — the system-wide janitorial pass:
disease-event clearance, certification expiry, commitment expiry, capital
project promotion, region-wide posture recompute, and the complex's own
bookkeeping (ops_run_index, last_ops_run_at, version).
"""

from db import STORE, set_dt, touch
from calc import (
    ACTIVE_FLOCK_STATUSES,
    AUTO_DEPLETE_AGE_WEEKS,
    GROWING_WEEKS,
    MOLT_DURATION_WEEKS,
    UNGRADED_FIELD,
    WEEKLY_MORTALITY_BPS,
    house_of_flock,
    recompute_hen_inventory,
    recompute_postures,
    weekly_lay_dozen,
)


def run_ops(complex_):
    clock = STORE.clock
    last = complex_.get("_dt_last_ops_run_at") or clock
    weeks = max(0, (clock - last).days // 7)

    changed_flock_ids = []
    for _week in range(weeks):
        flocks = [
            f
            for f in STORE.flocks.values()
            if f["status"] in ACTIVE_FLOCK_STATUSES
            and (house_of_flock(f) or {}).get("complex_id") == complex_["id"]
        ]
        flocks.sort(key=lambda f: f["_seq"])
        for f in flocks:
            # (1) auto-depletion precedes molt completion
            if f["age_weeks"] >= AUTO_DEPLETE_AGE_WEEKS:
                f["status"] = "DEPLETED"
                f["current_hen_count"] = 0
                changed_flock_ids.append(f["id"])
                continue
            # (2) molt completion
            if (
                f["status"] == "MOLT"
                and f["age_weeks"] - (f["molt_start_age_weeks"] or 0)
                >= MOLT_DURATION_WEEKS
            ):
                f["status"] = "LAYING"
                f["molt_count"] = 1
                f["molt_start_age_weeks"] = None
            # (3) growing -> laying at 18 weeks
            elif f["status"] == "GROWING" and f["age_weeks"] >= GROWING_WEEKS:
                f["status"] = "LAYING"
            # (4) lay accrual on the transitioned state
            if f["status"] == "LAYING":
                complex_[UNGRADED_FIELD[f["program"]]] += weekly_lay_dozen(
                    f["current_hen_count"], f["age_weeks"], f["molt_count"]
                )
            # (5) mortality, floored per flock per week
            f["current_hen_count"] -= (
                f["current_hen_count"] * WEEKLY_MORTALITY_BPS
            ) // 10000
            # (6) age advance
            f["age_weeks"] += 1
            changed_flock_ids.append(f["id"])

    for fid in changed_flock_ids:
        touch(STORE.flocks[fid])

    # hen inventory of this complex's houses reflects mortality/depletion
    for house in STORE.houses.values():
        if house["complex_id"] == complex_["id"]:
            recompute_hen_inventory(house)

    _janitorial_pass(clock)

    complex_["ops_run_index"] += 1
    set_dt(complex_, "last_ops_run_at", clock)
    touch(complex_)


def _janitorial_pass(clock):
    # DiseaseEvent auto-clear: every depopulation order COMPLETED and every
    # scope house's downtime elapsed.
    for e in STORE.disease_events.values():
        if e["status"] != "CONFIRMED":
            continue
        orders = [
            o
            for o in STORE.depopulation_orders.values()
            if o["disease_event_id"] == e["id"]
        ]
        if not all(o["status"] == "COMPLETED" for o in orders):
            continue
        clearable = True
        for hid in e["scope_house_ids"]:
            house = STORE.houses.get(hid)
            if house is None:
                continue
            downtime_until = house.get("_dt_downtime_until")
            if downtime_until is not None and downtime_until > clock:
                clearable = False
                break
        if clearable:
            e["status"] = "CLEARED"
            set_dt(e, "cleared_at", clock)
            touch(e)

    # Certification expiry: PASSED -> EXPIRED once the clock reaches valid_until
    for c in STORE.certifications.values():
        valid_until = c.get("_dt_valid_until")
        if c["status"] == "PASSED" and valid_until is not None and clock >= valid_until:
            c["status"] = "EXPIRED"
            touch(c)

    # Commitment expiry: ACTIVE -> EXPIRED once the clock passes effective_to
    for cm in STORE.commitments.values():
        if cm["status"] == "ACTIVE" and clock > cm["_dt_effective_to"]:
            cm["status"] = "EXPIRED"
            touch(cm)

    # Capital project promotion: first checkpoint after approval
    for p in STORE.capital_projects.values():
        if p["status"] == "APPROVED":
            p["status"] = "IN_CONSTRUCTION"
            set_dt(p, "construction_started_at", clock)
            touch(p)

    recompute_postures()
