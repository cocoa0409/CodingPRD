"""Routes: opening a visit, coverage, self-pay acceptance, checkout and voids."""

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
)
from common import (
    collection,
    get_clinician,
    get_queue_entry,
    get_visit,
    state_rule_or_404,
)
from envelope import object_response
from errors import (
    ERR_CHARGE_NOT_VOIDABLE,
    ERR_CLINIC_CLOSED,
    ERR_CLINICIAN_NOT_LICENSED_IN_STATE,
    ERR_COSIGN_REQUIRED,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_OUTSTANDING_BALANCE_BLOCK,
    ERR_OUT_OF_PROTOCOL_SCOPE,
    ERR_PAYMENT_METHOD_REQUIRED,
    ERR_PROTOCOL_NOT_OFFERED_IN_STATE,
    ERR_QUEUE_ENTRY_NOT_CALLABLE,
    ERR_QUOTE_MISMATCH,
    ERR_QUOTE_REQUIRED,
    ERR_SCOPE_HOLD_ACTIVE,
    ERR_VISIT_INVALID_STATE,
    raise_error,
)
from shapes import (
    bad,
    json_body,
    query_enum,
    query_string,
    read_enum,
    read_enum_array,
    read_int,
    read_number,
    read_string,
    reject_unknown,
)
from store import db, new_row, touch

bp = Blueprint("visits", __name__)

CLINICAL_STATUSES = (
    "SCREENING",
    "IN_ASSESSMENT",
    "TREATED",
    "REFERRED",
    "CLOSED",
    "CANCELLED_CLOSURE",
)
BILLING_STATUSES = (
    "UNBILLED",
    "COVERAGE_VERIFIED",
    "SELF_PAY_QUOTED",
    "SELF_PAY_ACCEPTED",
    "INVOICED",
    "VOIDED",
)
COVERAGE_RESULTS = ("ACTIVE", "INACTIVE", "UNKNOWN")


# ---------------------------------------------------------------------------
# POST /visits
# ---------------------------------------------------------------------------

@bp.route("/visits", methods=["POST"])
def create_visit():
    actor = authenticate([ROLE_CLINICIAN])
    body = json_body(required=True)
    reject_unknown(body, {"queue_entry_id", "clinician_id"})
    queue_entry_id = read_string(body, "queue_entry_id")
    clinician_id = read_string(body, "clinician_id", required=False)

    # rung 7 - body references, in declaration order
    entry = get_queue_entry(queue_entry_id)
    clinician = get_clinician(
        clinician_id if clinician_id is not None else actor.user_id
    )

    clinic = db.clinics[entry["clinic_id"]]

    # rung 8 - state rule presence
    state_rule = state_rule_or_404(clinic["state_code"])

    # rung 12 - clinic posture
    if clinic["open_status"] == "CLOSED":
        raise_error(ERR_CLINIC_CLOSED)

    # rung 13 - scope hold
    if clinician["scope_hold"]:
        raise_error(
            ERR_SCOPE_HOLD_ACTIVE,
            "Clinician %s is on scope hold." % clinician["id"],
        )

    # rung 14 - protocol availability
    protocol = calc.protocol_for(entry["complaint_code"], clinic["state_code"])
    if protocol is None:
        raise_error(ERR_PROTOCOL_NOT_OFFERED_IN_STATE)

    # rung 15 - age scope
    patient = db.patients[entry["patient_id"]]
    age = calc.age_months(patient["date_of_birth"])
    if not calc.age_in_scope(age, protocol, state_rule):
        raise_error(ERR_OUT_OF_PROTOCOL_SCOPE)

    # rung 20 - clinician licensure
    if clinician["license_state_code"] != clinic["state_code"]:
        raise_error(ERR_CLINICIAN_NOT_LICENSED_IN_STATE)

    # rung 23 - queue-entry consumability
    if entry["status"] != "CALLED" or calc.visits_for_queue_entry(entry["id"]):
        raise_error(
            ERR_QUEUE_ENTRY_NOT_CALLABLE,
            "Queue entry %s cannot be consumed." % entry["id"],
        )

    # rung 37 - balance ceiling on the self-pay path
    if (
        patient.get("payer_name") is None
        and patient["outstanding_balance_cents"]
        > calc.SELF_PAY_BALANCE_CEILING_CENTS
    ):
        raise_error(ERR_OUTSTANDING_BALANCE_BLOCK)

    row = new_row()
    row.update({
        "clinic_id": clinic["id"],
        "patient_id": patient["id"],
        "queue_entry_id": entry["id"],
        "protocol_id": protocol["id"],
        "clinician_id": clinician["id"],
        "complaint_code": entry["complaint_code"],
        "patient_age_months_at_visit": age,
        "clinical_status": "SCREENING",
        "billing_status": "UNBILLED",
        "self_pay": False,
        "coverage_status": "UNVERIFIED",
        "copay_cents": None,
        "coinsurance_pct": None,
        "quoted_price_cents": None,
        "final_price_cents": None,
        "patient_responsibility_cents": None,
        "payer_responsibility_cents": None,
        "services_rendered": [],
        "referral_required": False,
    })
    db.visits[row["id"]] = row

    entry["status"] = "SERVED"
    touch(entry)
    engine.refresh_clinic(clinic)

    return object_response(serial.visit(row), 201)


# ---------------------------------------------------------------------------
# POST /visits/{visitId}/eligibility-check
# ---------------------------------------------------------------------------

@bp.route("/visits/<visit_id>/eligibility-check", methods=["POST"])
def eligibility_check(visit_id):
    authenticate([ROLE_FRONT_DESK])
    body = json_body(required=True)
    reject_unknown(body, {"coverage_status", "copay_cents", "coinsurance_pct"})
    coverage_status = read_enum(body, "coverage_status", COVERAGE_RESULTS)
    copay = read_int(body, "copay_cents", required=False, minimum=0)
    coinsurance = read_number(
        body, "coinsurance_pct", required=False, minimum=0, maximum=100
    )
    if coverage_status == "ACTIVE" and (copay is None or coinsurance is None):
        bad(
            "Fields 'copay_cents' and 'coinsurance_pct' are required when "
            "coverage_status is ACTIVE."
        )

    visit = get_visit(visit_id)

    # rung 10 - declared transition
    if visit["billing_status"] != "UNBILLED" or visit["clinical_status"] in (
        "CLOSED",
        "CANCELLED_CLOSURE",
    ):
        raise_error(
            ERR_VISIT_INVALID_STATE,
            "Visit %s cannot record an eligibility result." % visit["id"],
        )

    patient = db.patients[visit["patient_id"]]

    # rung 36 - payment method
    if coverage_status == "ACTIVE" and patient.get("payer_name") is None:
        raise_error(
            ERR_PAYMENT_METHOD_REQUIRED,
            "Patient %s has no payer on file." % patient["id"],
        )

    protocol = db.protocols[visit["protocol_id"]]
    visit["coverage_status"] = coverage_status
    if coverage_status == "ACTIVE":
        visit["self_pay"] = False
        visit["copay_cents"] = copay
        visit["coinsurance_pct"] = coinsurance
        visit["quoted_price_cents"] = calc.insured_quote(
            protocol["base_price_cents"], copay, coinsurance
        )
        visit["billing_status"] = "COVERAGE_VERIFIED"
    else:
        visit["self_pay"] = True
        visit["copay_cents"] = None
        visit["coinsurance_pct"] = None
        visit["quoted_price_cents"] = calc.self_pay_quote(
            protocol["base_price_cents"]
        )
        visit["billing_status"] = "SELF_PAY_QUOTED"
    touch(visit)
    return object_response(serial.visit(visit), 200)


# ---------------------------------------------------------------------------
# POST /visits/{visitId}/accept-self-pay
# ---------------------------------------------------------------------------

@bp.route("/visits/<visit_id>/accept-self-pay", methods=["POST"])
def accept_self_pay(visit_id):
    actor = authenticate([ROLE_PATIENT, ROLE_FRONT_DESK])
    body = json_body(required=True)
    reject_unknown(body, {"acknowledged_price_cents"})
    acknowledged = read_int(body, "acknowledged_price_cents", minimum=0)

    visit = get_visit(visit_id)

    # rung 10 - declared transition
    if visit["billing_status"] != "SELF_PAY_QUOTED":
        raise_error(
            ERR_VISIT_INVALID_STATE,
            "Visit %s is %s and cannot accept a self-pay quote."
            % (visit["id"], visit["billing_status"]),
        )

    if actor.is_patient and actor.user_id != visit["patient_id"]:
        raise_error(
            ERR_FORBIDDEN_OWNERSHIP,
            "A patient may only accept their own quote.",
        )

    if acknowledged != visit["quoted_price_cents"]:
        raise_error(
            ERR_QUOTE_MISMATCH,
            "The acknowledged amount does not equal the quoted amount.",
        )

    visit["billing_status"] = "SELF_PAY_ACCEPTED"
    touch(visit)
    return object_response(serial.visit(visit), 200)


# ---------------------------------------------------------------------------
# POST /visits/{visitId}/checkout
# ---------------------------------------------------------------------------

@bp.route("/visits/<visit_id>/checkout", methods=["POST"])
def checkout(visit_id):
    authenticate([ROLE_CLINICIAN])
    body = json_body(required=False)
    reject_unknown(body, {"services_rendered"})
    services = read_enum_array(
        body, "services_rendered", calc.SERVICE_CODES, required=False
    )
    if services is None:
        services = []

    visit = get_visit(visit_id)

    # rung 10 - declared transition
    if visit["clinical_status"] not in ("TREATED", "REFERRED"):
        raise_error(
            ERR_VISIT_INVALID_STATE,
            "Visit %s is %s and cannot be checked out."
            % (visit["id"], visit["clinical_status"]),
        )

    protocol = db.protocols[visit["protocol_id"]]

    # rung 17 - cosignature
    if protocol["requires_cosign"] and visit["clinical_status"] == "TREATED":
        assessment = calc.assessment_for_visit(visit["id"])
        if assessment is None or assessment["status"] != "COSIGNED":
            raise_error(ERR_COSIGN_REQUIRED)

    # rung 35 - quote precedence
    if visit["billing_status"] == "UNBILLED":
        raise_error(ERR_QUOTE_REQUIRED)

    # rung 36 - payment method
    if visit["billing_status"] == "SELF_PAY_QUOTED":
        raise_error(
            ERR_PAYMENT_METHOD_REQUIRED,
            "The self-pay quote has not been accepted.",
        )

    referred = visit["clinical_status"] == "REFERRED"
    final_price, patient_share, payer_share = calc.visit_price_final(
        visit, protocol, services, referred
    )

    visit["services_rendered"] = list(services)
    visit["final_price_cents"] = final_price
    visit["patient_responsibility_cents"] = patient_share
    visit["payer_responsibility_cents"] = payer_share
    visit["clinical_status"] = "CLOSED"
    visit["billing_status"] = "INVOICED"
    touch(visit)

    engine.recompute_patient_balance(visit["patient_id"])

    patient = db.patients[visit["patient_id"]]
    if patient["pcp_consent_on_file"]:
        kind, address = calc.summary_destination_selection(patient)
        summary = new_row()
        summary.update({
            "visit_id": visit["id"],
            "destination_kind": kind,
            "destination_address": address,
            "includes_referral": referred,
            "attempt_count": 0,
            "last_error_code": None,
            "sent_at": None,
            "status": "QUEUED",
        })
        db.visit_summaries[summary["id"]] = summary

    return object_response(serial.visit(visit), 200)


# ---------------------------------------------------------------------------
# POST /visits/{visitId}/charge-void
# ---------------------------------------------------------------------------

@bp.route("/visits/<visit_id>/charge-void", methods=["POST"])
def charge_void(visit_id):
    authenticate([ROLE_CLINIC_ADMIN])
    body = json_body(required=True)
    reject_unknown(body, {"void_reason"})
    read_string(body, "void_reason")

    visit = get_visit(visit_id)

    # rung 38 - voidability
    if visit["billing_status"] != "INVOICED":
        raise_error(
            ERR_CHARGE_NOT_VOIDABLE,
            "Visit %s is %s and cannot be voided."
            % (visit["id"], visit["billing_status"]),
        )

    visit["billing_status"] = "VOIDED"
    touch(visit)
    engine.recompute_patient_balance(visit["patient_id"])
    return object_response(serial.visit(visit), 200)


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------

@bp.route("/visits/<visit_id>", methods=["GET"])
def read_visit(visit_id):
    actor = authenticate([ROLE_CLINIC_ADMIN, ROLE_CLINICIAN, ROLE_PHYSICIAN,
                          ROLE_FRONT_DESK, ROLE_PATIENT])
    row = get_visit(visit_id)
    if actor.is_patient and actor.user_id != row["patient_id"]:
        raise_error(
            ERR_FORBIDDEN_OWNERSHIP,
            "A patient may only read their own visits.",
        )
    return object_response(serial.visit(row), 200)


@bp.route("/visits", methods=["GET"])
def list_visits():
    authenticate([ROLE_CLINIC_ADMIN, ROLE_CLINICIAN, ROLE_PHYSICIAN,
                  ROLE_FRONT_DESK])
    clinic_id = query_string("clinic_id")
    patient_id = query_string("patient_id")
    clinician_id = query_string("clinician_id")
    queue_entry_id = query_string("queue_entry_id")
    protocol_id = query_string("protocol_id")
    clinical_status = query_enum("clinical_status", CLINICAL_STATUSES)
    billing_status = query_enum("billing_status", BILLING_STATUSES)
    return collection(db.visits, serial.visit, [
        (clinic_id, lambda row, v: row["clinic_id"] == v),
        (patient_id, lambda row, v: row["patient_id"] == v),
        (clinician_id, lambda row, v: row["clinician_id"] == v),
        (queue_entry_id, lambda row, v: row["queue_entry_id"] == v),
        (protocol_id, lambda row, v: row["protocol_id"] == v),
        (clinical_status, lambda row, v: row["clinical_status"] == v),
        (billing_status, lambda row, v: row["billing_status"] == v),
    ])
