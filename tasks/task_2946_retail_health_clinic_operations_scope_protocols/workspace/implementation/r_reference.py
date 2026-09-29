"""Routes: the logical clock and the reference-data surface."""

from flask import Blueprint

import calc
import engine
import serial
from auth import (
    ROLE_CLINIC_ADMIN,
    ROLE_CLINICIAN,
    ROLE_FRONT_DESK,
    ROLE_PATIENT,
    ROLE_PHYSICIAN,
    authenticate,
    patient_scope,
)
from common import (
    collection,
    get_clinic,
    get_clinician,
    get_patient,
    get_physician,
    get_protocol,
    state_rule_or_404,
)
from envelope import iso3, object_response
from errors import (
    ERR_DUPLICATE_PROTOCOL_OFFERING,
    ERR_DUPLICATE_STATE_RULE,
    raise_error,
)
from shapes import (
    bad,
    json_body,
    present,
    query_bool,
    query_enum,
    read_bool,
    read_date,
    read_enum,
    read_instant,
    read_int,
    read_number,
    read_state_code,
    read_state_code_array,
    read_string,
    read_string_array,
    reject_unknown,
    query_string,
)
from store import db, new_row

bp = Blueprint("reference", __name__)


# ---------------------------------------------------------------------------
# POST /_clock/set_current_utc
# ---------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate([ROLE_CLINIC_ADMIN])
    body = json_body(required=True)
    reject_unknown(body, {"current_utc"})
    target = read_instant(body, "current_utc")

    result = engine.advance_clock(target)
    data = {"current_utc": iso3(db.clock)}
    data.update(result)
    return object_response(data, 200)


# ---------------------------------------------------------------------------
# POST /state-rules
# ---------------------------------------------------------------------------

@bp.route("/state-rules", methods=["POST"])
def create_state_rule():
    authenticate([ROLE_CLINIC_ADMIN])
    body = json_body(required=True)
    reject_unknown(body, {
        "state_code",
        "chart_review_sample_pct",
        "review_deadline_hours",
        "collaborating_physician_required",
        "min_independent_practice_age_months",
        "controlled_rx_allowed",
        "max_supervised_clinicians_per_physician",
    })
    state_code = read_state_code(body, "state_code")
    sample_pct = read_int(body, "chart_review_sample_pct", minimum=0, maximum=100)
    deadline = read_int(body, "review_deadline_hours", minimum=1)
    physician_required = read_bool(body, "collaborating_physician_required")
    min_age = read_int(body, "min_independent_practice_age_months", minimum=0)
    controlled = read_bool(body, "controlled_rx_allowed")
    max_supervised = read_int(
        body, "max_supervised_clinicians_per_physician", minimum=1
    )

    if calc.state_rule_for(state_code) is not None:
        raise_error(
            ERR_DUPLICATE_STATE_RULE,
            "State %s is already registered." % state_code,
        )

    row = new_row()
    row.update({
        "state_code": state_code,
        "chart_review_sample_pct": sample_pct,
        "review_deadline_hours": deadline,
        "collaborating_physician_required": physician_required,
        "min_independent_practice_age_months": min_age,
        "controlled_rx_allowed": controlled,
        "max_supervised_clinicians_per_physician": max_supervised,
    })
    db.state_rules[row["id"]] = row
    return object_response(serial.state_rule(row), 201)


# ---------------------------------------------------------------------------
# POST /protocols
# ---------------------------------------------------------------------------

@bp.route("/protocols", methods=["POST"])
def create_protocol():
    authenticate([ROLE_CLINIC_ADMIN])
    body = json_body(required=True)
    reject_unknown(body, {
        "complaint_code",
        "min_age_months",
        "max_age_months",
        "base_price_cents",
        "acuity_tier",
        "red_flag_codes",
        "max_temp_c",
        "max_heart_rate_bpm",
        "min_spo2_pct",
        "requires_cosign",
        "allowed_state_codes",
    })
    complaint = read_enum(body, "complaint_code", calc.COMPLAINT_CODES)
    min_age = read_int(body, "min_age_months", minimum=0)
    max_age = read_int(body, "max_age_months", minimum=0)
    base_price = read_int(body, "base_price_cents", minimum=1)
    acuity = read_int(body, "acuity_tier", minimum=1, maximum=3)
    red_flags = read_string_array(body, "red_flag_codes")
    max_temp = read_number(body, "max_temp_c")
    max_hr = read_int(body, "max_heart_rate_bpm", minimum=0)
    min_spo2 = read_int(body, "min_spo2_pct", minimum=0)
    requires_cosign = read_bool(body, "requires_cosign")
    states = read_state_code_array(body, "allowed_state_codes", non_empty=True)

    if max_age <= min_age:
        bad("Field 'max_age_months' must be strictly greater than 'min_age_months'.")

    for existing in db.protocols.values():
        if existing["complaint_code"] != complaint:
            continue
        if set(existing["allowed_state_codes"]) & set(states):
            raise_error(
                ERR_DUPLICATE_PROTOCOL_OFFERING,
                "A protocol already offers %s in one of those states." % complaint,
            )

    row = new_row()
    row.update({
        "complaint_code": complaint,
        "min_age_months": min_age,
        "max_age_months": max_age,
        "base_price_cents": base_price,
        "acuity_tier": acuity,
        "red_flag_codes": red_flags,
        "max_temp_c": max_temp,
        "max_heart_rate_bpm": max_hr,
        "min_spo2_pct": min_spo2,
        "requires_cosign": requires_cosign,
        "allowed_state_codes": states,
    })
    db.protocols[row["id"]] = row
    return object_response(serial.protocol(row), 201)


# ---------------------------------------------------------------------------
# POST /clinics
# ---------------------------------------------------------------------------

@bp.route("/clinics", methods=["POST"])
def create_clinic():
    authenticate([ROLE_CLINIC_ADMIN])
    body = json_body(required=True)
    reject_unknown(body, {
        "name",
        "state_code",
        "min_clinicians_required",
        "appointment_slots_per_hour",
        "walk_in_queue_capacity",
    })
    name = read_string(body, "name")
    state_code = read_state_code(body, "state_code")
    min_clinicians = read_int(
        body, "min_clinicians_required", required=False, minimum=1
    )
    if min_clinicians is None:
        min_clinicians = 1
    slots = read_int(body, "appointment_slots_per_hour", minimum=1)
    capacity = read_int(body, "walk_in_queue_capacity", minimum=1)

    state_rule_or_404(state_code)

    row = new_row()
    row.update({
        "name": name,
        "state_code": state_code,
        "min_clinicians_required": min_clinicians,
        "appointment_slots_per_hour": slots,
        "walk_in_queue_capacity": capacity,
        "on_duty_clinician_count": 0,
        "open_status": "CLOSED",
        "waiting_count": 0,
        "posted_wait_minutes": 0,
        "last_realized_wait_minutes": None,
    })
    db.clinics[row["id"]] = row
    return object_response(serial.clinic(row), 201)


# ---------------------------------------------------------------------------
# POST /physicians
# ---------------------------------------------------------------------------

@bp.route("/physicians", methods=["POST"])
def create_physician():
    authenticate([ROLE_CLINIC_ADMIN])
    body = json_body(required=True)
    reject_unknown(body, {
        "full_name",
        "licensed_state_codes",
        "max_supervised_clinicians",
        "status",
    })
    full_name = read_string(body, "full_name")
    states = read_state_code_array(body, "licensed_state_codes", non_empty=True)
    max_supervised = read_int(body, "max_supervised_clinicians", minimum=1)
    status = read_enum(
        body, "status", ("ACTIVE", "INACTIVE"), required=False
    )
    if status is None:
        status = "ACTIVE"

    row = new_row()
    row.update({
        "full_name": full_name,
        "licensed_state_codes": states,
        "max_supervised_clinicians": max_supervised,
        "status": status,
        "current_supervised_count": 0,
    })
    db.physicians[row["id"]] = row
    return object_response(serial.physician(row), 201)


# ---------------------------------------------------------------------------
# POST /clinicians
# ---------------------------------------------------------------------------

@bp.route("/clinicians", methods=["POST"])
def create_clinician():
    authenticate([ROLE_CLINIC_ADMIN])
    body = json_body(required=True)
    reject_unknown(body, {
        "full_name",
        "credential",
        "license_state_code",
        "home_clinic_id",
        "supervising_physician_id",
        "float_eligible",
    })
    full_name = read_string(body, "full_name")
    credential = read_enum(body, "credential", ("NP", "PA"))
    license_state = read_state_code(body, "license_state_code")
    home_clinic_id = read_string(body, "home_clinic_id")
    supervising_id = read_string(body, "supervising_physician_id")
    float_eligible = read_bool(body, "float_eligible", required=False, default=False)

    get_clinic(home_clinic_id)
    get_physician(supervising_id)

    row = new_row()
    row.update({
        "full_name": full_name,
        "credential": credential,
        "license_state_code": license_state,
        "home_clinic_id": home_clinic_id,
        "supervising_physician_id": supervising_id,
        "float_eligible": float_eligible,
        "scope_hold": False,
        "active_assignment_count": 0,
    })
    db.clinicians[row["id"]] = row
    return object_response(serial.clinician(row), 201)


# ---------------------------------------------------------------------------
# POST /patients
# ---------------------------------------------------------------------------

@bp.route("/patients", methods=["POST"])
def create_patient():
    authenticate([ROLE_CLINIC_ADMIN, ROLE_FRONT_DESK])
    body = json_body(required=True)
    reject_unknown(body, {
        "full_name",
        "date_of_birth",
        "payer_name",
        "member_id",
        "pcp_name",
        "pcp_direct_address",
        "pcp_accepts_electronic_summary",
        "pcp_consent_on_file",
    })
    full_name = read_string(body, "full_name")
    dob = read_date(body, "date_of_birth")
    payer_name = read_string(body, "payer_name", required=False)
    member_id = read_string(body, "member_id", required=False)
    pcp_name = read_string(body, "pcp_name", required=False)
    pcp_address = read_string(body, "pcp_direct_address", required=False)
    accepts_electronic = read_bool(
        body, "pcp_accepts_electronic_summary", required=False, default=False
    )
    consent = read_bool(body, "pcp_consent_on_file", required=False, default=False)

    if payer_name is not None and member_id is None:
        bad("Field 'member_id' is required when 'payer_name' is supplied.")

    row = new_row()
    row.update({
        "full_name": full_name,
        "date_of_birth": dob,
        "payer_name": payer_name,
        "member_id": member_id,
        "pcp_name": pcp_name,
        "pcp_direct_address": pcp_address,
        "pcp_accepts_electronic_summary": accepts_electronic,
        "pcp_consent_on_file": consent,
        "active_therapy_classes": [],
        "active_therapy_class_count": 0,
        "outstanding_balance_cents": 0,
    })
    db.patients[row["id"]] = row
    return object_response(serial.patient(row), 201)


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------

@bp.route("/protocols/<protocol_id>", methods=["GET"])
def read_protocol(protocol_id):
    authenticate([ROLE_CLINIC_ADMIN, ROLE_CLINICIAN, ROLE_PHYSICIAN,
                  ROLE_FRONT_DESK])
    row = get_protocol(protocol_id)
    return object_response(serial.protocol(row), 200)


@bp.route("/protocols", methods=["GET"])
def list_protocols():
    authenticate([ROLE_CLINIC_ADMIN, ROLE_CLINICIAN, ROLE_PHYSICIAN,
                  ROLE_FRONT_DESK])
    complaint = query_enum("complaint_code", calc.COMPLAINT_CODES)
    return collection(db.protocols, serial.protocol, [
        (complaint, lambda row, v: row["complaint_code"] == v),
    ])


@bp.route("/clinics/<clinic_id>", methods=["GET"])
def read_clinic(clinic_id):
    authenticate([ROLE_CLINIC_ADMIN, ROLE_CLINICIAN, ROLE_PHYSICIAN,
                  ROLE_FRONT_DESK, ROLE_PATIENT])
    row = get_clinic(clinic_id)
    return object_response(serial.clinic(row), 200)


@bp.route("/physicians/<physician_id>", methods=["GET"])
def read_physician(physician_id):
    authenticate([ROLE_CLINIC_ADMIN, ROLE_PHYSICIAN])
    row = get_physician(physician_id)
    return object_response(serial.physician(row), 200)


@bp.route("/clinicians/<clinician_id>", methods=["GET"])
def read_clinician(clinician_id):
    authenticate([ROLE_CLINIC_ADMIN, ROLE_CLINICIAN, ROLE_PHYSICIAN])
    row = get_clinician(clinician_id)
    return object_response(serial.clinician(row), 200)


@bp.route("/clinicians", methods=["GET"])
def list_clinicians():
    authenticate([ROLE_CLINIC_ADMIN, ROLE_PHYSICIAN])
    home_clinic_id = query_string("home_clinic_id")
    supervising_physician_id = query_string("supervising_physician_id")
    float_eligible = query_bool("float_eligible")
    scope_hold = query_bool("scope_hold")
    return collection(db.clinicians, serial.clinician, [
        (home_clinic_id, lambda row, v: row["home_clinic_id"] == v),
        (supervising_physician_id,
         lambda row, v: row["supervising_physician_id"] == v),
        (float_eligible, lambda row, v: row["float_eligible"] == v),
        (scope_hold, lambda row, v: row["scope_hold"] == v),
    ])


@bp.route("/patients/<patient_id>", methods=["GET"])
def read_patient(patient_id):
    actor = authenticate([ROLE_CLINIC_ADMIN, ROLE_CLINICIAN, ROLE_FRONT_DESK,
                          ROLE_PATIENT])
    patient_scope(actor, patient_id)
    row = get_patient(patient_id)
    return object_response(serial.patient(row), 200)
