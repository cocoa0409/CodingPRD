"""Routes: assessments, the referral fork, cosignature and prescribing."""

from flask import Blueprint

import calc
import engine
import serial
from auth import (
    ROLE_CLINIC_ADMIN,
    ROLE_CLINICIAN,
    ROLE_PHYSICIAN,
    authenticate,
)
from common import (
    collection,
    get_assessment,
    get_prescription,
    get_visit,
    state_rule_or_404,
)
from envelope import object_response
from errors import (
    ERR_ASSESSMENT_INVALID_STATE,
    ERR_CLINIC_CLOSED,
    ERR_CONTROLLED_RX_NOT_PERMITTED,
    ERR_COSIGN_NOT_REQUIRED,
    ERR_DUPLICATE_THERAPY,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_PHYSICIAN_NOT_LICENSED_IN_STATE,
    ERR_PRESCRIPTION_INVALID_STATE,
    ERR_REFERRAL_REQUIRED,
    ERR_SCOPE_HOLD_ACTIVE,
    ERR_STALE_VISIT_VERSION,
    ERR_VISIT_INVALID_STATE,
    ERR_VISIT_NOT_TREATABLE,
    raise_error,
)
from shapes import (
    json_body,
    query_enum,
    query_string,
    read_enum,
    read_int,
    read_npi,
    read_number,
    read_string,
    read_string_array,
    reject_unknown,
)
from store import db, new_row, ordered, touch

bp = Blueprint("clinical", __name__)

ASSESSMENT_STATUSES = (
    "DRAFT",
    "REFERRAL_REQUIRED",
    "TREATMENT_AUTHORIZED",
    "COSIGNED",
)
PRESCRIPTION_STATUSES = ("DRAFT", "ROUTED", "CANCELLED")
COSIGNABLE = ("TREATMENT_AUTHORIZED", "REFERRAL_REQUIRED")


def _require_scope_clear(clinician_id):
    clinician = db.clinicians.get(clinician_id)
    if clinician is not None and clinician["scope_hold"]:
        raise_error(
            ERR_SCOPE_HOLD_ACTIVE,
            "Clinician %s is on scope hold." % clinician_id,
        )


def _locked_classes(patient_id, ignore_prescription_id=None):
    classes = set()
    for rx in db.prescriptions.values():
        if rx["patient_id"] != patient_id:
            continue
        if rx["status"] != "ROUTED":
            continue
        if ignore_prescription_id is not None and rx["id"] == ignore_prescription_id:
            continue
        classes.add(rx["therapy_class"])
    return classes


# ---------------------------------------------------------------------------
# POST /assessments
# ---------------------------------------------------------------------------

@bp.route("/assessments", methods=["POST"])
def create_assessment():
    actor = authenticate([ROLE_CLINICIAN])
    body = json_body(required=True)
    reject_unknown(body, {
        "visit_id",
        "temp_c",
        "heart_rate_bpm",
        "spo2_pct",
        "red_flag_codes",
    })
    visit_id = read_string(body, "visit_id")
    temp_c = read_number(body, "temp_c", minimum=30.0, maximum=43.0)
    heart_rate = read_int(body, "heart_rate_bpm", minimum=20, maximum=250)
    spo2 = read_int(body, "spo2_pct", minimum=50, maximum=100)
    red_flags = read_string_array(body, "red_flag_codes", required=False)
    if red_flags is None:
        red_flags = []

    # rung 7 - body reference
    visit = get_visit(visit_id)

    # rung 10 - declared transition
    if visit["clinical_status"] != "SCREENING":
        raise_error(
            ERR_VISIT_INVALID_STATE,
            "Visit %s is %s and cannot begin an assessment."
            % (visit["id"], visit["clinical_status"]),
        )

    # ownership - only the visit's own clinician assesses it
    if visit["clinician_id"] != actor.user_id:
        raise_error(
            ERR_FORBIDDEN_OWNERSHIP,
            "Only the visit's own clinician may assess it.",
        )

    # rung 13 - scope hold
    _require_scope_clear(actor.user_id)

    # rung 12 - clinic posture
    clinic = db.clinics.get(visit["clinic_id"])
    if clinic is not None and clinic["open_status"] == "CLOSED":
        raise_error(ERR_CLINIC_CLOSED)

    row = new_row()
    row.update({
        "visit_id": visit["id"],
        "protocol_id": visit["protocol_id"],
        "cosigned_by_physician_id": None,
        "temp_c": temp_c,
        "heart_rate_bpm": heart_rate,
        "spo2_pct": spo2,
        "red_flag_codes": list(red_flags),
        "referral_destination": None,
        "referral_reason_code": None,
        "cosigned_at": None,
        "status": "DRAFT",
    })
    db.assessments[row["id"]] = row

    visit["clinical_status"] = "IN_ASSESSMENT"
    touch(visit)
    return object_response(serial.assessment(row), 201)


# ---------------------------------------------------------------------------
# POST /assessments/{assessmentId}/submit
# ---------------------------------------------------------------------------

@bp.route("/assessments/<assessment_id>/submit", methods=["POST"])
def submit_assessment(assessment_id):
    actor = authenticate([ROLE_CLINICIAN])
    body = json_body(required=False)
    reject_unknown(body, set())

    row = get_assessment(assessment_id)

    # rung 10 - declared transition
    if row["status"] != "DRAFT":
        raise_error(
            ERR_ASSESSMENT_INVALID_STATE,
            "Assessment %s is %s and cannot be submitted."
            % (row["id"], row["status"]),
        )

    visit = db.visits[row["visit_id"]]

    # rung 25 - ownership
    if visit["clinician_id"] != actor.user_id:
        raise_error(
            ERR_FORBIDDEN_OWNERSHIP,
            "Only the visit's own clinician may submit its assessment.",
        )

    # rung 13 - scope hold
    _require_scope_clear(actor.user_id)

    protocol = db.protocols[row["protocol_id"]]
    destination, reason = calc.referral_trigger_evaluation(row, protocol)

    if destination is not None:
        row["referral_destination"] = destination
        row["referral_reason_code"] = reason
        row["status"] = "REFERRAL_REQUIRED"
        touch(row)

        visit["clinical_status"] = "REFERRED"
        visit["referral_required"] = True
        touch(visit)

        cancelled_any = False
        for rx in ordered(db.prescriptions.values()):
            if rx["visit_id"] != visit["id"]:
                continue
            if rx["status"] not in ("DRAFT", "ROUTED"):
                continue
            rx["status"] = "CANCELLED"
            rx["cancel_reason"] = "REFERRAL_CASCADE"
            touch(rx)
            cancelled_any = True
        if cancelled_any:
            engine.recompute_patient_therapy(visit["patient_id"])
    else:
        row["status"] = "TREATMENT_AUTHORIZED"
        touch(row)

        visit["clinical_status"] = "TREATED"
        visit["referral_required"] = False
        touch(visit)

    return object_response(serial.assessment(row), 200)


# ---------------------------------------------------------------------------
# POST /assessments/{assessmentId}/cosign
# ---------------------------------------------------------------------------

@bp.route("/assessments/<assessment_id>/cosign", methods=["POST"])
def cosign_assessment(assessment_id):
    actor = authenticate([ROLE_PHYSICIAN])
    body = json_body(required=False)
    reject_unknown(body, set())

    row = get_assessment(assessment_id)

    # rung 10 - declared transition
    if row["status"] not in COSIGNABLE:
        raise_error(
            ERR_ASSESSMENT_INVALID_STATE,
            "Assessment %s is %s and cannot be cosigned."
            % (row["id"], row["status"]),
        )

    protocol = db.protocols[row["protocol_id"]]
    if not protocol["requires_cosign"]:
        raise_error(ERR_COSIGN_NOT_REQUIRED)

    visit = db.visits[row["visit_id"]]
    assignment = calc.active_assignment_of(visit["clinician_id"])
    if (
        assignment is None
        or assignment["pinned_supervising_physician_id"] != actor.user_id
    ):
        raise_error(
            ERR_FORBIDDEN_OWNERSHIP,
            "Only the pinned supervising physician may cosign this assessment.",
        )

    clinic = db.clinics[visit["clinic_id"]]
    if clinic["state_code"] not in actor.row["licensed_state_codes"]:
        raise_error(ERR_PHYSICIAN_NOT_LICENSED_IN_STATE)

    row["status"] = "COSIGNED"
    row["cosigned_by_physician_id"] = actor.user_id
    row["cosigned_at"] = db.clock
    touch(row)
    return object_response(serial.assessment(row), 200)


# ---------------------------------------------------------------------------
# POST /prescriptions
# ---------------------------------------------------------------------------

@bp.route("/prescriptions", methods=["POST"])
def create_prescription():
    actor = authenticate([ROLE_CLINICIAN])
    body = json_body(required=True)
    reject_unknown(body, {
        "visit_id",
        "drug_name",
        "therapy_class",
        "days_supply",
        "pharmacy_npi",
        "expected_visit_version",
        "supersedes_prescription_id",
    })
    visit_id = read_string(body, "visit_id")
    drug_name = read_string(body, "drug_name")
    therapy_class = read_enum(body, "therapy_class", calc.THERAPY_CLASSES)
    days_supply = read_int(body, "days_supply", minimum=1, maximum=90)
    pharmacy_npi = read_npi(body, "pharmacy_npi")
    expected_version = read_int(body, "expected_visit_version", minimum=0)
    supersedes_id = read_string(
        body, "supersedes_prescription_id", required=False
    )

    # rung 7 - body references, in declaration order
    visit = get_visit(visit_id)
    predecessor = (
        get_prescription(supersedes_id) if supersedes_id is not None else None
    )

    clinic = db.clinics[visit["clinic_id"]]

    # rung 8 - state rule presence
    state_rule = state_rule_or_404(clinic["state_code"])

    # rung 11 - version pinning
    if expected_version != visit["version"]:
        raise_error(
            ERR_STALE_VISIT_VERSION,
            "Visit %s is at version %d." % (visit["id"], visit["version"]),
        )

    # rung 13 - scope hold
    _require_scope_clear(actor.user_id)

    # rung 16 - referral supremacy
    if visit["referral_required"]:
        raise_error(ERR_REFERRAL_REQUIRED)

    # rung 18 - controlled-substance permission
    if therapy_class == calc.CONTROLLED_CLASS and not state_rule[
        "controlled_rx_allowed"
    ]:
        raise_error(ERR_CONTROLLED_RX_NOT_PERMITTED)

    # rung 19 - duplicate therapy
    ignore_id = predecessor["id"] if predecessor is not None else None
    if therapy_class in _locked_classes(visit["patient_id"], ignore_id):
        raise_error(ERR_DUPLICATE_THERAPY)

    row = new_row()
    row.update({
        "visit_id": visit["id"],
        "patient_id": visit["patient_id"],
        "prescriber_clinician_id": visit["clinician_id"],
        "supersedes_prescription_id": supersedes_id,
        "drug_name": drug_name,
        "therapy_class": therapy_class,
        "days_supply": days_supply,
        "pharmacy_npi": pharmacy_npi,
        "routed_at": None,
        "status": "DRAFT",
        "cancel_reason": None,
    })
    db.prescriptions[row["id"]] = row
    return object_response(serial.prescription(row), 201)


# ---------------------------------------------------------------------------
# POST /prescriptions/{prescriptionId}/route
# ---------------------------------------------------------------------------

@bp.route("/prescriptions/<prescription_id>/route", methods=["POST"])
def route_prescription(prescription_id):
    actor = authenticate([ROLE_CLINICIAN])
    body = json_body(required=False)
    reject_unknown(body, set())

    row = get_prescription(prescription_id)

    # rung 10 - declared transition
    if row["status"] != "DRAFT":
        raise_error(
            ERR_PRESCRIPTION_INVALID_STATE,
            "Prescription %s is %s and cannot be routed."
            % (row["id"], row["status"]),
        )

    visit = db.visits[row["visit_id"]]

    # rung 16 - referral supremacy
    if visit["referral_required"]:
        raise_error(ERR_REFERRAL_REQUIRED)

    if visit["clinical_status"] != "TREATED":
        raise_error(
            ERR_VISIT_NOT_TREATABLE,
            "Visit %s is %s." % (visit["id"], visit["clinical_status"]),
        )

    # rung 19 - duplicate therapy
    predecessor = db.prescriptions.get(row["supersedes_prescription_id"])
    ignore_id = predecessor["id"] if predecessor is not None else None
    if row["therapy_class"] in _locked_classes(row["patient_id"], ignore_id):
        raise_error(ERR_DUPLICATE_THERAPY)

    # rung 25 - ownership
    if visit["clinician_id"] != actor.user_id:
        raise_error(
            ERR_FORBIDDEN_OWNERSHIP,
            "Only the visit's own clinician may route its prescriptions.",
        )

    if predecessor is not None and predecessor["status"] == "ROUTED":
        predecessor["status"] = "CANCELLED"
        predecessor["cancel_reason"] = "SUPERSEDED"
        touch(predecessor)

    row["status"] = "ROUTED"
    row["routed_at"] = db.clock
    touch(row)

    engine.recompute_patient_therapy(row["patient_id"])
    return object_response(serial.prescription(row), 200)


# ---------------------------------------------------------------------------
# POST /prescriptions/{prescriptionId}/cancel
# ---------------------------------------------------------------------------

@bp.route("/prescriptions/<prescription_id>/cancel", methods=["POST"])
def cancel_prescription(prescription_id):
    authenticate([ROLE_CLINICIAN])
    body = json_body(required=False)
    reject_unknown(body, {"cancel_reason"})
    cancel_reason = read_string(body, "cancel_reason", required=False)

    row = get_prescription(prescription_id)

    # rung 10 - declared transition
    if row["status"] == "CANCELLED":
        raise_error(
            ERR_PRESCRIPTION_INVALID_STATE,
            "Prescription %s is already CANCELLED." % row["id"],
        )

    row["status"] = "CANCELLED"
    row["cancel_reason"] = cancel_reason
    touch(row)

    engine.recompute_patient_therapy(row["patient_id"])
    return object_response(serial.prescription(row), 200)


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------

@bp.route("/assessments/<assessment_id>", methods=["GET"])
def read_assessment(assessment_id):
    authenticate([ROLE_CLINIC_ADMIN, ROLE_CLINICIAN, ROLE_PHYSICIAN])
    row = get_assessment(assessment_id)
    return object_response(serial.assessment(row), 200)


@bp.route("/assessments", methods=["GET"])
def list_assessments():
    authenticate([ROLE_CLINIC_ADMIN, ROLE_CLINICIAN, ROLE_PHYSICIAN])
    visit_id = query_string("visit_id")
    protocol_id = query_string("protocol_id")
    cosigned_by = query_string("cosigned_by_physician_id")
    status = query_enum("status", ASSESSMENT_STATUSES)
    return collection(db.assessments, serial.assessment, [
        (visit_id, lambda row, v: row["visit_id"] == v),
        (protocol_id, lambda row, v: row["protocol_id"] == v),
        (cosigned_by, lambda row, v: row["cosigned_by_physician_id"] == v),
        (status, lambda row, v: row["status"] == v),
    ])


@bp.route("/prescriptions/<prescription_id>", methods=["GET"])
def read_prescription(prescription_id):
    authenticate([ROLE_CLINIC_ADMIN, ROLE_CLINICIAN, ROLE_PHYSICIAN])
    row = get_prescription(prescription_id)
    return object_response(serial.prescription(row), 200)


@bp.route("/prescriptions", methods=["GET"])
def list_prescriptions():
    authenticate([ROLE_CLINIC_ADMIN, ROLE_CLINICIAN, ROLE_PHYSICIAN])
    visit_id = query_string("visit_id")
    patient_id = query_string("patient_id")
    prescriber_id = query_string("prescriber_clinician_id")
    supersedes_id = query_string("supersedes_prescription_id")
    therapy_class = query_enum("therapy_class", calc.THERAPY_CLASSES)
    status = query_enum("status", PRESCRIPTION_STATUSES)
    return collection(db.prescriptions, serial.prescription, [
        (visit_id, lambda row, v: row["visit_id"] == v),
        (patient_id, lambda row, v: row["patient_id"] == v),
        (prescriber_id, lambda row, v: row["prescriber_clinician_id"] == v),
        (supersedes_id, lambda row, v: row["supersedes_prescription_id"] == v),
        (therapy_class, lambda row, v: row["therapy_class"] == v),
        (status, lambda row, v: row["status"] == v),
    ])
