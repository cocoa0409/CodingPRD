"""Derived state, posture, cascades, lazy expiry and serialisers."""
from decimal import Decimal

import calc
from calc import d, r2, num
from ladder import touch, rows
from store import db, iso_ms, clock_now, add_days, sort_rows

LIVE_PARTICIPATION_RESERVING = ("PARTIALLY_APPROVED", "ACTIVE", "SUSPENDED", "UNDER_REVIEW")
OCCUPYING_ATTENDANCE = ("PLANNED", "ATTENDED", "MINUTES_SUBMITTED", "MINUTES_REVIEWED", "FLAGGED")
LEDGER_CONTACT_STATUSES = ("LOGGED", "UNDER_REVIEW", "REMEDIATION_REQUIRED", "ESCALATED")
LEDGER_ATTENDANCE_STATUSES = ("MINUTES_REVIEWED", "FLAGGED")
LIVE_MARKER_STATUSES = ("MARKER_REQUESTED", "MARKER_GRANTED", "PERFECTED")


# ------------------------------------------------------------------- accessors
def unit_participations(unit_id):
    return [p for p in rows("participations") if p["business_unit_id"] == unit_id]


def participation_attendances(participation_id):
    return [a for a in rows("attendances") if a["participation_id"] == participation_id]


def unit_contacts(unit_id):
    return [c for c in rows("contacts") if c["business_unit_id"] == unit_id]


def unit_attendances(unit_id):
    out = []
    for a in rows("attendances"):
        part = db.participations.get(a["participation_id"])
        if part is not None and part["business_unit_id"] == unit_id:
            out.append(a)
    return out


def unit_audits(unit_id):
    return [x for x in rows("document_audits") if x["business_unit_id"] == unit_id]


def unit_applications(unit_id):
    return [x for x in rows("leniency_applications") if x["business_unit_id"] == unit_id]


def active_assessment(unit_id):
    for a in rows("risk_assessments"):
        if a["business_unit_id"] == unit_id and a["status"] == "ACTIVE":
            return a
    return None


def active_analysis(transaction_id):
    for a in rows("hsr_analyses"):
        if a["transaction_id"] == transaction_id and a["status"] == "ACTIVE":
            return a
    return None


# ------------------------------------------------------------ derived counters
def review_minutes_consumed(unit):
    total = 0
    for p in unit_participations(unit["id"]):
        if p["status"] in LIVE_PARTICIPATION_RESERVING:
            total += int(p.get("review_minutes_reserved") or 0)
    return total


def document_violation_count(unit):
    total = 0
    for a in unit_audits(unit["id"]):
        if a["status"] == "COMPLETED":
            total += int(a.get("violation_count") or 0)
    return total


def site_readiness_score(site):
    scores = [
        int(x["score"])
        for x in rows("drills")
        if x["site_id"] == site["id"] and x["status"] == "COMPLETED" and x.get("score") is not None
    ]
    if not scores:
        return Decimal("0.00")
    return r2(d(sum(scores)) / d(len(scores)))


# ---------------------------------------------------------------- the ledger
def recompute_ledger(unit):
    total = Decimal("0")
    for c in unit_contacts(unit["id"]):
        if c["status"] in LEDGER_CONTACT_STATUSES:
            total += d(c.get("exposure_points_charged") or 0)
    for a in unit_attendances(unit["id"]):
        if a["status"] in LEDGER_ATTENDANCE_STATUSES:
            total += d(a.get("exposure_points_assessed") or 0)
    total += d(unit.get("manual_exposure_adjustment_points") or 0)
    value = max(Decimal("0.00"), r2(total))
    unit["exposure_points"] = value
    return value


def derive_posture(unit):
    exposure = d(unit.get("exposure_points") or 0)
    has_live_marker = any(
        app["marker_status"] in LIVE_MARKER_STATUSES for app in unit_applications(unit["id"])
    )
    if exposure >= calc.FROZEN_EXPOSURE_THRESHOLD or has_live_marker:
        return "FROZEN"
    if exposure >= calc.RESTRICTED_EXPOSURE_THRESHOLD or unit.get("risk_band") in ("HIGH", "SEVERE"):
        return "RESTRICTED"
    return "OPEN"


def recompute_posture(unit):
    """Recompute posture; entering FROZEN fires the freeze cascade."""
    previous = unit.get("posture", "OPEN")
    nxt = derive_posture(unit)
    if nxt == previous:
        return previous
    unit["posture"] = nxt
    touch(unit)
    if nxt == "FROZEN":
        freeze_cascade(unit)
    return nxt


# ------------------------------------------------------------------- cascades
def freeze_cascade(unit):
    """HOP 1: suspend live participations; HOP 2: cancel their future bookings."""
    targets = [
        p for p in unit_participations(unit["id"])
        if p["status"] in ("PARTIALLY_APPROVED", "ACTIVE")
    ]
    for part in sort_rows(targets):
        part["status"] = "SUSPENDED"
        touch(part)
        cancel_planned_attendances(
            participation_attendances(part["id"]),
            "business unit posture entered FROZEN",
            future_only=True,
        )


def cancel_planned_attendances(candidates, reason, future_only=True):
    now = clock_now()
    selected = []
    for att in candidates:
        if att["status"] != "PLANNED":
            continue
        meeting = db.meetings.get(att["meeting_id"])
        if meeting is None:
            continue
        if future_only and not (meeting["scheduled_start"] > now):
            continue
        selected.append((meeting["scheduled_start"], att["created_at"], att["_seq"], att))
    selected.sort(key=lambda t: (t[0], t[1], t[2]))
    for _, _, _, att in selected:
        att["status"] = "CANCELLED"
        att["cancellation_reason"] = reason
        touch(att)


def employee_attendances(employee_id):
    out = []
    for att in rows("attendances"):
        part = db.participations.get(att["participation_id"])
        if part is not None and part["employee_id"] == employee_id:
            out.append(att)
    return out


def suspend_employee_clearance(employee, reason):
    """CASCADE HOP 3 + 4 — GRANTED -> SUSPENDED and cancel future bookings."""
    if employee.get("clearance_status") != "GRANTED":
        return
    employee["clearance_status"] = "SUSPENDED"
    touch(employee)
    cancel_planned_attendances(
        employee_attendances(employee["id"]), reason, future_only=True
    )


def unit_touch_and_recompute(unit):
    """Ledger + posture recomputation at the end of a mutating request."""
    recompute_ledger(unit)
    touch(unit)
    recompute_posture(unit)


# ----------------------------------------------------------------- lazy expiry
def sweep_training_assignments():
    now = clock_now()
    for assignment in rows("assignments"):
        if assignment["status"] != "COMPLETED":
            continue
        expires = assignment.get("expires_at")
        if expires is not None and now >= expires:
            assignment["status"] = "EXPIRED"
            touch(assignment)


def qualifying_assignments(employee):
    out = []
    for assignment in rows("assignments"):
        if assignment["employee_id"] != employee["id"]:
            continue
        curriculum = db.curricula.get(assignment["curriculum_id"])
        if curriculum is None or not curriculum.get("is_mandatory"):
            continue
        if employee["role_category"] not in curriculum["target_role_categories"]:
            continue
        out.append(assignment)
    return out


def training_state(employee):
    now = clock_now()
    qualifying = qualifying_assignments(employee)
    current = [
        a for a in qualifying
        if a["status"] == "COMPLETED" and a.get("expires_at") is not None and now < a["expires_at"]
    ]
    if current:
        return "CURRENT", max(a["expires_at"] for a in current)
    history = [a for a in qualifying if a["status"] in ("COMPLETED", "EXPIRED") and a.get("completed_at")]
    if history:
        return "EXPIRED", None
    return "NONE", None


def training_status(employee):
    return training_state(employee)[0]


# --------------------------------------------------------------- leniency maths
def leniency_priority_rank(application):
    if application["marker_status"] not in ("MARKER_GRANTED", "PERFECTED"):
        return None
    candidates = [
        a for a in rows("leniency_applications")
        if a["cartel_code"] == application["cartel_code"]
        and a["marker_status"] in ("MARKER_GRANTED", "PERFECTED")
    ]
    candidates.sort(key=lambda a: (a["marker_granted_at"], a["created_at"], a["_seq"]))
    for index, candidate in enumerate(candidates, start=1):
        if candidate["id"] == application["id"]:
            return index
    return None


def recompute_leniency(application, force_zero_reduction=False):
    application["priority_rank"] = leniency_priority_rank(application)
    rank = None if force_zero_reduction else application["priority_rank"]
    application["estimated_penalty_cents"] = calc.leniency_penalty_estimate(
        application["affected_years"], application.get("gravity_pct"), rank
    )


def sweep_leniency_markers():
    now = clock_now()
    for application in rows("leniency_applications"):
        if application["marker_status"] != "MARKER_GRANTED":
            continue
        if application["disclosure_status"] != "DRAFT":
            continue
        granted = application.get("marker_granted_at")
        if granted is None:
            continue
        if now >= add_days(granted, calc.MARKER_VALIDITY_DAYS):
            application["marker_status"] = "MARKER_EXPIRED"
            application["priority_rank"] = None
            application["estimated_penalty_cents"] = calc.leniency_penalty_estimate(
                application["affected_years"], application.get("gravity_pct"), None
            )
            touch(application)
            unit = db.business_units.get(application["business_unit_id"])
            if unit is not None:
                touch(unit)
                recompute_posture(unit)


def sweep():
    sweep_training_assignments()
    sweep_leniency_markers()


# ----------------------------------------------------------------- serialisers
def _common(row):
    return {
        "id": row["id"],
        "created_at": iso_ms(row["created_at"]),
        "updated_at": iso_ms(row["updated_at"]),
        "version": row["version"],
    }


def ser_business_unit(row):
    out = _common(row)
    out.update({
        "name": row["name"],
        "market_code": row["market_code"],
        "market_share_bps": row["market_share_bps"],
        "interaction_point_count": row["interaction_point_count"],
        "competitor_overlap_pct": float(row["competitor_overlap_pct"]),
        "exposure_budget_points": float(row["exposure_budget_points"]),
        "review_minutes_budget": row["review_minutes_budget"],
        "exposure_points": num(row["exposure_points"]),
        "manual_exposure_adjustment_points": num(row["manual_exposure_adjustment_points"]),
        "review_minutes_consumed": review_minutes_consumed(row),
        "risk_band": row["risk_band"],
        "posture": row["posture"],
        "document_violation_count": document_violation_count(row),
    })
    return out


def ser_employee(row):
    status, expires = training_state(row)
    out = _common(row)
    out.update({
        "business_unit_id": row["business_unit_id"],
        "full_name": row["full_name"],
        "email": row["email"],
        "role_category": row["role_category"],
        "clearance_status": row["clearance_status"],
        "training_status": status,
        "training_expires_at": iso_ms(expires),
    })
    return out


def ser_curriculum(row):
    out = _common(row)
    out.update({
        "code": row["code"],
        "title": row["title"],
        "target_role_categories": list(row["target_role_categories"]),
        "duration_minutes": row["duration_minutes"],
        "validity_days": row["validity_days"],
        "is_mandatory": row["is_mandatory"],
    })
    return out


def ser_assignment(row):
    out = _common(row)
    out.update({
        "employee_id": row["employee_id"],
        "curriculum_id": row["curriculum_id"],
        "due_at": iso_ms(row["due_at"]),
        "status": row["status"],
        "started_at": iso_ms(row.get("started_at")),
        "completed_at": iso_ms(row.get("completed_at")),
        "expires_at": iso_ms(row.get("expires_at")),
        "score": row.get("score"),
        "waiver_reason": row.get("waiver_reason"),
    })
    return out


def ser_association(row):
    out = _common(row)
    out.update({
        "name": row["name"],
        "approval_tier": row["approval_tier"],
        "competitor_density_pct": float(row["competitor_density_pct"]),
        "status": row["status"],
    })
    return out


def ser_participation(row):
    out = _common(row)
    out.update({
        "business_unit_id": row["business_unit_id"],
        "association_id": row["association_id"],
        "employee_id": row["employee_id"],
        "purpose": row["purpose"],
        "status": row["status"],
        "legal_cleared": row["legal_cleared"],
        "business_justified": row["business_justified"],
        "legal_cleared_by_user_id": row.get("legal_cleared_by_user_id"),
        "business_justification": row.get("business_justification"),
        "review_load_minutes": row["review_load_minutes"],
        "review_minutes_reserved": row["review_minutes_reserved"],
    })
    return out


def ser_meeting(row):
    out = _common(row)
    out.update({
        "association_id": row["association_id"],
        "meeting_type": row["meeting_type"],
        "scheduled_start": iso_ms(row["scheduled_start"]),
        "scheduled_end": iso_ms(row["scheduled_end"]),
        "agenda_received": row["agenda_received"],
    })
    return out


def ser_attendance(row):
    out = _common(row)
    out.update({
        "meeting_id": row["meeting_id"],
        "participation_id": row["participation_id"],
        "status": row["status"],
        "occupied_start": iso_ms(row["occupied_start"]),
        "occupied_end": iso_ms(row["occupied_end"]),
        "minutes_summary": row.get("minutes_summary"),
        "topics_discussed": row.get("topics_discussed"),
        "minutes_verdict": row.get("minutes_verdict"),
        "minutes_findings": row.get("minutes_findings"),
        "minutes_reviewed_by_user_id": row.get("minutes_reviewed_by_user_id"),
        "exposure_points_assessed": num(row.get("exposure_points_assessed") or 0),
        "cancellation_reason": row.get("cancellation_reason"),
    })
    return out


def ser_contact(row):
    out = _common(row)
    out.update({
        "business_unit_id": row["business_unit_id"],
        "employee_id": row["employee_id"],
        "competitor_name": row["competitor_name"],
        "contact_channel": row["contact_channel"],
        "topic_tags": list(row["topic_tags"]),
        "pricing_topic": row["pricing_topic"],
        "occurred_at": iso_ms(row["occurred_at"]),
        "status": row["status"],
        "exposure_points_charged": num(row.get("exposure_points_charged") or 0),
        "band_multiplier_applied": float(row["band_multiplier_applied"]),
        "review_opened_by_user_id": row.get("review_opened_by_user_id"),
        "remediation_instructions": row.get("remediation_instructions"),
        "remediation_response": row.get("remediation_response"),
    })
    return out


def ser_transaction(row):
    out = _common(row)
    out.update({
        "business_unit_id": row["business_unit_id"],
        "target_name": row["target_name"],
        "deal_value_cents": row["deal_value_cents"],
        "assumed_liabilities_cents": row["assumed_liabilities_cents"],
        "market_valuation_cents": row["market_valuation_cents"],
        "acquirer_total_assets_cents": row["acquirer_total_assets_cents"],
        "target_total_assets_cents": row["target_total_assets_cents"],
        "exemption_code": row["exemption_code"],
        "signed_at": iso_ms(row["signed_at"]),
        "status": row["status"],
        "filed_at": iso_ms(row.get("filed_at")),
        "waiting_period_end": iso_ms(row.get("waiting_period_end")),
    })
    return out


def ser_hsr(row):
    out = _common(row)
    out.update({
        "transaction_id": row["transaction_id"],
        "valuation_variant": row["valuation_variant"],
        "size_of_transaction_cents": row["size_of_transaction_cents"],
        "filing_required": row["filing_required"],
        "determination": row["determination"],
        "status": row["status"],
        "analyzed_by_user_id": row.get("analyzed_by_user_id"),
    })
    return out


def ser_site(row):
    out = _common(row)
    out.update({
        "name": row["name"],
        "country_code": row["country_code"],
        "concurrent_drill_capacity": row["concurrent_drill_capacity"],
        "readiness_score": num(site_readiness_score(row)),
    })
    return out


def ser_drill(row):
    out = _common(row)
    out.update({
        "site_id": row["site_id"],
        "drill_type": row["drill_type"],
        "window_start": iso_ms(row["window_start"]),
        "window_end": iso_ms(row["window_end"]),
        "status": row["status"],
        "score": row.get("score"),
        "gaps_found": row.get("gaps_found"),
        "abort_reason": row.get("abort_reason"),
    })
    return out


def ser_audit(row):
    score = row.get("guideline_score")
    out = _common(row)
    out.update({
        "business_unit_id": row["business_unit_id"],
        "sample_size": row["sample_size"],
        "scope_note": row["scope_note"],
        "status": row["status"],
        "violation_count": row.get("violation_count"),
        "high_risk_phrase_count": row.get("high_risk_phrase_count"),
        "guideline_score": num(score) if score is not None else None,
    })
    return out


def ser_leniency(row):
    gravity = row.get("gravity_pct")
    out = _common(row)
    out.update({
        "business_unit_id": row["business_unit_id"],
        "source_contact_id": row.get("source_contact_id"),
        "cartel_code": row["cartel_code"],
        "affected_years": [dict(y) for y in row["affected_years"]],
        "gravity_pct": float(gravity) if gravity is not None else None,
        "marker_status": row["marker_status"],
        "disclosure_status": row["disclosure_status"],
        "marker_requested_at": iso_ms(row.get("marker_requested_at")),
        "marker_granted_at": iso_ms(row.get("marker_granted_at")),
        "priority_rank": row.get("priority_rank"),
        "estimated_penalty_cents": row.get("estimated_penalty_cents"),
        "withdrawal_reason": row.get("withdrawal_reason"),
    })
    return out


def ser_assessment(row):
    out = _common(row)
    out.update({
        "business_unit_id": row["business_unit_id"],
        "variant": row["variant"],
        "share_component": num(row["share_component"]),
        "interaction_component": num(row["interaction_component"]),
        "overlap_component": num(row["overlap_component"]),
        "incident_load": num(row["incident_load"]),
        "escalated_contact_count": row["escalated_contact_count"],
        "flagged_attendance_count": row["flagged_attendance_count"],
        "document_violation_count": row["document_violation_count"],
        "market_risk_index": num(row["market_risk_index"]),
        "risk_band": row["risk_band"],
        "status": row["status"],
    })
    return out
