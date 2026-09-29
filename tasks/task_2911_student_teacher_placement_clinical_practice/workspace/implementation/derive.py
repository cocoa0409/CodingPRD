"""Lazy expiry transitions (PRD 2.8) and conserved derived quantities (PRD 2.9)."""

from decimal import Decimal

import calc
import clock
import store

NON_TERMINAL_PLACEMENT = ("PROPOSED", "ACTIVE", "REMOVAL_PENDING")
COMMITTED_PLACEMENT = ("ACTIVE", "REMOVAL_PENDING", "COMPLETED")
COMMITTED_STIPEND = ("ACCRUED", "APPROVED", "PAID")
COUNTED_CYCLE = ("SCHEDULED", "COMPLETED", "MISSED")


def _set(row, field, value):
    if row.get(field) != value:
        row[field] = value
        return True
    return False


# --- readiness items -------------------------------------------------------

def expire_item(item):
    """VERIFIED item whose expires_on is strictly behind the clock -> EXPIRED."""
    if item["status"] != "VERIFIED":
        return False
    expires_on = item.get("expires_on")
    if expires_on is None or not expires_on < clock.today():
        return False
    item["status"] = "EXPIRED"
    store.touch(item)
    return True


def sweep_candidate_items(candidate):
    changed = False
    for item in store.items_of(candidate["id"]):
        if expire_item(item):
            changed = True
    return changed


def _rolling_reference_start(candidate_id):
    best = None
    for placement in store.placements_of_candidate(candidate_id):
        if placement["placement_status"] not in (
                "ACTIVE", "REMOVAL_PENDING", "REMOVED", "COMPLETED"):
            continue
        start = placement["start_date"]
        if best is None or start > best:
            best = start
    return best


def _counted_items(candidate, variant):
    today = clock.today()
    reference_start = None
    if variant == "ROLLING":
        reference_start = _rolling_reference_start(candidate["id"])
    counted = []
    for item in store.items_of(candidate["id"]):
        status = item["status"]
        expires_on = item.get("expires_on")
        if variant == "STRICT":
            if status == "VERIFIED" and (expires_on is None
                                         or expires_on >= today):
                counted.append(item)
        else:
            if status == "VERIFIED":
                counted.append(item)
            elif (status == "EXPIRED" and expires_on is not None
                    and reference_start is not None
                    and expires_on > reference_start):
                counted.append(item)
    return counted


def evaluate_readiness(candidate, variant, force_touch=False):
    """Sweep expiries, re-score the gate, and record the variant used."""
    sweep_candidate_items(candidate)
    counted = _counted_items(candidate, variant)
    exam, clearance, coursework = calc.readiness_components(counted)
    score = exam + clearance + coursework
    status = calc.readiness_status(score, clearance,
                                   candidate["readiness_status"])
    changed = _set(candidate, "readiness_score", score)
    changed = _set(candidate, "readiness_status", status) or changed
    changed = _set(candidate, "readiness_variant_used", variant) or changed
    if changed or force_touch:
        store.touch(candidate)
    return status


# --- partnership agreements ------------------------------------------------

def expire_agreement(agreement):
    if agreement["status"] != "ACTIVE":
        return False
    if not agreement["window_end"] < clock.today():
        return False
    agreement["status"] = "EXPIRED"
    store.touch(agreement)
    return True


def derive_agreement_ledger(agreement):
    reserved = 0
    committed = 0
    money = 0
    for placement in store.placements_of_agreement(agreement["id"]):
        if placement["placement_status"] == "PROPOSED":
            reserved += 1
        if placement["placement_status"] in COMMITTED_PLACEMENT:
            committed += 1
        if placement["stipend_status"] in COMMITTED_STIPEND:
            money += int(placement["stipend_gross_cents"] or 0)
    posture = ("CAP_REACHED" if committed >= agreement["placement_cap"]
               else "OPEN")
    changed = _set(agreement, "seats_reserved", reserved)
    changed = _set(agreement, "seats_committed", committed) or changed
    changed = _set(agreement, "stipend_committed_cents", money) or changed
    changed = _set(agreement, "capacity_posture", posture) or changed
    if changed:
        store.touch(agreement)
    return changed


# --- cooperating teachers --------------------------------------------------

def expire_teacher_training(teacher):
    if teacher["qualification_status"] != "QUALIFIED":
        return False
    expires_on = teacher.get("training_expires_on")
    if expires_on is None or not expires_on < clock.today():
        return False
    teacher["qualification_status"] = "TRAINING_EXPIRED"
    store.touch(teacher)
    return True


def derive_teacher_counters(teacher):
    count = 0
    for placement in store.placements_of_teacher(teacher["id"]):
        if placement["placement_status"] in NON_TERMINAL_PLACEMENT:
            count += 1
    if _set(teacher, "active_placement_count", count):
        store.touch(teacher)
        return True
    return False


# --- placements, supervisors ----------------------------------------------

def supervisor_travel_miles(placement):
    supervisor = store.SUPERVISORS.get(placement["supervisor_id"])
    teacher = store.TEACHERS.get(placement["cooperating_teacher_id"])
    if supervisor is None or teacher is None:
        return 0
    return calc.manhattan(supervisor["home_grid_x"], supervisor["home_grid_y"],
                          teacher["site_grid_x"], teacher["site_grid_y"])


def derive_placement_points(placement):
    points = calc.stage_points(placement["placement_status"],
                               supervisor_travel_miles(placement))
    if _set(placement, "supervisor_points", points):
        store.touch(placement)
        return True
    return False


def derive_supervisor(supervisor):
    total = 0
    for placement in store.placements_of_supervisor(supervisor["id"]):
        derive_placement_points(placement)
        if placement["placement_status"] in NON_TERMINAL_PLACEMENT:
            total += int(placement["supervisor_points"] or 0)
    ceiling = calc.max_caseload_points(
        supervisor["employment_type"],
        supervisor.get("max_caseload_points_override"))
    changed = _set(supervisor, "caseload_points", total)
    changed = _set(supervisor, "max_caseload_points", ceiling) or changed
    if total >= ceiling and supervisor.get("accepting_new_placements"):
        # A recomputation only ever forces the flag false, never back to true.
        supervisor["accepting_new_placements"] = False
        changed = True
    if changed:
        store.touch(supervisor)
    return changed


# --- observation cycles ----------------------------------------------------

def miss_cycle(cycle):
    if cycle["status"] != "SCHEDULED":
        return False
    if clock.now() < cycle["window_end"]:
        return False
    cycle["status"] = "MISSED"
    store.touch(cycle)
    return True


def sweep_placement_cycles(placement):
    changed = False
    for cycle in store.cycles_of_placement(placement["id"]):
        if miss_cycle(cycle):
            changed = True
    return changed


def derive_placement_observations(placement, sweep=True):
    if sweep:
        sweep_placement_cycles(placement)
    counted = 0
    completed = 0
    summative = 0
    for cycle in store.cycles_of_placement(placement["id"]):
        if cycle["status"] in COUNTED_CYCLE:
            counted += 1
        if cycle["status"] == "COMPLETED":
            completed += 1
            if cycle["cycle_type"] == "SUMMATIVE":
                summative += 1
    ratio = calc.compliance_ratio(counted, completed)
    changed = _set(placement, "observation_compliance_ratio", ratio)
    changed = _set(placement, "summative_completed_count", summative) or changed
    if changed:
        store.touch(placement)
    return ratio


def cancel_scheduled_cycles(placement, note):
    """PROPOSED/ACTIVE cycles are held when a removal takes the placement."""
    for cycle in store.cycles_of_placement(placement["id"]):
        if cycle["status"] != "SCHEDULED":
            continue
        cycle["status"] = "CANCELLED_HOLD"
        cycle["resolution_note"] = note
        store.touch(cycle)


# --- placement requests ----------------------------------------------------

def derive_request_current_placement(request_row):
    """The newest placement of the request, unless it was voided outright."""
    current = None
    for placement in store.placements_of_request(request_row["id"]):
        if placement["placement_status"] == "VOIDED":
            current = None
        else:
            current = placement["id"]
    if _set(request_row, "current_placement_id", current):
        store.touch(request_row)
        return True
    return False


def ratio_is_one(placement):
    return Decimal(str(placement["observation_compliance_ratio"])) == Decimal("1")
