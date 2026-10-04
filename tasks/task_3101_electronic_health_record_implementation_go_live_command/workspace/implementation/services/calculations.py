"""Calculation rules (SCAFFOLD §1.3) implemented verbatim."""

from decimal import Decimal, ROUND_HALF_UP

from db import (
    BUILD_REJECTED_OPTIMISTIC_CAP,
    CLASS_WEIGHT,
    INTERCHANNEL_PENALTY,
    INTERCHANNEL_REJECT_THRESHOLD,
    MIN_OBSERVATION_HOURS,
    MIN_PASS_RATE,
    OPEN_POSTURE_MIN,
    PAYLOAD_MAX_PCT,
    RESTRICTED_POSTURE_MIN,
    SCENARIO_MIN_CYCLES,
    SEV1_PENALTY,
    SEV2_PENALTY,
    SEV3_PENALTY,
    SEV4_PENALTY,
    PROFICIENCY_GATE_PCT,
    CERT_MIN_HOURS,
    EPOCH_CAPACITY_POINTS,
    STABILIZATION_TARGET,
)
from errors import q0, q2

D = Decimal

SEVERITY_PENALTY = {
    "SEV1": D(SEV1_PENALTY),
    "SEV2": D(SEV2_PENALTY),
    "SEV3": D(SEV3_PENALTY),
    "SEV4": D(SEV4_PENALTY),
}

OPEN_DEFECT_STATES = {"OPEN", "IN_REMEDIATION", "REOPENED"}


def severity_penalty(severity):
    return SEVERITY_PENALTY.get(severity, D(0))


# --------------------------------------------------------------------------
# readiness_posture_score
# --------------------------------------------------------------------------
def readiness_scores(program, optimistic=False):
    """Returns (readiness_score, readiness_posture, optimistic_readiness_score).

    Stage A: defects in {RESOLVED, DEFERRED} are excluded.
    Stage B: group open defects by owning build item's department_id, take MAX
             severity in the department.
    Stage C: interchannel penalty when any channel has >= 25 rejections.
    Stage D: when interchannel_penalty > 0 the per-department penalties are
             dropped entirely (replacement, not addition).
    """
    from services import lookups as L

    open_defects = [
        d
        for d in L.program_defects(program["id"])
        if d["status"] in OPEN_DEFECT_STATES
    ]

    dept_max = {}
    for defect in open_defects:
        scenario = L.DB.test_scenarios.get(defect["test_scenario_id"])
        penalty = severity_penalty(defect["severity"])
        if scenario is not None:
            item = L.DB.system_build_items.get(scenario["system_build_item_id"])
            if item is not None and item["status"] == "BUILD_REJECTED":
                penalty = min(penalty, D(BUILD_REJECTED_OPTIMISTIC_CAP))
            dept_id = item["department_id"] if item else None
            if optimistic:
                dept_max[dept_id] = max(dept_max.get(dept_id, D(0)), penalty)

    if not optimistic:
        for defect in open_defects:
            scenario = L.DB.test_scenarios.get(defect["test_scenario_id"])
            if scenario is None:
                continue
            item = L.DB.system_build_items.get(scenario["system_build_item_id"])
            dept_id = item["department_id"] if item else None
            penalty = severity_penalty(defect["severity"])
            dept_max[dept_id] = max(dept_max.get(dept_id, D(0)), penalty)

    interchannel = D(0)
    rejections = sum(
        int(c.get("rejected_message_count") or 0) for c in L.program_channels(program["id"])
    )
    if rejections >= INTERCHANNEL_REJECT_THRESHOLD:
        interchannel = D(INTERCHANNEL_PENALTY)

    if interchannel > 0:
        score = D(100) - interchannel
    else:
        score = D(100) - sum(dept_max.values(), D(0))

    score = max(D("0.00"), min(D("100.00"), score))
    score = q2(score)

    if score >= D(str(OPEN_POSTURE_MIN)):
        posture = "OPEN"
    elif score >= D(str(RESTRICTED_POSTURE_MIN)):
        posture = "RESTRICTED"
    else:
        posture = "ROLLBACK_REQUIRED"
    return score, posture


def posture_only(program):
    score, posture = readiness_scores(program, optimistic=False)
    return score, posture


# --------------------------------------------------------------------------
# build_customization_risk
# --------------------------------------------------------------------------
def build_customization_risk(build_classification, customization_depth, local_custom_fields):
    unit_count = len(set(local_custom_fields or []))
    billable = min(unit_count, 12)
    tier_points = (
        2 * min(billable, 4)
        + 3 * max(0, min(billable, 8) - 4)
        + 5 * max(0, billable - 8)
    )
    risk_raw = D(tier_points) * D(str(CLASS_WEIGHT[build_classification]))
    depth = int(customization_depth or 0)
    if depth <= 1:
        depth_multiplier = D(1)
    else:
        depth_multiplier = D(1) + D(depth - 1) * D("0.15")
    risk_raw = risk_raw * depth_multiplier
    return q2(risk_raw)


# --------------------------------------------------------------------------
# charge_capture_reconciliation
# --------------------------------------------------------------------------
def charge_capture(legacy_charge_cents, order_type, final):
    base = D(str(legacy_charge_cents))
    lines = [base]
    if order_type == "LAB":
        lines.append(base * D("0.050"))
    elif order_type == "IMAGING":
        lines.append(base * D("0.125"))
        lines.append(base * D("0.075"))
    elif order_type == "MEDICATION":
        lines.append(base * D("0.030"))
    elif order_type == "PROCEDURE":
        lines.append(base * D("0.200"))
        lines.append(base * D("0.050"))

    rounded_lines = [q2(line) for line in lines]
    subtotal = sum(rounded_lines, D(0))
    provisional = q2(subtotal)

    charge_gap = D("0.00")
    if order_type == "PROCEDURE" and final:
        unrounded_total = sum(lines, D(0))
        charge_gap = q2(unrounded_total * D("0.030"))

    final_charge = q2(provisional + charge_gap)
    return provisional, final_charge, q2(final_charge - provisional)


# --------------------------------------------------------------------------
# conversion_reconciliation_variance
# --------------------------------------------------------------------------
def conversion_variance(source_count, reconciled_count, payload_class):
    source = int(source_count or 0)
    reconciled = int(reconciled_count or 0)
    variance_count = abs(source - reconciled)
    if source == 0:
        penalty = D("100.00")
    elif variance_count == 0:
        penalty = D("0.00")
    else:
        penalty = q2(D(100) * D(variance_count) / D(source))
    cap = D(str(PAYLOAD_MAX_PCT[payload_class]))
    return variance_count, penalty, penalty > cap


# --------------------------------------------------------------------------
# command_center_sla_minutes
# --------------------------------------------------------------------------
SEV_WEIGHT = {"SEV1": "0.25", "SEV2": "0.50", "SEV3": "1.00", "SEV4": "2.00"}
ZONE_MODIFIER = {
    "ED": "0.80",
    "OR": "0.70",
    "ICU": "0.75",
    "MED_SURG": "1.00",
    "RADIOLOGY": "1.10",
    "PHARMACY": "1.05",
}


def command_center_sla(severity, zone, coverage_count, base_minutes=60):
    sev = D(SEV_WEIGHT[severity])
    zone_mod = D(ZONE_MODIFIER[zone])
    coverage = D("0.50") if coverage_count == 0 else D("1.00")
    return q0(D(base_minutes) * sev * zone_mod * coverage)


# --------------------------------------------------------------------------
# proficiency_gate_ratio
# --------------------------------------------------------------------------
def proficiency_ratio(required_staff_count, cleared_count):
    required = int(required_staff_count or 0)
    if required == 0:
        ratio = D("100.00")
    else:
        ratio = q2(D(100) * D(cleared_count) / D(required))
    return ratio, ratio >= D(str(PROFICIENCY_GATE_PCT))


def cleared_staff(staff_rows):
    return [s for s in staff_rows if s["status"] in ("PROFICIENCY_VERIFIED", "CREDENTIALED")]


# --------------------------------------------------------------------------
# staff_certification_readiness
# --------------------------------------------------------------------------
def accumulated_training_hours(assignments):
    return q2(
        sum(
            (D(str(a.get("completed_hours") or 0)) for a in assignments if a["status"] in ("IN_PROGRESS", "COMPLETED")),
            D(0),
        )
    )


def certification_ready(assignments, hours):
    non_waived = [a for a in assignments if a["status"] != "WAIVED"]
    all_complete = all(a["status"] == "COMPLETED" for a in non_waived)
    return hours >= D(CERT_MIN_HOURS) and all_complete


# --------------------------------------------------------------------------
# test_validation_sweep
# --------------------------------------------------------------------------
def test_cycles_passed(scenarios, current_epoch):
    passing = 0
    for scenario in scenarios:
        if scenario.get("executed_epoch") != current_epoch:
            continue
        if scenario["status"] == "PASSED":
            passing += 1
    return passing


def cycle_requirement_met(scenario_class, passing):
    return passing >= SCENARIO_MIN_CYCLES[scenario_class]


# --------------------------------------------------------------------------
# interface_message_validation_pass_rate
# --------------------------------------------------------------------------
def interface_pass_rate(validated, rejected):
    decided = int(validated or 0) + int(rejected or 0)
    if decided == 0:
        return D("0.00"), False
    rate = q2(D(100) * D(int(validated or 0)) / D(decided))
    return rate, rate >= D(str(MIN_PASS_RATE))


# --------------------------------------------------------------------------
# revenue_cycle_stabilization_index
# --------------------------------------------------------------------------
def ar_days_factor(clock, encounter_utc):
    if encounter_utc is None:
        return D(100)
    delta = clock - encounter_utc
    days = delta.total_seconds() / 86400.0
    if days <= 7:
        return D(100)
    if days <= 14:
        return D(80)
    if days <= 30:
        return D(50)
    return D(20)


def revenue_cycle_index(clock, orders):
    considered = [o for o in orders if o["clinical_state"] in ("CONVERTED", "RECONCILED")]
    if not considered:
        return D("0.00")
    ar_factor = min(ar_days_factor(clock, o["encounter_utc"]) for o in considered)
    denial_factor = D(0) if any(o["billing_state"] == "CLAIM_DENIED" for o in considered) else D(100)
    index = D("0.60") * ar_factor + D("0.40") * denial_factor
    return q2(index)


# --------------------------------------------------------------------------
# optimization_release_allocation
# --------------------------------------------------------------------------
def allocation_queue(items):
    pending = [i for i in items if i["status"] == "TRIAGED"]
    return sorted(
        pending,
        key=lambda i: (
            i["effort_points"],
            i["requested_epoch"],
            i["created_at"],
        ),
    )


def allocate_scheduled_epoch(item, target_epoch, all_items):
    consumed = sum(
        int(i["effort_points"])
        for i in all_items
        if i["status"] in ("SCHEDULED", "IN_PROGRESS", "RELEASED")
        and i.get("scheduled_epoch") == target_epoch
        and i["id"] != item["id"]
    )
    remaining = EPOCH_CAPACITY_POINTS - consumed
    if int(item["effort_points"]) <= remaining:
        return target_epoch
    return target_epoch + 1