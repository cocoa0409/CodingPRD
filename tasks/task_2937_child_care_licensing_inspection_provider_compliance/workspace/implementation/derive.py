"""Derived fields, recomputations and the cross-entity cascades of PRD §2.10."""

import calc
import clock
import constants as K
import store


# --- StaffMember derived clearance fields (PRD §3.3) -----------------------


def covered_check_types(staff_member_id):
    now = clock.now_dt()
    covered = set()
    for check in store.checks_of(staff_member_id):
        if check["status"] not in ("CLEARED", "WAIVED"):
            continue
        expires = check.get("expires_at")
        if expires is not None and clock.at(expires) <= now:
            continue
        covered.add(check["check_type"])
    return covered


def staff_clearance(staff):
    """Returns (clearance_status, supervision_eligible, barred_offense_tier)."""
    checks = store.checks_of(staff["id"])
    disqualified = [c for c in checks if c["status"] == "DISQUALIFIED"]
    pending_waiver = [c for c in checks if c["status"] == "WAIVER_PENDING"]

    tier = "NONE"
    for check in disqualified:
        candidate = check.get("disqualifying_offense_tier") or "NONE"
        if K.TIER_RANK[candidate] > K.TIER_RANK[tier]:
            tier = candidate

    if disqualified:
        status = "BARRED"
    elif pending_waiver:
        status = "WAIVER_PENDING"
    elif set(K.REQUIRED_CHECK_TYPES).issubset(covered_check_types(staff["id"])):
        status = "CLEARED"
    else:
        status = "PENDING"

    eligible = status == "CLEARED" and staff["member_type"] in (
        "DIRECTOR",
        "LEAD_TEACHER",
        "ASSISTANT",
    )
    return status, eligible, tier


def clearance_status_of(staff):
    return staff_clearance(staff)[0]


def supervision_eligible(staff):
    return staff_clearance(staff)[1]


# --- Provider clearance completeness (PRD §3.3) ---------------------------


def provider_clearance_complete(provider):
    people = store.staff_of(provider["id"])
    if not any(s["member_type"] == "DIRECTOR" for s in people):
        return False
    for staff in people:
        if clearance_status_of(staff) != "CLEARED":
            return False
        if not set(K.REQUIRED_CHECK_TYPES).issubset(covered_check_types(staff["id"])):
            return False
    return True


# --- AgeGroupRoster derived flags (PRD §3.2) ------------------------------


def lead_is_eligible(age_group, lead):
    if lead is None:
        return False
    status, eligible, _tier = staff_clearance(lead)
    if status != "CLEARED" or not eligible:
        return False
    if lead["member_type"] not in ("DIRECTOR", "LEAD_TEACHER"):
        return False
    return age_group in lead["qualified_age_groups"]


def recompute_roster_flags(roster):
    age_group = roster["age_group"]
    roster["required_staff_count"] = calc.required_staff_count(
        age_group, roster["enrolled_count"]
    )
    roster["ratio_compliant"] = (
        roster["staff_assigned_count"] >= roster["required_staff_count"]
    )
    roster["group_size_compliant"] = roster["enrolled_count"] <= calc.effective_group_cap(
        age_group, roster["approved_group_size"]
    )
    if roster["enrolled_count"] == 0:
        roster["supervision_compliant"] = True
    else:
        lead = store.staff_members.get(roster.get("lead_staff_member_id"))
        roster["supervision_compliant"] = lead_is_eligible(age_group, lead)
    return roster


def approved_size_sum(provider_id):
    return sum(r["approved_group_size"] for r in store.rosters_of(provider_id))


def roster_capacity_limit(provider):
    if provider["licensed_capacity"] > 0:
        return provider["licensed_capacity"]
    return provider["requested_capacity"]


# --- Provider counters (PRD §2.9, §3.5) -----------------------------------


def recompute_provider_points(provider):
    now = clock.now_dt()
    cutoff = clock.sub_months(now, K.RISK_LOOKBACK_MONTHS)
    open_points = 0
    resolved_points = 0
    lifetime_points = 0
    critical_open = 0
    critical_24mo = 0
    for inspection in store.provider_inspections(provider["id"]):
        if inspection["status"] != "FINALIZED":
            continue
        finalized_at = clock.at(inspection["finalized_at"])
        for violation in store.inspection_violations(inspection["id"]):
            points = violation["assessed_points"]
            status = violation["status"]
            if status in K.OPEN_VIOLATION_STATUSES:
                open_points += points
                if violation["severity"] == "CRITICAL":
                    critical_open += 1
            elif status == "VERIFIED_CORRECTED":
                resolved_points += points
            if status != "VACATED":
                lifetime_points += points
                if (
                    violation["severity"] == "CRITICAL"
                    and finalized_at is not None
                    and finalized_at > cutoff
                ):
                    critical_24mo += 1
    provider["open_violation_points"] = open_points
    provider["resolved_violation_points"] = resolved_points
    provider["lifetime_violation_points"] = lifetime_points
    provider["critical_open_count"] = critical_open
    provider["critical_violation_count_24mo"] = critical_24mo
    return provider


def recompute_provider_complaint_counts(provider):
    now = clock.now_dt()
    cutoff = clock.sub_months(now, K.RISK_LOOKBACK_MONTHS)
    substantiated = 0
    inconclusive = 0
    for complaint in store.by_provider(store.complaints, provider["id"]):
        determined_at = complaint.get("determined_at")
        if not determined_at or complaint["status"] == "SCREENED_OUT":
            continue
        if clock.at(determined_at) <= cutoff:
            continue
        if complaint.get("determination") == "SUBSTANTIATED":
            substantiated += 1
        elif complaint.get("determination") == "INCONCLUSIVE":
            inconclusive += 1
    provider["substantiated_complaint_count_24mo"] = substantiated
    provider["inconclusive_complaint_count_24mo"] = inconclusive
    return provider


def recompute_provider_risk(provider):
    score = calc.risk_score(provider, "ENFORCEMENT_REVIEW")
    provider["risk_score"] = score
    provider["risk_tier"] = calc.risk_tier(score)
    return provider


def recompute_provider(provider):
    recompute_provider_points(provider)
    recompute_provider_complaint_counts(provider)
    recompute_provider_risk(provider)
    return provider


# --- Inspection derived fields (PRD §3.5) --------------------------------


def recompute_violation_count(inspection):
    rows = store.inspection_violations(inspection["id"])
    inspection["violation_count"] = len([v for v in rows if v["status"] != "VACATED"])
    return inspection


def recompute_final_score(inspection):
    rows = store.inspection_violations(inspection["id"])
    score, raw, _count = calc.compliance_score(rows, "FINAL")
    inspection["final_compliance_score"] = score
    inspection["raw_deduction_points"] = raw
    return inspection


def recompute_preliminary_score(inspection):
    rows = store.inspection_violations(inspection["id"])
    score, _raw, _count = calc.compliance_score(rows, "PRELIMINARY")
    inspection["preliminary_compliance_score"] = score
    return inspection


def recompute_inspector_visit_count(inspector):
    count = 0
    for inspection in store.ordered(store.inspections):
        if inspection["inspector_id"] != inspector["id"]:
            continue
        if inspection["status"] in ("SCHEDULED", "IN_PROGRESS", "PENDING_REVIEW"):
            count += 1
    if inspector["scheduled_visit_count"] != count:
        inspector["scheduled_visit_count"] = count
        store.touch(inspector)
    return inspector


# --- Violation creation (shared by citation and both cascades) -------------


def create_violation(
    inspection,
    checklist_item,
    primary_age_group,
    narrative,
    severity,
    parent_violation=None,
    auto_generated=False,
    status="CITED",
    with_due_date=False,
):
    depth = 0 if parent_violation is None else min(
        2, parent_violation["repeat_chain_depth"] + 1
    )
    observed = inspection.get("age_groups_observed") or []
    infant_exposure = primary_age_group == "INFANT" or (
        bool(checklist_item.get("infant_sensitive")) and "INFANT" in observed
    )
    points = calc.assessed_points(severity, infant_exposure, depth)
    record = {
        "inspection_id": inspection["id"],
        "checklist_item_id": checklist_item["id"],
        "repeat_of_violation_id": parent_violation["id"] if parent_violation else None,
        "primary_age_group": primary_age_group,
        "severity_override": None,
        "severity": severity,
        "repeat_chain_depth": depth,
        "infant_exposure": infant_exposure,
        "assessed_points": points,
        "status": status,
        "correction_due_date": None,
        "narrative": narrative,
        "corrected_at": None,
        "vacated_reason": None,
        "auto_generated": auto_generated,
    }
    store.create(store.violations, record)
    if with_due_date:
        record["correction_due_date"] = correction_due_date(record)
    return record


def correction_due_date(violation):
    cited_at = clock.at(violation["created_at"])
    return clock.fmt(clock.add_days(cited_at, K.CORRECTION_DAYS[violation["severity"]]))


# --- Voiding an inspection (PRD §3.4) -------------------------------------


def void_inspection(inspection, reason):
    inspection["status"] = "VOIDED"
    for violation in store.inspection_violations(inspection["id"]):
        if violation["status"] in ("CITED", "CORRECTION_PENDING"):
            violation["status"] = "VACATED"
            violation["vacated_reason"] = reason
            store.touch(violation)
    store.touch(inspection)
    inspector = store.inspectors.get(inspection["inspector_id"])
    if inspector is not None:
        recompute_inspector_visit_count(inspector)
    return inspection


# --- Clearance cascade (PRD §3.3, four links) -----------------------------


def check_context(check):
    staff = store.staff_members[check["staff_member_id"]]
    provider = store.providers[staff["provider_id"]]
    return staff, provider


def clearance_snapshot(staff, provider):
    return staff_clearance(staff), provider_clearance_complete(provider)


def propagate_check_change(check, before, always_touch_provider=False):
    staff, provider = check_context(check)
    before_staff, before_complete = before

    after_staff = staff_clearance(staff)
    if after_staff != before_staff:
        store.touch(staff)

    if before_staff[1] and not after_staff[1]:
        for roster in store.rosters_of(provider["id"]):
            if roster.get("lead_staff_member_id") == staff["id"]:
                roster["lead_staff_member_id"] = None
                roster["staff_assigned_count"] = max(0, roster["staff_assigned_count"] - 1)
                recompute_roster_flags(roster)
                store.touch(roster)

    after_complete = provider_clearance_complete(provider)
    provider_changed = False
    if (
        before_complete
        and not after_complete
        and provider["application_status"] == "CHECKS_CLEARED"
    ):
        provider["application_status"] = "SUBMITTED"
        provider_changed = True
        for inspection in store.provider_inspections(provider["id"]):
            if inspection["inspection_type"] == "INITIAL" and inspection["status"] in (
                "SCHEDULED",
                "IN_PROGRESS",
            ):
                void_inspection(inspection, "Provider clearance reverted.")
        recompute_provider(provider)

    if always_touch_provider or provider_changed:
        store.touch(provider)
    return provider


# --- Substantiated-complaint link four (PRD §3.7) -------------------------


def auto_propose_enforcement(provider, inspection):
    points = provider["open_violation_points"]
    if points < K.PROBATION_THRESHOLD or provider["current_ladder_step"] >= 2:
        return None
    action_type = calc.recommended_action_type(points)
    if action_type is None:
        return None
    record = {
        "provider_id": provider["id"],
        "source_inspection_id": inspection["id"] if inspection else None,
        "requested_action_type": action_type,
        "action_type": action_type,
        "ladder_step": K.LADDER_STEP[action_type],
        "status": "PROPOSED",
        "basis_points": points,
        "fine_amount_cents": calc.fine_amount_cents(action_type, points),
        "proposed_at": clock.now(),
        "issued_at": None,
        "effective_at": None,
        "appeal_deadline_at": None,
        "appealed_at": None,
        "appeal_note": None,
        "resolved_at": None,
        "appeal_decision": None,
        "issued_by_user_id": None,
        "capacity_held_slots": 0,
        "rationale": None,
    }
    return store.create(store.actions, record)


def latest_finalized(candidates):
    """Highest finalized_at, ties broken by the earliest created_at."""
    best = None
    for row in candidates:
        if best is None or row["finalized_at"] > best["finalized_at"]:
            best = row
    return best


# --- Segregation of duties (PRD §2.8) -------------------------------------


def inspector_finalized_recently(inspector_id, provider_id):
    cutoff = clock.sub_months(clock.now_dt(), K.SEGREGATION_LOOKBACK_MONTHS)
    for inspection in store.provider_inspections(provider_id):
        if inspection["inspector_id"] != inspector_id:
            continue
        if inspection["status"] != "FINALIZED" or not inspection.get("finalized_at"):
            continue
        if clock.at(inspection["finalized_at"]) > cutoff:
            return True
    return False


def cap_reviewer_conflict(user_id, source_inspection_id):
    if source_inspection_id is None:
        return False
    for plan in store.caps_of_inspection(source_inspection_id):
        if plan.get("reviewed_by_user_id") != user_id:
            continue
        if plan["status"] in ("APPROVED", "COMPLETED", "FAILED"):
            return True
    return False


TRACKED_PROVIDER_FIELDS = (
    "open_violation_points",
    "resolved_violation_points",
    "lifetime_violation_points",
    "critical_open_count",
    "critical_violation_count_24mo",
    "substantiated_complaint_count_24mo",
    "inconclusive_complaint_count_24mo",
    "risk_score",
    "risk_tier",
)


def recompute_provider_tracked(provider):
    """Recompute the provider's counters, bumping the row only when a value moved."""
    before = dict((k, provider[k]) for k in TRACKED_PROVIDER_FIELDS)
    recompute_provider(provider)
    if any(provider[k] != before[k] for k in TRACKED_PROVIDER_FIELDS):
        store.touch(provider)
        return True
    return False
