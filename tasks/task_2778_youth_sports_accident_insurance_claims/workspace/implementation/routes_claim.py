"""Claims, provider bills, coordination records and benefit payments."""

from flask import Blueprint, g

import auth
import constants as C
import db
import guards
import response
import services
import util
import validation as v
from errors import ApiError

bp = Blueprint("claim", __name__)

_CLAIM_READERS = [
    "ProgramAdministrator", "LeagueAdministrator", "ClaimsExaminer", "MedicalReviewer",
    "GuardianPortal",
]
_MONEY_READERS = ["ProgramAdministrator", "ClaimsExaminer", "GuardianPortal"]
_COORD_READERS = ["ProgramAdministrator", "ClaimsExaminer"]

_OPEN_FOR_COORDINATION = ("PENDING_COORDINATION", "UNDER_ADJUDICATION")


def _claim_context(claim):
    policy = db.get("league_policies", claim["league_policy_id"])
    enrollment = db.get("enrollments", claim["enrollment_id"])
    report = db.get("injury_reports", claim["injury_report_id"])
    return policy, enrollment, report


def _touch_claim(claim_id):
    """Resolve a claim and run the lazy 45-day waiver sweep before anything else."""
    claim = guards.resolve("claim", claim_id)
    services.eob_sweep(claim)
    return claim


# --------------------------------------------------------------------- claims

@bp.get("/claims/<claim_id>")
def get_claim(claim_id):
    auth.require_roles(_CLAIM_READERS)
    claim = _touch_claim(claim_id)
    auth.check_ownership(claim)
    return response.respond_obj(claim)


@bp.get("/claims")
def list_claims():
    auth.require_roles(_CLAIM_READERS)
    limit, offset = v.pagination()
    report_id = v.query_str("injury_report_id")
    policy_id = v.query_str("league_policy_id")
    enrollment_id = v.query_str("enrollment_id")
    adjudication_status = v.query_enum("adjudication_status", C.ADJUDICATION_STATUSES)
    coordination_status = v.query_enum("coordination_status", C.COORDINATION_STATUSES)
    services.eob_sweep_all()
    rows = db.all_rows("claims")
    if report_id is not None:
        rows = [r for r in rows if r["injury_report_id"] == report_id]
    if policy_id is not None:
        rows = [r for r in rows if r["league_policy_id"] == policy_id]
    if enrollment_id is not None:
        rows = [r for r in rows if r["enrollment_id"] == enrollment_id]
    if adjudication_status is not None:
        rows = [r for r in rows if r["adjudication_status"] == adjudication_status]
    if coordination_status is not None:
        rows = [r for r in rows if r["coordination_status"] == coordination_status]
    return response.respond_list(rows, limit, offset)


@bp.post("/claims/<claim_id>/request-eob")
def request_eob(claim_id):
    auth.require_roles(["ClaimsExaminer"])
    claim = _touch_claim(claim_id)
    body = v.json_body()
    v.req_str(body, "note", required=False, default=None)
    if claim["coordination_status"] != "NOT_STARTED":
        raise ApiError("ERR_INVALID_COORDINATION_STATE")
    if claim["adjudication_status"] not in _OPEN_FOR_COORDINATION:
        raise ApiError("ERR_INVALID_CLAIM_STATE")
    policy, enrollment, _report = _claim_context(claim)
    guards.require_policy_in_force(policy, ("ACTIVE", "RUN_OFF"))
    guards.require_not_frozen(policy)
    if not services.other_coverage_on_file(enrollment["participant_id"]):
        raise ApiError("ERR_NO_OTHER_COVERAGE_ON_FILE")
    services.touch(
        claim,
        coordination_status="EOB_REQUESTED",
        eob_requested_at=db.now_iso(),
    )
    return response.respond_obj(claim)


@bp.post("/claims/<claim_id>/confirm-no-other-coverage")
def confirm_no_other_coverage(claim_id):
    auth.require_roles(["ClaimsExaminer"])
    claim = _touch_claim(claim_id)
    body = v.json_body()
    v.req_str(body, "attestation_note")
    if claim["coordination_status"] != "NOT_STARTED":
        raise ApiError("ERR_INVALID_COORDINATION_STATE")
    if claim["adjudication_status"] not in _OPEN_FOR_COORDINATION:
        raise ApiError("ERR_INVALID_CLAIM_STATE")
    policy, enrollment, _report = _claim_context(claim)
    guards.require_policy_in_force(policy, ("ACTIVE", "RUN_OFF"))
    guards.require_not_frozen(policy)
    if services.other_coverage_on_file(enrollment["participant_id"]):
        raise ApiError("ERR_OTHER_COVERAGE_ON_FILE")
    if policy["coverage_basis_election"] != "FULL_EXCESS_PERMITTED":
        raise ApiError("ERR_FULL_EXCESS_NOT_PERMITTED")
    services.touch(
        claim,
        coordination_status="NO_OTHER_COVERAGE_CONFIRMED",
        coordination_basis="FULL_EXCESS",
    )
    services.recompute_claim_determination(claim)
    return response.respond_obj(claim)


@bp.post("/claims/<claim_id>/cat-certification")
def certify_claim(claim_id):
    auth.require_roles(["MedicalReviewer"])
    claim = _touch_claim(claim_id)
    body = v.json_body()
    note = v.req_str(body, "certification_note")
    if claim["adjudication_status"] in ("DENIED", "WITHDRAWN"):
        raise ApiError("ERR_INVALID_CLAIM_STATE")
    if claim["cat_certification_status"] != "NONE":
        raise ApiError("ERR_INVALID_CLAIM_STATE")
    _policy, _enrollment, report = _claim_context(claim)
    if report["severity_tier"] != "CATASTROPHIC":
        raise ApiError("ERR_SEVERITY_NOT_CATASTROPHIC")
    services.touch(
        claim,
        cat_certification_status="CERTIFIED",
        cat_certified_at=db.now_iso(),
        cat_certified_by_user_id=g.user_id,
        cat_certification_note=note,
    )
    services.recompute_claim_determination(claim)
    return response.respond_obj(claim)


@bp.post("/claims/<claim_id>/cat-certification-revocation")
def revoke_certification(claim_id):
    auth.require_roles(["MedicalReviewer"])
    claim = _touch_claim(claim_id)
    body = v.json_body()
    reason = v.req_str(body, "revocation_reason")
    if claim["cat_certification_status"] != "CERTIFIED":
        raise ApiError("ERR_INVALID_CLAIM_STATE")
    _policy, _enrollment, report = _claim_context(claim)
    if report["severity_tier"] != "CATASTROPHIC":
        raise ApiError("ERR_SEVERITY_NOT_CATASTROPHIC")
    services.touch(
        claim,
        cat_certification_status="REVOKED",
        cat_revocation_reason=reason,
    )
    services.recompute_claim_determination(claim)
    return response.respond_obj(claim)


@bp.post("/claims/<claim_id>/adjudicate")
def adjudicate_claim(claim_id):
    auth.require_roles(["ClaimsExaminer"])
    claim = _touch_claim(claim_id)
    body = v.json_body()
    v.req_str(body, "examiner_note")
    if claim["adjudication_status"] != "UNDER_ADJUDICATION":
        raise ApiError("ERR_INVALID_CLAIM_STATE")
    policy, enrollment, _report = _claim_context(claim)
    guards.require_policy_in_force(policy, ("ACTIVE", "RUN_OFF"))
    guards.require_not_frozen(policy)
    reaches_cat_layer = (
        policy["cat_layer_elected"]
        and claim["benefit_before_limit_cents"] > policy["cat_attachment_point_cents"]
    )
    if reaches_cat_layer and claim["cat_certification_status"] != "CERTIFIED":
        raise ApiError("ERR_CAT_CERTIFICATION_REQUIRED")
    if claim["coordination_status"] not in C.SETTLED_COORDINATION_STATUSES:
        raise ApiError("ERR_COORDINATION_INCOMPLETE")
    stamp = db.now_iso()
    if enrollment["status"] == "WITHDRAWN":
        denial_reason = "ENROLLMENT_WITHDRAWN"
    elif claim["benefit_payable_cents"] == 0:
        denial_reason = "NO_BENEFIT_PAYABLE"
    else:
        denial_reason = None
    if denial_reason is not None:
        services.touch(
            claim,
            adjudication_status="DENIED",
            adjudicated_at=stamp,
            adjudicated_by_user_id=g.user_id,
            denial_reason=denial_reason,
        )
        for bill in db.bills_of_claim(claim["id"]):
            if bill["status"] == "REPRICED":
                services.touch(bill, status="DENIED")
        claim["_determination_frozen"] = True
        services.recompute_policy(policy)
        return response.respond_obj(claim)
    services.touch(
        claim,
        adjudication_status="APPROVED",
        adjudicated_at=stamp,
        adjudicated_by_user_id=g.user_id,
    )
    claim["_determination_frozen"] = True
    for bill in db.bills_of_claim(claim["id"]):
        if bill["status"] == "REPRICED":
            services.touch(bill, status="ADJUDICATED")
    services.recompute_policy(policy)
    return response.respond_obj(claim)


@bp.post("/claims/<claim_id>/withdraw")
def withdraw_claim(claim_id):
    auth.require_roles(["LeagueAdministrator"])
    claim = _touch_claim(claim_id)
    auth.check_ownership(claim)
    body = v.json_body()
    reason = v.req_str(body, "withdrawal_reason")
    status = claim["adjudication_status"]
    if status not in ("PENDING_COORDINATION", "UNDER_ADJUDICATION", "APPROVED"):
        raise ApiError("ERR_INVALID_CLAIM_STATE")
    if claim["paid_to_date_cents"] != 0:
        raise ApiError("ERR_PAYMENT_ON_FILE")
    policy, _enrollment, _report = _claim_context(claim)
    services.touch(claim, adjudication_status="WITHDRAWN", withdrawal_reason=reason)
    if status == "UNDER_ADJUDICATION":
        sweep = ("SUBMITTED", "REPRICED")
    elif status == "APPROVED":
        sweep = ("SUBMITTED", "REPRICED", "ADJUDICATED")
    else:
        sweep = ()
    for bill in db.bills_of_claim(claim["id"]):
        if bill["status"] in sweep:
            services.touch(bill, status="VOIDED", void_reason="CLAIM_WITHDRAWN")
    claim["_determination_frozen"] = True
    services.recompute_policy(policy)
    return response.respond_obj(claim)


# -------------------------------------------------------------- provider bills

@bp.post("/provider-bills")
def create_provider_bill():
    auth.require_roles(["ClaimsExaminer"])
    body = v.json_body()
    claim_id = v.req_id(body, "claim_id")
    npi = v.req_npi(body, "provider_npi")
    provider_name = v.req_str(body, "provider_name")
    network_status = v.req_enum(body, "network_status", C.NETWORK_STATUSES)
    service_category = v.req_enum(body, "service_category", C.SERVICE_CATEGORIES)
    service_date = v.req_instant(body, "service_date")
    billed = v.req_int(body, "billed_charge_cents", minimum=1)
    fee_schedule = v.req_int(body, "fee_schedule_amount_cents", minimum=0)
    claim = _touch_claim(claim_id)
    policy, _enrollment, report = _claim_context(claim)
    guards.require_policy_in_force(policy, ("ACTIVE", "RUN_OFF"))
    guards.require_not_frozen(policy)
    injury_datetime = util.parse_datetime(report["injury_datetime"])
    if not guards.instant_in_term(policy, service_date) or (
        util.day_diff(service_date, injury_datetime) < 0
    ):
        raise ApiError("ERR_SERVICE_DATE_OUTSIDE_TERM")
    row = db.new_row("provider_bills", {
        "claim_id": claim["id"],
        "provider_npi": npi,
        "provider_name": provider_name,
        "network_status": network_status,
        "service_category": service_category,
        "service_date": util.format_datetime(service_date),
        "billed_charge_cents": billed,
        "fee_schedule_amount_cents": fee_schedule,
        "negotiated_amount_cents": None,
        "scheduled_cap_cents": None,
        "allowed_amount_cents": 0,
        "balance_billed_cents": None,
        "family_responsibility_cents": None,
        "other_plan_paid_cents": 0,
        "status": "SUBMITTED",
        "repriced_at": None,
        "repriced_by_user_id": None,
        "void_reason": None,
    })
    response.mark_fresh(row)
    return response.respond_obj(row, 201)


@bp.get("/provider-bills/<provider_bill_id>")
def get_provider_bill(provider_bill_id):
    auth.require_roles(_MONEY_READERS)
    row = guards.resolve("provider_bill", provider_bill_id)
    auth.check_ownership(row)
    return response.respond_obj(row)


@bp.get("/provider-bills")
def list_provider_bills():
    auth.require_roles(_MONEY_READERS)
    limit, offset = v.pagination()
    claim_id = v.query_str("claim_id")
    status = v.query_enum("status", C.BILL_STATUSES)
    network_status = v.query_enum("network_status", C.NETWORK_STATUSES)
    service_category = v.query_enum("service_category", C.SERVICE_CATEGORIES)
    rows = db.all_rows("provider_bills")
    if claim_id is not None:
        rows = [r for r in rows if r["claim_id"] == claim_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if network_status is not None:
        rows = [r for r in rows if r["network_status"] == network_status]
    if service_category is not None:
        rows = [r for r in rows if r["service_category"] == service_category]
    return response.respond_list(rows, limit, offset)


@bp.post("/provider-bills/<provider_bill_id>/reprice")
def reprice_provider_bill(provider_bill_id):
    auth.require_roles(["ClaimsExaminer"])
    bill = guards.resolve("provider_bill", provider_bill_id)
    claim = db.get("claims", bill["claim_id"])
    services.eob_sweep(claim)
    v.json_body()
    if bill["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_BILL_STATE")
    if claim["adjudication_status"] not in _OPEN_FOR_COORDINATION:
        raise ApiError("ERR_INVALID_CLAIM_STATE")
    policy, _enrollment, report = _claim_context(claim)
    guards.require_policy_in_force(policy, ("ACTIVE", "RUN_OFF"))
    guards.require_not_frozen(policy)
    sport = guards.sport_of_policy(policy)
    caps = sport["service_category_caps"] or {}
    if bill["service_category"] not in caps:
        raise ApiError("ERR_SERVICE_CATEGORY_NOT_SCHEDULED")
    figures = services.reprice_figures(
        bill, caps[bill["service_category"]], report["severity_tier"]
    )
    services.touch(
        bill,
        status="REPRICED",
        repriced_at=db.now_iso(),
        repriced_by_user_id=g.user_id,
        **figures
    )
    if claim["adjudication_status"] == "PENDING_COORDINATION":
        services.touch(claim, adjudication_status="UNDER_ADJUDICATION")
    services.recompute_claim_balance_totals(claim)
    services.recompute_claim_determination(claim)
    return response.respond_obj(bill)


@bp.post("/provider-bills/<provider_bill_id>/void")
def void_provider_bill(provider_bill_id):
    auth.require_roles(["ClaimsExaminer"])
    bill = guards.resolve("provider_bill", provider_bill_id)
    claim = db.get("claims", bill["claim_id"])
    services.eob_sweep(claim)
    body = v.json_body()
    reason = v.req_str(body, "void_reason")
    status = bill["status"]
    if status not in ("SUBMITTED", "REPRICED", "ADJUDICATED"):
        raise ApiError("ERR_INVALID_BILL_STATE")
    if status in ("REPRICED", "ADJUDICATED"):
        for payment in db.payments_of_claim(claim["id"]):
            if payment["provider_bill_id"] == bill["id"] and payment["status"] == "ISSUED":
                raise ApiError("ERR_PAYMENT_ON_FILE")
    services.touch(bill, status="VOIDED", void_reason=reason)
    services.recompute_claim_balance_totals(claim)
    if status != "ADJUDICATED":
        services.recompute_claim_determination(claim)
    return response.respond_obj(bill)


# --------------------------------------------------------- coordination records

@bp.post("/coordination-records")
def create_coordination_record():
    auth.require_roles(["ClaimsExaminer"])
    body = v.json_body()
    claim_id = v.req_id(body, "claim_id")
    bill_id = v.req_id(body, "provider_bill_id")
    plan_id = v.req_id(body, "family_health_plan_id")
    received = v.req_instant(body, "eob_received_date")
    allowed = v.req_int(body, "other_plan_allowed_cents", minimum=0)
    paid = v.req_int(body, "other_plan_paid_cents", minimum=0)
    patient = v.req_int(body, "patient_responsibility_cents", minimum=0)
    expected_version = v.req_int(body, "expected_claim_version", minimum=1)
    if paid > allowed:
        v.bad("other_plan_paid_cents may not exceed other_plan_allowed_cents")
    claim = _touch_claim(claim_id)
    bill = guards.resolve("provider_bill", bill_id)
    plan = guards.resolve("family_health_plan", plan_id)
    policy, enrollment, _report = _claim_context(claim)
    if bill["claim_id"] != claim["id"]:
        raise ApiError("ERR_SCOPE_MISMATCH")
    if plan["participant_id"] != enrollment["participant_id"]:
        raise ApiError("ERR_SCOPE_MISMATCH")
    if claim["coordination_status"] not in ("EOB_REQUESTED", "EOB_RECEIVED"):
        raise ApiError("ERR_INVALID_COORDINATION_STATE")
    guards.require_policy_in_force(policy, ("ACTIVE", "RUN_OFF"))
    guards.require_not_frozen(policy)
    if expected_version != claim["version"]:
        raise ApiError("ERR_STALE_CLAIM_VERSION")
    if not services.active_coverage_plans(enrollment["participant_id"]):
        raise ApiError("ERR_NO_OTHER_COVERAGE_ON_FILE")
    row = db.new_row("coordination_records", {
        "claim_id": claim["id"],
        "provider_bill_id": bill["id"],
        "family_health_plan_id": plan["id"],
        "eob_received_date": util.format_datetime(received),
        "other_plan_allowed_cents": allowed,
        "other_plan_paid_cents": paid,
        "patient_responsibility_cents": patient,
        "status": "ACTIVE",
        "superseded_by_record_id": None,
    })
    response.mark_fresh(row)
    for prior in db.coordination_records_of_claim(claim["id"]):
        if prior["id"] == row["id"] or prior["status"] != "ACTIVE":
            continue
        if (prior["provider_bill_id"] == bill["id"]
                and prior["family_health_plan_id"] == plan["id"]):
            services.touch(prior, status="SUPERSEDED", superseded_by_record_id=row["id"])
    if claim["coordination_status"] == "EOB_REQUESTED":
        services.touch(
            claim,
            coordination_status="EOB_RECEIVED",
            coordination_basis="EXCESS_OF_OTHER",
        )
    services.recompute_bill_other_plan_paid(bill)
    services.recompute_claim_determination(claim)
    response.mark_dirty(claim)
    return response.respond_obj(row, 201)


@bp.get("/coordination-records/<coordination_record_id>")
def get_coordination_record(coordination_record_id):
    auth.require_roles(_COORD_READERS)
    row = guards.resolve("coordination_record", coordination_record_id)
    return response.respond_obj(row)


@bp.get("/coordination-records")
def list_coordination_records():
    auth.require_roles(_COORD_READERS)
    limit, offset = v.pagination()
    claim_id = v.query_str("claim_id")
    bill_id = v.query_str("provider_bill_id")
    plan_id = v.query_str("family_health_plan_id")
    superseded_by = v.query_str("superseded_by_record_id")
    status = v.query_enum("status", C.COORD_RECORD_STATUSES)
    rows = db.all_rows("coordination_records")
    if claim_id is not None:
        rows = [r for r in rows if r["claim_id"] == claim_id]
    if bill_id is not None:
        rows = [r for r in rows if r["provider_bill_id"] == bill_id]
    if plan_id is not None:
        rows = [r for r in rows if r["family_health_plan_id"] == plan_id]
    if superseded_by is not None:
        rows = [r for r in rows if r["superseded_by_record_id"] == superseded_by]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return response.respond_list(rows, limit, offset)


# ------------------------------------------------------------ benefit payments

@bp.post("/benefit-payments")
def create_benefit_payment():
    auth.require_roles(["ClaimsExaminer"])
    body = v.json_body()
    claim_id = v.req_id(body, "claim_id")
    bill_id = v.req_id(body, "provider_bill_id")
    payee_type = v.req_enum(body, "payee_type", C.PAYEE_TYPES)
    layer = v.req_enum(body, "layer", C.PAYMENT_LAYERS)
    amount = v.req_int(body, "amount_cents", minimum=1)
    claim = _touch_claim(claim_id)
    bill = guards.resolve("provider_bill", bill_id)
    if bill["claim_id"] != claim["id"]:
        raise ApiError("ERR_SCOPE_MISMATCH")
    if claim["adjudication_status"] != "APPROVED":
        raise ApiError("ERR_INVALID_CLAIM_STATE")
    if bill["status"] != "ADJUDICATED":
        raise ApiError("ERR_INVALID_BILL_STATE")
    policy, enrollment, _report = _claim_context(claim)
    guards.require_policy_in_force(policy, ("ACTIVE", "RUN_OFF"))
    guards.require_not_frozen(policy)
    if layer == "BASE":
        if claim["paid_base_cents"] + amount > claim["base_layer_benefit_cents"]:
            raise ApiError("ERR_PAYMENT_EXCEEDS_BENEFIT")
    else:
        if claim["paid_cat_cents"] + amount > claim["cat_layer_benefit_cents"]:
            raise ApiError("ERR_PAYMENT_EXCEEDS_BENEFIT")
    if amount > (bill["allowed_amount_cents"] or 0):
        raise ApiError("ERR_PAYMENT_EXCEEDS_BENEFIT")
    if claim["paid_to_date_cents"] + amount > claim["benefit_payable_cents"]:
        raise ApiError("ERR_PAYMENT_EXCEEDS_BENEFIT")
    if policy["paid_loss_cents"] + amount > policy["aggregate_limit_cents"]:
        raise ApiError("ERR_AGGREGATE_LIMIT_EXCEEDED")
    row = db.new_row("benefit_payments", {
        "claim_id": claim["id"],
        "provider_bill_id": bill["id"],
        "payee_type": payee_type,
        "layer": layer,
        "amount_cents": amount,
        "status": "ISSUED",
        "issued_at": db.now_iso(),
        "issued_by_user_id": g.user_id,
        "void_reason": None,
        "voided_at": None,
    })
    response.mark_fresh(row)
    services.recompute_claim_payment_totals(claim)
    if (claim["adjudication_status"] == "APPROVED"
            and claim["paid_to_date_cents"] >= claim["benefit_payable_cents"]):
        services.touch(claim, adjudication_status="PAID")
    services.recompute_enrollment(enrollment)
    services.recompute_policy(policy)
    return response.respond_obj(row, 201)


@bp.get("/benefit-payments/<benefit_payment_id>")
def get_benefit_payment(benefit_payment_id):
    auth.require_roles(_MONEY_READERS)
    row = guards.resolve("benefit_payment", benefit_payment_id)
    auth.check_ownership(row)
    return response.respond_obj(row)


@bp.get("/benefit-payments")
def list_benefit_payments():
    auth.require_roles(_MONEY_READERS)
    limit, offset = v.pagination()
    claim_id = v.query_str("claim_id")
    bill_id = v.query_str("provider_bill_id")
    layer = v.query_enum("layer", C.PAYMENT_LAYERS)
    payee_type = v.query_enum("payee_type", C.PAYEE_TYPES)
    status = v.query_enum("status", C.PAYMENT_STATUSES)
    rows = db.all_rows("benefit_payments")
    if claim_id is not None:
        rows = [r for r in rows if r["claim_id"] == claim_id]
    if bill_id is not None:
        rows = [r for r in rows if r["provider_bill_id"] == bill_id]
    if layer is not None:
        rows = [r for r in rows if r["layer"] == layer]
    if payee_type is not None:
        rows = [r for r in rows if r["payee_type"] == payee_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return response.respond_list(rows, limit, offset)


@bp.post("/benefit-payments/<benefit_payment_id>/void")
def void_benefit_payment(benefit_payment_id):
    auth.require_roles(["ClaimsExaminer"])
    payment = guards.resolve("benefit_payment", benefit_payment_id)
    claim = db.get("claims", payment["claim_id"])
    services.eob_sweep(claim)
    body = v.json_body()
    reason = v.req_str(body, "void_reason")
    if payment["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_PAYMENT_STATE")
    policy, enrollment, _report = _claim_context(claim)
    services.touch(payment, status="VOIDED", void_reason=reason, voided_at=db.now_iso())
    services.recompute_claim_payment_totals(claim)
    if (claim["adjudication_status"] == "PAID"
            and claim["paid_to_date_cents"] < claim["benefit_payable_cents"]):
        services.touch(claim, adjudication_status="APPROVED")
    services.recompute_enrollment(enrollment)
    services.recompute_policy(policy)
    return response.respond_obj(payment)
