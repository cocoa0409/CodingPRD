"""Complaint intake, allegations, classification, withdrawal, purge."""
from decimal import Decimal

from flask import Blueprint, g

import calc
import svc
from core import (
    ApiError,
    add_days,
    body,
    db,
    dump,
    endpoint,
    f_bool,
    f_dt,
    f_enum,
    f_enum_list,
    f_str,
    new_row,
    paginate,
    q_enum,
    q_str,
    respond_object,
    sort_created,
    touch,
)

bp = Blueprint("complaints", __name__)

SCREENING_OUTCOMES = ("ACCEPT", "REJECT")


# ---------------------------------------------------------------------------
# Intake
# ---------------------------------------------------------------------------
@bp.post("/complaints")
@endpoint("Complainant", "Supervisor", "IACommander")
def create_complaint():
    payload = body()
    # tier 4 -- schema
    intake_channel = f_enum(payload, "intake_channel", calc.INTAKE_CHANNELS)
    narrative = f_str(payload, "narrative")
    incident_datetime = f_dt(payload, "incident_datetime")
    alleged_injury = f_bool(payload, "alleged_injury", required=False, default=False)
    reported_allegation_types = f_enum_list(
        payload, "reported_allegation_types", calc.ALLEGATION_TYPES
    )
    subject_unit_id = f_str(payload, "subject_unit_id")
    complainant_name = f_str(payload, "complainant_name", required=False)
    complainant_contact = f_str(payload, "complainant_contact", required=False)
    complainant_demographic_code = f_enum(
        payload,
        "complainant_demographic_code",
        calc.COMPLAINANT_DEMOGRAPHIC_CODES,
        required=False,
        default="UNKNOWN",
    )
    supervisor_id = payload.get("reporting_supervisor_officer_id")
    if intake_channel == "SUPERVISOR":
        reporting_supervisor_officer_id = f_str(
            payload, "reporting_supervisor_officer_id"
        )
    else:
        if supervisor_id is not None:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "reporting_supervisor_officer_id is only valid on a SUPERVISOR intake.",
            )
        reporting_supervisor_officer_id = None
    # tier 5 -- body reference existence
    if reporting_supervisor_officer_id is not None:
        svc.need_officer(reporting_supervisor_officer_id)
    svc.need_unit(subject_unit_id)
    # tier 10 -- referential
    if calc.internal_affairs_unit() is None:
        raise ApiError("ERR_NO_INTAKE_UNIT")
    # tier 11 -- temporal
    if incident_datetime < add_days(db.clock, -calc.STATUTE_DAYS):
        raise ApiError("ERR_STATUTE_EXPIRED")
    # tier 12 -- business constraint
    if intake_channel in ("PUBLIC", "SUPERVISOR"):
        if not complainant_name or not complainant_contact:
            raise ApiError("ERR_COMPLAINANT_IDENTITY_REQUIRED")
    else:
        if complainant_name or complainant_contact:
            raise ApiError("ERR_COMPLAINANT_IDENTITY_REQUIRED")

    classification, priority, screening_required, assigned_unit_id = (
        calc.classify_and_route(
            reported_allegation_types, alleged_injury, intake_channel, subject_unit_id
        )
    )
    db.intake_sequence += 1
    intake_sequence = db.intake_sequence
    reference_code = (
        None
        if intake_channel == "ANONYMOUS"
        else calc.intake_reference_code(intake_sequence)
    )
    complaint = new_row(
        "Complaint",
        intake_channel=intake_channel,
        complainant_name=complainant_name,
        complainant_contact=complainant_contact,
        complainant_demographic_code=complainant_demographic_code,
        narrative=narrative,
        incident_datetime=incident_datetime,
        alleged_injury=alleged_injury,
        reported_allegation_types=list(reported_allegation_types),
        subject_unit_id=subject_unit_id,
        reporting_supervisor_officer_id=reporting_supervisor_officer_id,
        intake_sequence=intake_sequence,
        intake_reference_code=reference_code,
        classification=classification,
        priority=priority,
        assigned_unit_id=assigned_unit_id,
        screening_required=screening_required,
        statute_expires_at=add_days(incident_datetime, calc.STATUTE_DAYS),
        status="SCREENING" if screening_required else "CLASSIFIED",
        received_at=db.clock,
        closed_at=None,
        retention_until=None,
        allegation_count=0,
        sustained_allegation_count=0,
        reclassification_count=0,
        purged_at=None,
    )
    db.complaints[complaint["id"]] = complaint
    return respond_object(dump(complaint), 201)


@bp.get("/complaints/<complaint_id>")
@endpoint(
    "Complainant",
    "Supervisor",
    "Investigator",
    "IACommander",
    "RecordsCustodian",
    "AppealsOfficer",
)
def read_complaint(complaint_id):
    return respond_object(dump(svc.need_complaint(complaint_id)))


@bp.get("/complaints")
@endpoint(
    "Supervisor", "Investigator", "IACommander", "RecordsCustodian", "AppealsOfficer"
)
def list_complaints():
    assigned_unit_id = q_str("assigned_unit_id")
    subject_unit_id = q_str("subject_unit_id")
    supervisor_id = q_str("reporting_supervisor_officer_id")
    status = q_enum("status", calc.COMPLAINT_STATUSES)
    classification = q_enum("classification", calc.CLASSIFICATIONS)
    intake_channel = q_enum("intake_channel", calc.INTAKE_CHANNELS)
    rows = sort_created(list(db.complaints.values()))
    if assigned_unit_id is not None:
        rows = [r for r in rows if r["assigned_unit_id"] == assigned_unit_id]
    if subject_unit_id is not None:
        rows = [r for r in rows if r["subject_unit_id"] == subject_unit_id]
    if supervisor_id is not None:
        rows = [r for r in rows if r["reporting_supervisor_officer_id"] == supervisor_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if classification is not None:
        rows = [r for r in rows if r["classification"] == classification]
    if intake_channel is not None:
        rows = [r for r in rows if r["intake_channel"] == intake_channel]
    return paginate(rows)


# ---------------------------------------------------------------------------
# Allegations
# ---------------------------------------------------------------------------
@bp.post("/complaints/<complaint_id>/allegations")
@endpoint("IACommander", "Supervisor")
def create_allegation(complaint_id):
    complaint = svc.need_complaint(complaint_id)
    payload = body()
    subject_officer_id = f_str(payload, "subject_officer_id")
    allegation_type = f_enum(payload, "allegation_type", calc.ALLEGATION_TYPES)
    narrative = f_str(payload, "narrative")
    offense_class = f_enum(payload, "offense_class", calc.OFFENSE_CLASSES)
    officer = svc.need_officer(subject_officer_id)
    if complaint["status"] not in ("SCREENING", "CLASSIFIED", "UNDER_INVESTIGATION"):
        raise ApiError("ERR_COMPLAINT_STATE_INVALID")
    allegation = new_row(
        "Allegation",
        complaint_id=complaint["id"],
        subject_officer_id=subject_officer_id,
        allegation_type=allegation_type,
        narrative=narrative,
        offense_class=offense_class,
        evidence_weight_for=Decimal("0"),
        evidence_weight_against=Decimal("0"),
        policy_compliant=None,
        support_pct=Decimal("0.00"),
        preponderance_met=False,
        disposition="PENDING",
        disposed_at=None,
        prior_sustained_count_at_disposition=None,
        redacted=False,
    )
    db.allegations[allegation["id"]] = allegation
    complaint["allegation_count"] += 1
    touch(complaint)
    svc.append_activity_event(
        officer["id"],
        "COMPLAINT_INTAKE",
        "NA",
        complaint["received_at"],
        source_reference=complaint["id"],
        system_generated=True,
    )
    svc.recompute_officer_eis(officer)
    return respond_object(dump(allegation), 201)


@bp.get("/allegations/<allegation_id>")
@endpoint(
    "Supervisor", "Investigator", "IACommander", "RecordsCustodian", "AppealsOfficer"
)
def read_allegation(allegation_id):
    return respond_object(dump(svc.need_allegation(allegation_id)))


@bp.get("/allegations")
@endpoint(
    "Supervisor", "Investigator", "IACommander", "RecordsCustodian", "AppealsOfficer"
)
def list_allegations():
    complaint_id = q_str("complaint_id")
    subject_officer_id = q_str("subject_officer_id")
    disposition = q_enum("disposition", calc.DISPOSITIONS)
    allegation_type = q_enum("allegation_type", calc.ALLEGATION_TYPES)
    rows = sort_created(list(db.allegations.values()))
    if complaint_id is not None:
        rows = [r for r in rows if r["complaint_id"] == complaint_id]
    if subject_officer_id is not None:
        rows = [r for r in rows if r["subject_officer_id"] == subject_officer_id]
    if disposition is not None:
        rows = [r for r in rows if r["disposition"] == disposition]
    if allegation_type is not None:
        rows = [r for r in rows if r["allegation_type"] == allegation_type]
    return paginate(rows)


# ---------------------------------------------------------------------------
# Screening, reclassification
# ---------------------------------------------------------------------------
@bp.post("/complaints/<complaint_id>/classify")
@endpoint("IACommander")
def classify_complaint(complaint_id):
    complaint = svc.need_complaint(complaint_id)
    payload = body()
    outcome = f_enum(payload, "screening_outcome", SCREENING_OUTCOMES)
    override = f_enum(
        payload, "classification_override", calc.CLASSIFICATIONS, required=False
    )
    rejection_reason = f_str(
        payload, "rejection_reason", required=(outcome == "REJECT")
    )
    # tier 8 -- state legality
    if outcome == "REJECT":
        if complaint["status"] != "SCREENING":
            raise ApiError("ERR_COMPLAINT_STATE_INVALID")
    elif complaint["status"] not in ("SCREENING", "CLASSIFIED", "UNDER_INVESTIGATION"):
        raise ApiError("ERR_COMPLAINT_STATE_INVALID")
    # tier 10 -- referential business rules
    if calc.internal_affairs_unit() is None:
        raise ApiError("ERR_NO_INTAKE_UNIT")

    if outcome == "REJECT":
        complaint["status"] = "REJECTED_INTAKE"
        complaint["closed_at"] = db.clock
        complaint["retention_until"] = add_days(
            db.clock, calc.RETENTION_DAYS_BY_DISPOSITION["WITHDRAWN"]
        )
        touch(complaint)
        for allegation in svc.allegations_of(complaint["id"]):
            allegation["disposition"] = "WITHDRAWN"
            allegation["disposed_at"] = complaint["closed_at"]
            touch(allegation)
        return respond_object(dump(complaint))

    if complaint["status"] == "SCREENING":
        classification, priority, screening_required, assigned_unit_id = (
            calc.classify_and_route(
                complaint["reported_allegation_types"],
                complaint["alleged_injury"],
                complaint["intake_channel"],
                complaint["subject_unit_id"],
                override,
            )
        )
        complaint["classification"] = classification
        complaint["priority"] = priority
        complaint["assigned_unit_id"] = assigned_unit_id
        complaint["screening_required"] = False
        complaint["status"] = "CLASSIFIED"
        touch(complaint)
        return respond_object(dump(complaint))

    # Reclassification self-loop from CLASSIFIED or UNDER_INVESTIGATION.
    # tier 12 -- business constraints
    if (
        complaint["reclassification_count"] >= calc.MAX_RECLASSIFICATIONS
        or override is None
        or override == complaint["classification"]
    ):
        raise ApiError("ERR_MAX_RECLASSIFICATIONS_REACHED")
    complaint["reclassification_count"] += 1
    complaint["classification"] = override
    complaint["priority"] = calc.PRIORITY_BY_CLASSIFICATION[override]
    complaint["assigned_unit_id"] = calc.routing_target(
        override, complaint["screening_required"], complaint["subject_unit_id"]
    )
    touch(complaint)
    investigation = svc.investigation_of(complaint["id"])
    if investigation is not None and investigation["status"] not in ("CLOSED", "VOIDED"):
        svc.refresh_investigation_window(investigation, complaint)
        assignee_id = investigation.get("assigned_investigator_officer_id")
        assignee = db.officers.get(assignee_id) if assignee_id else None
        forced = (
            assignee is not None
            and investigation["required_certification_level"]
            > assignee["certification_level"]
        )
        if forced:
            svc.release_investigator(investigation)
            investigation["assigned_investigator_officer_id"] = None
            investigation["status"] = "UNASSIGNED"
        touch(investigation)
    return respond_object(dump(complaint))


# ---------------------------------------------------------------------------
# Withdrawal
# ---------------------------------------------------------------------------
@bp.post("/complaints/<complaint_id>/withdraw")
@endpoint("Complainant", "Supervisor")
def withdraw_complaint(complaint_id):
    complaint = svc.need_complaint(complaint_id)
    payload = body()
    supplied_code = f_str(payload, "intake_reference_code")
    f_str(payload, "withdrawal_reason", required=False)
    # tier 6 -- resource-level ownership (the intake credential)
    stored_code = complaint.get("intake_reference_code")
    if stored_code is not None and supplied_code != stored_code:
        raise ApiError("ERR_INTAKE_CODE_MISMATCH")
    # tier 8 -- state legality
    if complaint["status"] not in ("CLASSIFIED", "UNDER_INVESTIGATION", "ADJUDICATION"):
        raise ApiError("ERR_COMPLAINT_STATE_INVALID")
    # tier 12 -- business constraints
    if complaint["intake_channel"] not in ("PUBLIC", "SUPERVISOR"):
        raise ApiError("ERR_ANONYMOUS_NOT_WITHDRAWABLE")
    if complaint["sustained_allegation_count"] != 0:
        raise ApiError("ERR_SUSTAINED_NOT_WITHDRAWABLE")

    from_status = complaint["status"]
    complaint["status"] = "WITHDRAWN"
    complaint["closed_at"] = db.clock
    complaint["retention_until"] = add_days(
        db.clock, calc.RETENTION_DAYS_BY_DISPOSITION["WITHDRAWN"]
    )
    touch(complaint)
    for allegation in svc.allegations_of(complaint["id"]):
        if allegation["disposition"] == "PENDING":
            allegation["disposition"] = "WITHDRAWN"
            allegation["disposed_at"] = complaint["closed_at"]
            touch(allegation)
    if from_status in ("UNDER_INVESTIGATION", "ADJUDICATION"):
        investigation = svc.investigation_of(complaint["id"])
        if investigation is not None and investigation["status"] not in (
            "CLOSED",
            "VOIDED",
        ):
            svc.void_investigation(investigation, cancel_sessions=True)
    return respond_object(dump(complaint))


# ---------------------------------------------------------------------------
# Purge
# ---------------------------------------------------------------------------
@bp.post("/complaints/<complaint_id>/purge")
@endpoint("RecordsCustodian")
def purge_complaint(complaint_id):
    complaint = svc.need_complaint(complaint_id)
    payload = body()
    f_str(payload, "purge_reason", required=False)
    allegations = svc.allegations_of(complaint["id"])
    # tier 8 -- purgeability
    if complaint["status"] not in ("CLOSED", "WITHDRAWN") or complaint["purged_at"]:
        raise ApiError("ERR_COMPLAINT_NOT_PURGEABLE")
    # tier 9 -- business safety
    allegation_ids = {a["id"] for a in allegations}
    held = any(
        d["status"] == "ACTIVE" and d["source_allegation_id"] in allegation_ids
        for d in db.disclosures.values()
    )
    if not held:
        held = any(
            a["allegation_type"] == "UNTRUTHFULNESS" and a["disposition"] == "SUSTAINED"
            for a in allegations
        )
    if held:
        raise ApiError("ERR_CREDIBILITY_HOLD")
    discipline_ids = {
        d["id"] for d in db.disciplines.values() if d["allegation_id"] in allegation_ids
    }
    if any(
        a["discipline_id"] in discipline_ids and a["status"] in ("FILED", "HEARD")
        for a in db.appeals.values()
    ):
        raise ApiError("ERR_APPEAL_PENDING")
    # tier 11 -- temporal
    retention_until = complaint.get("retention_until")
    if retention_until is None or db.clock < retention_until:
        raise ApiError("ERR_RETENTION_NOT_EXPIRED")

    complaint["narrative"] = None
    complaint["complainant_name"] = None
    complaint["complainant_contact"] = None
    complaint["complainant_demographic_code"] = "UNKNOWN"
    complaint["purged_at"] = db.clock
    complaint["status"] = "PURGED"
    touch(complaint)
    for allegation in allegations:
        allegation["narrative"] = None
        allegation["redacted"] = True
        touch(allegation)
    return respond_object(dump(complaint))
