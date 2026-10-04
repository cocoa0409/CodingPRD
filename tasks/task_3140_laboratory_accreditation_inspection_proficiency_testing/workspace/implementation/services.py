from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

import store
from util import fmt_ts

CYCLE_OPEN_STATUSES = {"TEAM_ASSEMBLY", "SCREENED", "CONDUCTED", "FINDINGS_ISSUED"}
CYCLE_CONDUCTED_ONWARD = {
    "CONDUCTED",
    "FINDINGS_ISSUED",
    "DECIDED",
    "APPEALED",
    "INTERIM_SELF_INSPECTION",
    "RE_DECIDED",
}
INVESTIGATION_NONTERMINAL = {"OPEN", "UNDER_REVIEW", "CORRECTIVE_ACTION_REQUIRED"}


# ---------------------------------------------------------------------------
# Derived-field helpers
# ---------------------------------------------------------------------------

def touch(rec):
    rec["version"] += 1
    rec["updated_at"] = fmt_ts(store.now())


def recompute_lab_count(lab_id):
    lab = store.STORES["laboratories"].get(lab_id)
    if not lab:
        return
    count = sum(
        1
        for e in store.STORES["enrollments"].values()
        if e["laboratory_id"] == lab_id and e["status"] == "ACTIVE"
    )
    if lab["active_discipline_count"] != count:
        lab["active_discipline_count"] = count
        touch(lab)


def set_enrollment_status(enr, new_status):
    if enr["status"] == new_status:
        return
    enr["status"] = new_status
    touch(enr)
    recompute_lab_count(enr["laboratory_id"])
    refresh_postures_for_laboratory(enr["laboratory_id"])


def lab_to_probation(lab):
    lab["accreditation_status"] = "PROBATION"
    touch(lab)
    for enr in store.STORES["enrollments"].values():
        if enr["laboratory_id"] == lab["id"] and enr["status"] == "ACTIVE":
            set_enrollment_status(enr, "SUSPENDED")
    for ins in store.STORES["inspector_profiles"].values():
        if ins["affiliated_laboratory_id"] == lab["id"] and ins["status"] == "ACTIVE":
            ins["status"] = "SUSPENDED"
            touch(ins)
    recompute_lab_count(lab["id"])


def apply_lab_decision(lab, decision):
    if decision == "ACCREDITED":
        if lab["accreditation_status"] == "ENROLLED":
            lab["accreditation_status"] = "ACCREDITED"
            touch(lab)
    elif decision == "DENIED":
        if lab["accreditation_status"] in ("ENROLLED", "ACCREDITED"):
            lab_to_probation(lab)


# ---------------------------------------------------------------------------
# PT standing recomputation
# ---------------------------------------------------------------------------

def graded_events(enrollment_id):
    out = []
    for r in store.STORES["pt_results"].values():
        if r["status"] != "GRADED":
            continue
        ship = store.STORES["pt_shipments"].get(r["shipment_id"])
        if not ship:
            continue
        sub = store.STORES["pt_subscriptions"].get(ship["subscription_id"])
        if not sub or sub["enrollment_id"] != enrollment_id:
            continue
        out.append((ship["_shipped_dt"], r["_seq"], r))
    out.sort(key=lambda t: (t[0], t[1]))
    return [t[2] for t in out]


def recompute_standing(enr):
    events = graded_events(enr["id"])
    if events:
        last = events[-1]
        enr["standing_per_event"] = (
            "UNSATISFACTORY" if last["event_evaluation"] == "UNSATISFACTORY" else "SATISFACTORY"
        )
        n = len(events)
        window = events[-min(3, n):]
        unsat = sum(1 for e in window if e["event_evaluation"] == "UNSATISFACTORY")
        enr["standing_rolling"] = (
            "UNSATISFACTORY" if (n >= 2 and unsat >= 2) else "SATISFACTORY"
        )
        streak = 0
        for e in reversed(events):
            if e["event_evaluation"] == "UNSATISFACTORY":
                streak += 1
            else:
                break
        enr["unsuccessful_event_streak"] = streak
    else:
        enr["standing_per_event"] = "SATISFACTORY"
        enr["standing_rolling"] = "SATISFACTORY"
        enr["unsuccessful_event_streak"] = 0


def nonterminal_investigation(enrollment_id):
    for inv in store.STORES["pt_investigations"].values():
        if inv["enrollment_id"] == enrollment_id and inv["status"] in INVESTIGATION_NONTERMINAL:
            return inv
    return None


def maybe_open_investigation(enr, result_id):
    pe_unsat = enr["standing_per_event"] == "UNSATISFACTORY"
    ro_unsat = enr["standing_rolling"] == "UNSATISFACTORY"
    if not (pe_unsat or ro_unsat):
        return None
    if nonterminal_investigation(enr["id"]):
        return None
    if pe_unsat and ro_unsat:
        variant = "BOTH"
    elif pe_unsat:
        variant = "PER_EVENT"
    else:
        variant = "ROLLING"
    inv = {
        "enrollment_id": enr["id"],
        "trigger_variant": variant,
        "status": "OPEN",
        "corrective_action_notes": None,
        "linked_result_ids": [result_id],
    }
    return inv


# ---------------------------------------------------------------------------
# Inspection-cycle burden + posture
# ---------------------------------------------------------------------------

def compute_burden(cycle_id):
    total = 0
    for f in store.STORES["inspection_findings"].values():
        if f["inspection_cycle_id"] != cycle_id:
            continue
        if f["status"] not in ("CITED", "RESPONSE_SUBMITTED", "ESCALATED"):
            continue
        section = store.STORES["sections"].get(f["section_id"])
        base = 4 if f["deficiency_level"] == "LEVEL_2" else 2
        mult = 2 if (section and section.get("critical_testing")) else 1
        total += base * mult
    return total


def recompute_burden(cycle_id):
    cycle = store.STORES["inspection_cycles"].get(cycle_id)
    if not cycle:
        return
    cycle["deficiency_burden_score"] = compute_burden(cycle_id)


def compute_posture(lab_id):
    enrollments = [
        e for e in store.STORES["enrollments"].values() if e["laboratory_id"] == lab_id
    ]
    active = [e for e in enrollments if e["status"] == "ACTIVE"]
    if not active:
        return False
    active_ids = {e["id"] for e in active}
    for sec in store.STORES["sections"].values():
        if sec["enrollment_id"] in active_ids and sec["checklist_status"] != "ASSIGNED":
            return False
    for p in store.STORES["personnel_records"].values():
        if p["enrollment_id"] in active_ids and p["qualification_status"] != "QUALIFIED":
            return False
    for e in active:
        ok = any(
            mv["enrollment_id"] == e["id"] and mv["status"] == "APPROVED"
            for mv in store.STORES["method_validations"].values()
        )
        if not ok:
            return False
    return True


def refresh_postures_for_laboratory(lab_id):
    posture = compute_posture(lab_id)
    for cycle in store.STORES["inspection_cycles"].values():
        if cycle["laboratory_id"] == lab_id and cycle["posture_ready"] != posture:
            cycle["posture_ready"] = posture
            touch(cycle)


# ---------------------------------------------------------------------------
# Business-day helper
# ---------------------------------------------------------------------------

def add_business_days_end(dt, n):
    """Return 23:59:59Z on the nth business day strictly after date(dt)."""
    d = dt.date()
    counted = 0
    while counted < n:
        d = d + timedelta(days=1)
        if d.weekday() < 5:  # Mon..Fri
            counted += 1
    from datetime import datetime as _dt, timezone as _tz
    return _dt(d.year, d.month, d.day, 23, 59, 59, tzinfo=_tz.utc)


# ---------------------------------------------------------------------------
# Time-driven automatic transitions
# ---------------------------------------------------------------------------

def fire_clock_transitions():
    now = store.now()
    # 1) Shipments past due_at close
    for ship in store.STORES["pt_shipments"].values():
        if ship["status"] == "OPEN" and now > ship["_due_dt"]:
            ship["status"] = "CLOSED"
            ship["closure_reason"] = "DEADLINE_ELAPSED"
            touch(ship)
    # 2) CITED findings past response_due_at escalate
    affected_cycles = set()
    for f in store.STORES["inspection_findings"].values():
        if f["status"] == "CITED" and f.get("_response_due_dt") and now > f["_response_due_dt"]:
            f["status"] = "ESCALATED"
            touch(f)
            affected_cycles.add(f["inspection_cycle_id"])
    for cid in affected_cycles:
        recompute_burden(cid)
    # 3) QUALIFIED personnel whose latest assessment expired -> COMPETENCY_REVIEW
    for p in store.STORES["personnel_records"].values():
        if p["qualification_status"] != "QUALIFIED":
            continue
        latest = None
        for a in store.STORES["competency_assessments"].values():
            if a["personnel_id"] != p["id"]:
                continue
            if latest is None or a["_assessed_dt"] > latest["_assessed_dt"]:
                latest = a
        if latest is not None and now > latest["_valid_until_dt"]:
            p["qualification_status"] = "COMPETENCY_REVIEW"
            touch(p)
