"""Inspection readiness, findings, corrective actions and diversion control."""
import db
from constants import (
    COUNSELING_BREACH_PENALTY,
    CRITICAL_FINDING_PENALTY,
    LAPSED_PRIVILEGE_PENALTY,
    MAJOR_FINDING_PENALTY,
    MINOR_FINDING_PENALTY,
    NEEDS_ATTENTION_THRESHOLD,
    OPEN_DIVERSION_PENALTY,
    READINESS_BASE,
    READY_THRESHOLD,
    RESTRICTED_VARIANCE_MG,
    VARIANCE_PENALTY,
)
from errors import ApiError
from services import program as program_svc, stability
from services.num import r1


def inspection_of(inspection_id):
    row = db.compliance_inspections.get(inspection_id)
    if row is None:
        raise ApiError("ERR_INSPECTION_NOT_FOUND", "No ComplianceInspection with the supplied id")
    return row


def finding_of(finding_id):
    row = db.compliance_findings.get(finding_id)
    if row is None:
        raise ApiError("ERR_FINDING_NOT_FOUND", "No ComplianceFinding with the supplied id")
    return row


def action_of(action_id):
    row = db.corrective_actions.get(action_id)
    if row is None:
        raise ApiError("ERR_ACTION_NOT_FOUND", "No CorrectiveAction with the supplied id")
    return row


def case_of(case_id):
    row = db.diversion_cases.get(case_id)
    if row is None:
        raise ApiError("ERR_DIVERSION_CASE_NOT_FOUND", "No DiversionCase with the supplied id")
    return row


def patient_of(case):
    return db.patients.get(case.get("patient_id"))


# ---------------------------------------------------------------------------
# Inspection readiness (R7)
# ---------------------------------------------------------------------------
def readiness_terms(program, clock=None):
    if clock is None:
        clock = db.clock_dt()
    open_critical = 0
    open_major = 0
    open_minor = 0
    for row in db.compliance_findings.values():
        if row.get("program_id") != program["id"] or row.get("status") != "OPEN":
            continue
        if row.get("severity") == "CRITICAL":
            open_critical += 1
        elif row.get("severity") == "MAJOR":
            open_major += 1
        elif row.get("severity") == "MINOR":
            open_minor += 1
    open_cases = sum(
        1
        for row in db.diversion_cases.values()
        if row.get("program_id") == program["id"] and row.get("status") in ("OPEN", "UNDER_REVIEW")
    )
    variance_over = (program.get("latest_inventory_variance_mg") or 0.0) > RESTRICTED_VARIANCE_MG
    counseling_breach = any(
        row.get("program_id") == program["id"]
        and row.get("counseling_standing") == "COUNSELING_DEFICIENT"
        for row in db.patients.values()
    )
    today = clock.strftime("%Y-%m-%d")
    lapsed = False
    for row in db.take_home_privileges.values():
        if row.get("program_id") != program["id"]:
            continue
        if row.get("decision") not in ("APPROVED", "APPROVED_WITH_EXCEPTION"):
            continue
        expires = row.get("expires_on")
        if expires and expires <= today:
            lapsed = True
            break
    return {
        "open_critical": open_critical,
        "open_major": open_major,
        "open_minor": open_minor,
        "open_diversion_cases": open_cases,
        "variance_over": variance_over,
        "counseling_breach": counseling_breach,
        "lapsed_privilege": lapsed,
    }


def compute_readiness(program, clock=None):
    terms = readiness_terms(program, clock)
    score = READINESS_BASE
    score -= CRITICAL_FINDING_PENALTY * terms["open_critical"]
    score -= MAJOR_FINDING_PENALTY * terms["open_major"]
    score -= MINOR_FINDING_PENALTY * terms["open_minor"]
    score -= OPEN_DIVERSION_PENALTY * terms["open_diversion_cases"]
    if terms["variance_over"]:
        score -= VARIANCE_PENALTY
    if terms["counseling_breach"]:
        score -= COUNSELING_BREACH_PENALTY
    if terms["lapsed_privilege"]:
        score -= LAPSED_PRIVILEGE_PENALTY
    score = r1(score)
    if score >= READY_THRESHOLD:
        tier = "READY"
    elif score >= NEEDS_ATTENTION_THRESHOLD:
        tier = "NEEDS_ATTENTION"
    else:
        tier = "NOT_READY"
    return score, tier, terms


def refresh_inspection(inspection, bump=True):
    program = db.programs.get(inspection.get("program_id"))
    if program is None:
        return inspection
    score, tier, _ = compute_readiness(program)
    inspection["readiness_score"] = score
    inspection["readiness_tier"] = tier
    inspection["finding_count"] = sum(
        1 for row in db.compliance_findings.values() if row.get("inspection_id") == inspection["id"]
    )
    if bump:
        db.stamp(inspection)
    return inspection


# ---------------------------------------------------------------------------
# Inspection transitions
# ---------------------------------------------------------------------------
def begin_inspection(inspection, actor):
    if inspection.get("status") != "SCHEDULED":
        raise ApiError("ERR_INSPECTION_NOT_SCHEDULED", "ComplianceInspection is not SCHEDULED")
    inspection["status"] = "IN_PROGRESS"
    refresh_inspection(inspection, bump=False)
    db.stamp(inspection)
    return inspection


def complete_inspection(inspection, actor):
    if inspection.get("status") != "IN_PROGRESS":
        raise ApiError(
            "ERR_INSPECTION_NOT_IN_PROGRESS",
            "ComplianceInspection is not IN_PROGRESS",
        )
    for row in db.compliance_findings.values():
        if row.get("inspection_id") != inspection["id"]:
            continue
        if row.get("severity") == "CRITICAL" and row.get("status") == "OPEN":
            raise ApiError(
                "ERR_CRITICAL_FINDING_OPEN",
                "A CRITICAL finding belonging to this inspection is still OPEN",
            )
    inspection["status"] = "COMPLETED"
    inspection["finding_count"] = sum(
        1 for row in db.compliance_findings.values() if row.get("inspection_id") == inspection["id"]
    )
    db.stamp(inspection)
    return inspection


def cancel_inspection(inspection, actor):
    if inspection.get("status") != "SCHEDULED":
        raise ApiError("ERR_INSPECTION_NOT_SCHEDULED", "ComplianceInspection is not SCHEDULED")
    inspection["status"] = "CANCELLED"
    db.stamp(inspection)
    return inspection


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------
def create_finding(inspection, requirement_code, severity, actor):
    from services import entity

    row = entity.make_finding(inspection, requirement_code, severity)
    db.compliance_findings[row["id"]] = row
    inspection["finding_count"] = sum(
        1 for r in db.compliance_findings.values() if r.get("inspection_id") == inspection["id"]
    )
    db.stamp(inspection)
    return row


# ---------------------------------------------------------------------------
# Corrective actions
# ---------------------------------------------------------------------------
def create_action(program_id, finding_id, severity, plan_text, due_date, actor):
    from constants import PLAN_TEXT_MIN
    from services import entity

    if plan_text is None or len(plan_text) < PLAN_TEXT_MIN:
        raise ApiError(
            "ERR_JUSTIFICATION_TOO_SHORT",
            "plan_text must be at least %d characters" % PLAN_TEXT_MIN,
        )
    row = entity.make_action(program_id, finding_id, severity, plan_text, due_date)
    db.corrective_actions[row["id"]] = row
    program = db.programs.get(program_id)
    if program is not None and severity == "CRITICAL":
        program_svc.refresh_program(program, bump=True)
    elif program is not None:
        program_svc.refresh_program(program, bump=True)
    return row


def implement_action(action, actor):
    if action.get("status") != "OPEN":
        raise ApiError("ERR_ACTION_NOT_OPEN", "CorrectiveAction is not OPEN")
    action["status"] = "IMPLEMENTED"
    db.stamp(action)
    program_svc.refresh_program_by_id(action.get("program_id"), bump=True)
    return action


def verify_action(action, actor):
    if action.get("status") != "IMPLEMENTED":
        raise ApiError("ERR_ACTION_NOT_IMPLEMENTED", "CorrectiveAction is not IMPLEMENTED")
    action["status"] = "VERIFIED_CLOSED"
    db.stamp(action)
    program_svc.refresh_program_by_id(action.get("program_id"), bump=True)
    return action


def cancel_action(action, actor):
    if action.get("status") != "OPEN":
        raise ApiError("ERR_ACTION_NOT_OPEN", "CorrectiveAction is not OPEN")
    action["status"] = "CANCELED"
    db.stamp(action)
    program_svc.refresh_program_by_id(action.get("program_id"), bump=True)
    return action


# ---------------------------------------------------------------------------
# Diversion cases
# ---------------------------------------------------------------------------
def create_case(program_id, patient, related_dose_dispense_id, detection_source, severity, actor):
    from services import entity

    row = entity.make_diversion_case(
        program_id,
        patient["id"],
        related_dose_dispense_id,
        actor.user_id,
        detection_source,
        severity,
    )
    db.diversion_cases[row["id"]] = row
    program_svc.refresh_program_by_id(program_id, bump=True)
    return row


def begin_review(case, actor):
    if case.get("status") != "OPEN":
        raise ApiError("ERR_DIVERSION_CASE_NOT_OPEN", "DiversionCase is not OPEN")
    case["status"] = "UNDER_REVIEW"
    db.stamp(case)
    patient = patient_of(case)
    if patient is not None:
        patient["diversion_standing"] = "UNDER_INVESTIGATION"
        from services import patient as patient_svc

        patient_svc.refresh_risk(patient)
        stability.refresh_patient(patient, publish="A")
        db.stamp(patient)
    program_svc.refresh_program_by_id(case.get("program_id"), bump=True)
    return case


def confirm(case, outcome_summary, actor):
    if case.get("status") != "UNDER_REVIEW":
        raise ApiError(
            "ERR_DIVERSION_CASE_NOT_UNDER_REVIEW",
            "DiversionCase is not UNDER_REVIEW",
        )
    from constants import OUTCOME_SUMMARY_MIN

    if outcome_summary is None or len(outcome_summary) < OUTCOME_SUMMARY_MIN:
        raise ApiError(
            "ERR_JUSTIFICATION_TOO_SHORT",
            "outcome_summary must be at least %d characters" % OUTCOME_SUMMARY_MIN,
        )
    case["status"] = "CONFIRMED"
    case["confirmed_at"] = db.fmt_dt(db.clock_dt())
    case["outcome_summary"] = outcome_summary
    db.stamp(case)

    patient = patient_of(case)
    if patient is not None:
        patient["diversion_standing"] = "CONFIRMED_DIVERSION"
        from services import patient as patient_svc

        patient_svc.refresh_risk(patient)
        recut_with_surcharge(patient, 25.0)
        # First hop of the depth-three cascade: every granted privilege is revoked.
        from services import patient_flow

        patient_flow.revoke_patient_privileges(
            patient, reason_code=None, reset_phase=False, quarantine_lots=True
        )
        stability.refresh_patient(patient, publish="A")
        db.stamp(patient)
    program_svc.refresh_program_by_id(case.get("program_id"), bump=True)
    return case


def recut_with_surcharge(patient, surcharge):
    from services import patient as patient_svc

    score = patient_svc.compute_risk_score(patient)
    score = r1(score + surcharge)
    patient["risk_score_points"] = score
    patient["risk_tier"] = patient_svc.cut_tier(score)
    return score


def unsubstantiate(case, outcome_summary, actor):
    if case.get("status") != "UNDER_REVIEW":
        raise ApiError(
            "ERR_DIVERSION_CASE_NOT_UNDER_REVIEW",
            "DiversionCase is not UNDER_REVIEW",
        )
    case["status"] = "UNSUBSTANTIATED"
    case["outcome_summary"] = outcome_summary
    db.stamp(case)
    patient = patient_of(case)
    if patient is not None:
        patient["diversion_standing"] = "CLEAR"
        from services import patient as patient_svc

        patient_svc.refresh_risk(patient)
        stability.refresh_patient(patient, publish="A")
        db.stamp(patient)
    program_svc.refresh_program_by_id(case.get("program_id"), bump=True)
    return case


def close_case(case, actor):
    if case.get("status") not in ("UNSUBSTANTIATED", "CONFIRMED"):
        raise ApiError(
            "ERR_DIVERSION_CASE_NOT_CLOSABLE",
            "DiversionCase is neither CONFIRMED nor UNSUBSTANTIATED",
        )
    case["status"] = "CLOSED"
    db.stamp(case)
    program_svc.refresh_program_by_id(case.get("program_id"), bump=True)
    return case