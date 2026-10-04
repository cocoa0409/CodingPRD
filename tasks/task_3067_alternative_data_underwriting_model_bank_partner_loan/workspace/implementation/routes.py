"""Route handlers for all /platform endpoints."""
from flask import Blueprint

from db import store, parse_iso
from errors import (
    invalid_request, not_found, referenced_not_found, model_invalid_state,
    model_locked, model_already_active, model_has_open_applications,
    no_active_model, partner_invalid_state, partner_holds_loans,
    credit_box_invalid_state, credit_box_not_in_window,
    verification_invalid_state, app_invalid_state, loan_invalid_state,
    pool_invalid_state, fairness_gate_blocking, exclusion_review_open,
    segregation_of_duties, payment_invalid, stale_version,
)
from helpers import (
    MODEL_STATUSES, PARTNER_TYPES, PARTNER_STATUSES, CREDIT_BOX_STATUSES,
    EDUCATION_LEVELS, EMPLOYMENT_STATUSES, CHANNELS, APPLICATION_STATUSES,
    VERIFICATION_KINDS, VERIFICATION_STATUSES, REVIEW_TYPES, REVIEW_OUTCOMES,
    LOAN_STATUSES, ALLOCATION_CHANNELS, SERVICING_EVENT_TYPES, POOL_STATUSES,
    new_resource, touch, serialize, list_collection, get_body,
    req_str, req_int, req_number, req_enum, req_list,
)
from middleware import get_auth, require_roles
from response import success_object, success_list
from services import (
    compute_risk_score, compute_dti, compute_approved_amount,
    compute_disparate_impact, add_event, recompute_scheduled_interest,
    create_loan, late_fee, run_allocation,
    partner_originated_this_month_count, partner_funded_balance_cents,
)

bp = Blueprint("platform", __name__, url_prefix="/platform")

READ_ROLES = (
    "PlatformAdmin", "RiskOfficer", "PartnerAdmin", "VerificationOfficer",
    "ServicingAgent", "CollectionsAgent", "Auditor",
)

TERMINAL_APPLICATION_STATUSES = {"APPROVED", "DECLINED", "WITHDRAWN"}


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("PlatformAdmin")
    body = get_body()
    to_iso = body.get("to_iso8601")
    if not isinstance(to_iso, str) or not to_iso:
        raise invalid_request("Missing or invalid field: to_iso8601")
    try:
        dt = parse_iso(to_iso)
    except (TypeError, ValueError):
        raise invalid_request("Missing or invalid field: to_iso8601")
    store.clock = dt
    # First clock advance after funding moves FUNDED loans to CURRENT.
    funded = [l for l in store.loans.values() if l.get("status") == "FUNDED"]
    funded.sort(key=lambda l: (l.get("created_at", ""), l.get("_seq", 0)))
    for loan in funded:
        loan["status"] = "CURRENT"
        add_event(loan, "DELINQUENCY_ADVANCED", 0)
        touch(loan)
    from response import logical_now_iso
    return success_object({"current_utc": logical_now_iso()})


# ---------------------------------------------------------------------------
# ModelVersion
# ---------------------------------------------------------------------------

def _check_variables(variables, require_nonempty=True):
    if not isinstance(variables, list) or (require_nonempty and not variables):
        raise invalid_request("variables must be a non-empty list")
    for v in variables:
        if not isinstance(v, dict):
            raise invalid_request("each variable must be an object")
        name = v.get("name")
        if not isinstance(name, str) or not name:
            raise invalid_request("variable name required")
        weight = v.get("weight")
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or weight < 0:
            raise invalid_request("variable weight must be a non-negative number")
        if "min" not in v or "max" not in v:
            raise invalid_request("variable min/max required")


@bp.post("/model-versions")
def create_model_version():
    user_id, _ = require_roles("RiskOfficer")
    body = get_body()
    model_code = req_str(body, "model_code")
    if "variables" not in body or not isinstance(body["variables"], list):
        raise invalid_request("Missing or invalid field: variables")
    variables = body["variables"]
    calibration_note = body.get("calibration_note")
    if calibration_note is not None and not isinstance(calibration_note, str):
        raise invalid_request("Missing or invalid field: calibration_note")
    score_floor = req_int(body, "score_floor")
    score_ceiling = req_int(body, "score_ceiling")
    rec = new_resource()
    rec.update({
        "model_code": model_code,
        "variables": variables,
        "calibration_note": calibration_note,
        "score_floor": score_floor,
        "score_ceiling": score_ceiling,
        "status": "DRAFT",
        "fairness_report": None,
        "created_by_user_id": user_id,
    })
    store.model_versions[rec["id"]] = rec
    return success_object(serialize(rec), status=201)


@bp.get("/model-versions/<mid>")
def get_model_version(mid):
    require_roles(*READ_ROLES)
    rec = store.model_versions.get(mid)
    if rec is None:
        raise not_found("ModelVersion not found")
    return success_object(serialize(rec))


@bp.get("/model-versions")
def list_model_versions():
    require_roles(*READ_ROLES)
    items, limit, offset, total = list_collection(
        store.model_versions.values(), [("status", "status")]
    )
    return success_list(items, limit, offset, total)


@bp.patch("/model-versions/<mid>")
def patch_model_version(mid):
    require_roles("RiskOfficer")
    rec = store.model_versions.get(mid)
    if rec is None:
        raise not_found("ModelVersion not found")
    body = get_body()
    if rec["status"] != "DRAFT":
        raise model_locked()
    _check_variables(req_list(body, "variables"))
    score_floor = req_int(body, "score_floor")
    score_ceiling = req_int(body, "score_ceiling")
    expected = body.get("expected_model_version")
    if expected is not None and expected != rec["version"]:
        raise stale_version()
    rec["variables"] = body["variables"]
    rec["score_floor"] = score_floor
    rec["score_ceiling"] = score_ceiling
    touch(rec)
    return success_object(serialize(rec))


@bp.post("/model-versions/<mid>/validate")
def validate_model_version(mid):
    user_id, _ = require_roles("RiskOfficer")
    rec = store.model_versions.get(mid)
    if rec is None:
        raise not_found("ModelVersion not found")
    if rec["status"] != "DRAFT":
        raise model_invalid_state()
    if user_id == rec.get("created_by_user_id"):
        raise segregation_of_duties(
            "The validating officer must differ from the model creator"
        )
    _check_variables(rec.get("variables"))
    report = compute_disparate_impact(mid)
    rec["fairness_report"] = report
    rec["status"] = "VALIDATED"
    touch(rec)
    return success_object(serialize(rec))


@bp.post("/model-versions/<mid>/activate")
def activate_model_version(mid):
    require_roles("RiskOfficer")
    rec = store.model_versions.get(mid)
    if rec is None:
        raise not_found("ModelVersion not found")
    if rec["status"] != "VALIDATED":
        raise model_invalid_state()
    if any(m.get("status") == "ACTIVE" for m in store.model_versions.values()):
        raise model_already_active()
    reviews = [r for r in store.fairness_reviews.values() if r.get("model_version_id") == mid]
    if any(r.get("outcome") == "FAILED" for r in reviews):
        raise fairness_gate_blocking("A FAILED fairness review exists")
    if not any(
        r.get("review_type") == "DISPARATE_IMPACT" and r.get("outcome") == "PASSED"
        for r in reviews
    ):
        raise fairness_gate_blocking("No PASSED DISPARATE_IMPACT review exists")
    if any(
        r.get("review_type") == "VARIABLE_EXCLUSION" and r.get("outcome") == "PENDING"
        for r in reviews
    ):
        raise exclusion_review_open()
    rec["status"] = "ACTIVE"
    touch(rec)
    return success_object(serialize(rec))


@bp.post("/model-versions/<mid>/retire")
def retire_model_version(mid):
    require_roles("RiskOfficer")
    rec = store.model_versions.get(mid)
    if rec is None:
        raise not_found("ModelVersion not found")
    if rec["status"] not in ("VALIDATED", "ACTIVE"):
        raise model_invalid_state()
    if rec["status"] == "ACTIVE":
        open_apps = [
            a for a in store.applications.values()
            if a.get("model_version_id") == mid
            and a.get("status") not in TERMINAL_APPLICATION_STATUSES
        ]
        if open_apps:
            raise model_has_open_applications()
    rec["status"] = "RETIRED"
    touch(rec)
    return success_object(serialize(rec))


# ---------------------------------------------------------------------------
# FairnessReview
# ---------------------------------------------------------------------------

@bp.post("/fairness-reviews")
def create_fairness_review():
    require_roles("RiskOfficer")
    body = get_body()
    mv = body.get("model_version_id")
    if not isinstance(mv, str) or not mv or mv not in store.model_versions:
        raise referenced_not_found("model_version_id does not resolve")
    review_type = req_enum(body, "review_type", REVIEW_TYPES)
    details = body.get("details")
    if details is not None and not isinstance(details, str):
        raise invalid_request("Missing or invalid field: details")
    rec = new_resource()
    rec.update({
        "model_version_id": mv,
        "review_type": review_type,
        "outcome": "PENDING",
        "details": details,
    })
    store.fairness_reviews[rec["id"]] = rec
    return success_object(serialize(rec), status=201)


@bp.get("/fairness-reviews")
def list_fairness_reviews():
    require_roles(*READ_ROLES)
    items, limit, offset, total = list_collection(
        store.fairness_reviews.values(),
        [("model_version_id", "model_version_id"),
         ("review_type", "review_type"),
         ("outcome", "outcome")],
    )
    return success_list(items, limit, offset, total)


@bp.get("/fairness-reviews/<rid>")
def get_fairness_review(rid):
    require_roles(*READ_ROLES)
    rec = store.fairness_reviews.get(rid)
    if rec is None:
        raise not_found("FairnessReview not found")
    return success_object(serialize(rec))


@bp.post("/fairness-reviews/<rid>/decide")
def decide_fairness_review(rid):
    require_roles("RiskOfficer")
    rec = store.fairness_reviews.get(rid)
    if rec is None:
        raise not_found("FairnessReview not found")
    body = get_body()
    outcome = req_enum(body, "outcome", {"PASSED", "FAILED"})
    rec["outcome"] = outcome
    if rec["review_type"] == "DISPARATE_IMPACT":
        report = compute_disparate_impact(rec["model_version_id"])
        model = store.model_versions.get(rec["model_version_id"])
        if model is not None and model.get("status") in ("VALIDATED", "ACTIVE"):
            model["fairness_report"] = report
            touch(model)
    touch(rec)
    return success_object(serialize(rec))


# ---------------------------------------------------------------------------
# Attestation
# ---------------------------------------------------------------------------

@bp.post("/model-versions/<mid>/attestations")
def create_attestation(mid):
    user_id, _ = require_roles("RiskOfficer")
    model = store.model_versions.get(mid)
    if model is None:
        raise not_found("ModelVersion not found")
    body = get_body()
    pid = body.get("partner_id")
    if not isinstance(pid, str) or not pid or pid not in store.partners:
        raise referenced_not_found("partner_id does not resolve")
    period_label = req_str(body, "period_label")

    partner = store.partners[pid]
    held_loans = [l for l in store.loans.values() if l.get("holder_partner_id") == pid]
    if held_loans:
        scores = []
        for loan in held_loans:
            app = store.applications.get(loan.get("application_id"), {})
            if app.get("risk_score") is not None:
                scores.append(app["risk_score"])
        if scores:
            from services import rhu
            avg = rhu(sum(scores) / len(scores))
            expected = 500 + 10 * max(0, 550 - avg)
        else:
            expected = 500
    else:
        expected = 500

    charged_off = sum(1 for l in held_loans if l.get("status") == "CHARGED_OFF")
    funded_count = len(held_loans)
    if funded_count == 0:
        actual = 0
    else:
        from services import rhu
        actual = rhu(10000 * charged_off / funded_count)

    rec = new_resource()
    rec.update({
        "model_version_id": mid,
        "partner_id": pid,
        "period_label": period_label,
        "expected_default_rate_bps": expected,
        "actual_default_rate_bps": actual,
        "variance_bps": actual - expected,
        "attested_by_user_id": user_id,
    })
    store.attestations[rec["id"]] = rec
    return success_object(serialize(rec), status=201)


@bp.get("/attestations")
def list_attestations():
    require_roles(*READ_ROLES)
    items, limit, offset, total = list_collection(
        store.attestations.values(),
        [("model_version_id", "model_version_id"), ("partner_id", "partner_id")],
    )
    return success_list(items, limit, offset, total)


@bp.get("/attestations/<aid>")
def get_attestation(aid):
    require_roles(*READ_ROLES)
    rec = store.attestations.get(aid)
    if rec is None:
        raise not_found("Attestation not found")
    return success_object(serialize(rec))


# ---------------------------------------------------------------------------
# Partner
# ---------------------------------------------------------------------------

def serialize_partner(rec):
    out = serialize(rec)
    out["originated_this_month_count"] = partner_originated_this_month_count(rec)
    out["funded_balance_cents"] = partner_funded_balance_cents(rec)
    return out


@bp.post("/partners")
def create_partner():
    require_roles("PartnerAdmin")
    body = get_body()
    legal_name = req_str(body, "legal_name")
    partner_type = req_enum(body, "partner_type", PARTNER_TYPES)
    home_state = req_str(body, "home_state")
    rec = new_resource()
    rec.update({
        "legal_name": legal_name,
        "partner_type": partner_type,
        "home_state": home_state,
        "status": "ONBOARDING",
        "active_credit_box_id": None,
        "activated_by_user_id": None,
    })
    store.partners[rec["id"]] = rec
    return success_object(serialize_partner(rec), status=201)


@bp.get("/partners/<pid>")
def get_partner(pid):
    require_roles(*READ_ROLES)
    rec = store.partners.get(pid)
    if rec is None:
        raise not_found("Partner not found")
    return success_object(serialize_partner(rec))


@bp.get("/partners")
def list_partners():
    require_roles(*READ_ROLES)
    items, limit, offset, total = list_collection(
        store.partners.values(),
        [("partner_type", "partner_type"),
         ("status", "status"),
         ("active_credit_box_id", "active_credit_box_id")],
    )
    items = [
        {**it,
         "originated_this_month_count": partner_originated_this_month_count(store.partners[it["id"]]),
         "funded_balance_cents": partner_funded_balance_cents(store.partners[it["id"]])}
        for it in items
    ]
    return success_list(items, limit, offset, total)


@bp.post("/partners/<pid>/activate")
def activate_partner(pid):
    user_id, _ = require_roles("PartnerAdmin")
    rec = store.partners.get(pid)
    if rec is None:
        raise not_found("Partner not found")
    if rec["status"] not in ("ONBOARDING", "SUSPENDED"):
        raise partner_invalid_state()
    rec["status"] = "ACTIVE"
    rec["activated_by_user_id"] = user_id
    touch(rec)
    return success_object(serialize_partner(rec))


@bp.post("/partners/<pid>/suspend")
def suspend_partner(pid):
    require_roles("PartnerAdmin")
    rec = store.partners.get(pid)
    if rec is None:
        raise not_found("Partner not found")
    if rec["status"] != "ACTIVE":
        raise partner_invalid_state()
    rec["status"] = "SUSPENDED"
    touch(rec)
    return success_object(serialize_partner(rec))


@bp.post("/partners/<pid>/offboard")
def offboard_partner(pid):
    require_roles("PartnerAdmin")
    rec = store.partners.get(pid)
    if rec is None:
        raise not_found("Partner not found")
    if rec["status"] != "ACTIVE":
        raise partner_invalid_state()
    if partner_funded_balance_cents(rec) != 0:
        raise partner_holds_loans()
    rec["status"] = "OFFBOARDED"
    touch(rec)
    for box in store.credit_boxes.values():
        if box.get("partner_id") != pid:
            continue
        if box["status"] == "ACTIVE":
            box["status"] = "SUPERSEDED"
            touch(box)
        elif box["status"] == "DRAFT":
            box["status"] = "RETIRED"
            touch(box)
    if rec.get("active_credit_box_id"):
        box = store.credit_boxes.get(rec["active_credit_box_id"])
        if box is not None and box["status"] != "ACTIVE":
            rec["active_credit_box_id"] = None
            touch(rec)
    for pool in store.securitization_pools.values():
        if pool.get("trust_partner_id") == pid and pool["status"] == "OPEN":
            pool["status"] = "CLOSED"
            touch(pool)
    return success_object(serialize_partner(rec))


# ---------------------------------------------------------------------------
# CreditBox
# ---------------------------------------------------------------------------

@bp.post("/partners/<pid>/credit-boxes")
def create_credit_box(pid):
    require_roles("PartnerAdmin")
    partner = store.partners.get(pid)
    if partner is None:
        raise not_found("Partner not found")
    body = get_body()
    min_score = req_int(body, "min_score")
    max_score = req_int(body, "max_score")
    allowed_states = req_list(body, "allowed_states")
    min_loan = req_int(body, "min_loan_cents")
    max_loan = req_int(body, "max_loan_cents")
    cap = req_int(body, "monthly_volume_cap_count")
    apr = req_number(body, "annual_percentage_rate")
    eff_from = req_str(body, "effective_from")
    eff_to = req_str(body, "effective_to")
    try:
        dt_from = parse_iso(eff_from)
        dt_to = parse_iso(eff_to)
    except (TypeError, ValueError):
        raise invalid_request("effective_from/effective_to must be ISO8601")
    if dt_to <= dt_from:
        raise invalid_request("effective_to must be strictly after effective_from")
    rec = new_resource()
    rec.update({
        "partner_id": pid,
        "min_score": min_score,
        "max_score": max_score,
        "allowed_states": allowed_states,
        "min_loan_cents": min_loan,
        "max_loan_cents": max_loan,
        "monthly_volume_cap_count": cap,
        "annual_percentage_rate": apr,
        "effective_from": eff_from,
        "effective_to": eff_to,
        "status": "DRAFT",
    })
    store.credit_boxes[rec["id"]] = rec
    return success_object(serialize(rec), status=201)


@bp.get("/partners/<pid>/credit-boxes")
def list_credit_boxes(pid):
    require_roles(*READ_ROLES)
    if pid not in store.partners:
        raise not_found("Partner not found")
    boxes = [b for b in store.credit_boxes.values() if b.get("partner_id") == pid]
    items, limit, offset, total = list_collection(boxes, [("status", "status")])
    return success_list(items, limit, offset, total)


@bp.get("/credit-boxes/<bid>")
def get_credit_box(bid):
    require_roles(*READ_ROLES)
    rec = store.credit_boxes.get(bid)
    if rec is None:
        raise not_found("CreditBox not found")
    return success_object(serialize(rec))


@bp.post("/partners/<pid>/credit-boxes/<bid>/activate")
def activate_credit_box(pid, bid):
    require_roles("PartnerAdmin")
    partner = store.partners.get(pid)
    if partner is None:
        raise not_found("Partner not found")
    box = store.credit_boxes.get(bid)
    if box is None or box.get("partner_id") != pid:
        raise not_found("CreditBox not found")
    if box["status"] != "DRAFT":
        raise credit_box_invalid_state()
    if partner["status"] != "ACTIVE":
        raise partner_invalid_state()
    if box["min_score"] > box["max_score"] or box["min_loan_cents"] > box["max_loan_cents"]:
        raise invalid_request("min must not exceed max")
    now = store.clock
    if not (parse_iso(box["effective_from"]) <= now <= parse_iso(box["effective_to"])):
        raise credit_box_not_in_window()
    body = get_body()
    expected = body.get("expected_partner_version")
    if expected is not None and expected != partner["version"]:
        raise stale_version()
    prev_id = partner.get("active_credit_box_id")
    if prev_id:
        prev = store.credit_boxes.get(prev_id)
        if prev is not None and prev["status"] == "ACTIVE":
            prev["status"] = "SUPERSEDED"
            touch(prev)
    box["status"] = "ACTIVE"
    touch(box)
    partner["active_credit_box_id"] = box["id"]
    touch(partner)
    return success_object(serialize(box))


@bp.post("/partners/<pid>/credit-boxes/<bid>/retire")
def retire_credit_box(pid, bid):
    require_roles("PartnerAdmin")
    partner = store.partners.get(pid)
    if partner is None:
        raise not_found("Partner not found")
    box = store.credit_boxes.get(bid)
    if box is None or box.get("partner_id") != pid:
        raise not_found("CreditBox not found")
    if box["status"] != "DRAFT":
        raise credit_box_invalid_state()
    box["status"] = "RETIRED"
    touch(box)
    return success_object(serialize(box))


# ---------------------------------------------------------------------------
# Applicant
# ---------------------------------------------------------------------------

@bp.post("/applicants")
def create_applicant():
    require_roles("PlatformAdmin", "VerificationOfficer")
    body = get_body()
    full_name = req_str(body, "full_name")
    state_code = req_str(body, "state_code")
    annual_income = req_int(body, "annual_income_cents")
    monthly_debt = req_int(body, "monthly_debt_payments_cents")
    education = req_enum(body, "education_level", EDUCATION_LEVELS)
    employment = req_enum(body, "employment_status", EMPLOYMENT_STATUSES)
    months_employed = req_int(body, "months_employed")
    avg_balance = req_int(body, "bank_account_avg_balance_cents")
    nsf = req_int(body, "bank_account_nsf_count_90d")
    net_cashflow = req_int(body, "monthly_net_cashflow_cents")
    bureau = req_int(body, "bureau_score")
    rec = new_resource()
    rec.update({
        "full_name": full_name,
        "state_code": state_code,
        "annual_income_cents": annual_income,
        "monthly_debt_payments_cents": monthly_debt,
        "education_level": education,
        "employment_status": employment,
        "months_employed": months_employed,
        "bank_account_avg_balance_cents": avg_balance,
        "bank_account_nsf_count_90d": nsf,
        "monthly_net_cashflow_cents": net_cashflow,
        "bureau_score": bureau,
    })
    store.applicants[rec["id"]] = rec
    return success_object(serialize(rec), status=201)


@bp.get("/applicants/<aid>")
def get_applicant(aid):
    require_roles(*READ_ROLES)
    rec = store.applicants.get(aid)
    if rec is None:
        raise not_found("Applicant not found")
    return success_object(serialize(rec))


@bp.get("/applicants")
def list_applicants():
    require_roles(*READ_ROLES)
    items, limit, offset, total = list_collection(
        store.applicants.values(), [("state_code", "state_code")]
    )
    return success_list(items, limit, offset, total)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

@bp.post("/applications")
def create_application():
    require_roles("PlatformAdmin")
    body = get_body()
    applicant_id = body.get("applicant_id")
    if not isinstance(applicant_id, str) or applicant_id not in store.applicants:
        raise referenced_not_found("applicant_id does not resolve")
    channel = req_enum(body, "channel", CHANNELS)
    referral_partner_id = body.get("referral_partner_id")
    requested = req_int(body, "requested_amount_cents")
    if channel == "PARTNER_REFERRAL":
        if referral_partner_id is None:
            raise invalid_request("referral_partner_id is required for PARTNER_REFERRAL")
        if not isinstance(referral_partner_id, str) or referral_partner_id not in store.partners:
            raise referenced_not_found("referral_partner_id does not resolve")
    elif channel == "DIRECT":
        if referral_partner_id is not None:
            raise invalid_request("referral_partner_id must not be supplied for DIRECT")

    active_models = [m for m in store.model_versions.values() if m.get("status") == "ACTIVE"]
    if len(active_models) != 1:
        raise no_active_model()
    model = active_models[0]
    applicant = store.applicants[applicant_id]

    score = compute_risk_score(model, applicant)
    dti = compute_dti(applicant)

    rec = new_resource()
    rec.update({
        "applicant_id": applicant_id,
        "channel": channel,
        "referral_partner_id": referral_partner_id if channel == "PARTNER_REFERRAL" else None,
        "requested_amount_cents": requested,
        "model_version_id": model["id"],
        "risk_score": score,
        "approved_amount_cents": None,
        "debt_to_income_pct": dti,
    })
    store.applications[rec["id"]] = rec

    if model["score_floor"] <= score < 300:
        rec["status"] = "DECLINED"
    else:
        rec["status"] = "VERIFICATION_PENDING"
        for kind in ("INCOME", "IDENTITY"):
            v = new_resource()
            v.update({
                "application_id": rec["id"],
                "kind": kind,
                "status": "PENDING",
                "reviewer_id": None,
                "instant_checker_user_id": None,
            })
            store.verifications[v["id"]] = v
    return success_object(serialize(rec), status=201)


@bp.get("/applications/<aid>")
def get_application(aid):
    require_roles(*READ_ROLES)
    rec = store.applications.get(aid)
    if rec is None:
        raise not_found("Application not found")
    return success_object(serialize(rec))


@bp.get("/applications")
def list_applications():
    require_roles(*READ_ROLES)
    items, limit, offset, total = list_collection(
        store.applications.values(),
        [("applicant_id", "applicant_id"),
         ("referral_partner_id", "referral_partner_id"),
         ("model_version_id", "model_version_id"),
         ("status", "status"),
         ("channel", "channel")],
    )
    return success_list(items, limit, offset, total)


@bp.post("/applications/<aid>/withdraw")
def withdraw_application(aid):
    require_roles("PlatformAdmin")
    rec = store.applications.get(aid)
    if rec is None:
        raise not_found("Application not found")
    if rec["status"] not in ("SUBMITTED", "VERIFICATION_PENDING"):
        raise app_invalid_state()
    rec["status"] = "WITHDRAWN"
    touch(rec)
    return success_object(serialize(rec))


@bp.post("/applications/<aid>/allocate")
def allocate_application(aid):
    require_roles("PlatformAdmin")
    rec = store.applications.get(aid)
    if rec is None:
        raise not_found("Application not found")
    if rec["status"] != "UNDERWRITTEN":
        raise app_invalid_state()
    decision = run_allocation(rec)
    return success_object(serialize(decision))


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

@bp.get("/applications/<aid>/verifications")
def list_verifications(aid):
    require_roles(*READ_ROLES)
    if aid not in store.applications:
        raise not_found("Application not found")
    verifs = [v for v in store.verifications.values() if v.get("application_id") == aid]
    items, limit, offset, total = list_collection(
        verifs, [("kind", "kind"), ("status", "status")]
    )
    return success_list(items, limit, offset, total)


def _get_verification_scoped(aid, vid):
    app = store.applications.get(aid)
    if app is None:
        raise not_found("Application not found")
    v = store.verifications.get(vid)
    if v is None or v.get("application_id") != aid:
        raise not_found("Verification not found")
    return app, v


def _bubble_up(app):
    verifs = [v for v in store.verifications.values() if v.get("application_id") == app["id"]]
    unresolved = [
        v for v in verifs
        if v["status"] in ("PENDING", "INSTANT_FAILED", "MANUAL_REVIEW", "MANUAL_FAILED")
    ]
    if not unresolved:
        app["approved_amount_cents"] = compute_approved_amount(app)
        app["status"] = "UNDERWRITTEN"
        touch(app)


@bp.post("/applications/<aid>/verifications/<vid>/instant-check")
def instant_check(aid, vid):
    user_id, _ = require_roles("VerificationOfficer")
    app, v = _get_verification_scoped(aid, vid)
    if app["status"] != "VERIFICATION_PENDING":
        raise app_invalid_state()
    if v["status"] != "PENDING":
        raise verification_invalid_state()
    applicant = store.applicants.get(app["applicant_id"], {})
    if v["kind"] == "INCOME":
        passed = (
            applicant.get("bank_account_nsf_count_90d", 0) < 3
            and applicant.get("monthly_net_cashflow_cents", 0) > 0
        )
    else:  # IDENTITY
        passed = (
            applicant.get("months_employed", 0) >= 3
            and applicant.get("bureau_score", 0) >= 500
        )
    v["status"] = "INSTANT_PASSED" if passed else "INSTANT_FAILED"
    v["instant_checker_user_id"] = user_id
    touch(v)
    if passed:
        others = [x for x in store.verifications.values()
                  if x.get("application_id") == aid and x["id"] != vid]
        if all(x["status"] == "INSTANT_PASSED" for x in others):
            _bubble_up(app)
    else:
        app["status"] = "DOCS_REQUIRED"
        touch(app)
    return success_object(serialize(v))


@bp.post("/applications/<aid>/verifications/<vid>/manual-decision")
def manual_decision(aid, vid):
    user_id, _ = require_roles("VerificationOfficer")
    app, v = _get_verification_scoped(aid, vid)
    if app["status"] != "DOCS_REQUIRED":
        raise app_invalid_state()
    if v["status"] not in ("INSTANT_FAILED", "MANUAL_REVIEW"):
        raise verification_invalid_state()
    if user_id == v.get("instant_checker_user_id"):
        raise segregation_of_duties(
            "Manual decider must differ from the instant checker"
        )
    body = get_body()
    raw = body.get("outcome")
    if isinstance(raw, str):
        normalized = raw.strip().upper()
    else:
        normalized = None
    if normalized in ("PASS", "PASSED", "MANUAL_PASSED"):
        outcome = "PASS"
    elif normalized in ("FAIL", "FAILED", "MANUAL_FAILED"):
        outcome = "FAIL"
    else:
        raise invalid_request("outcome must be PASS or FAIL")
    v["status"] = "MANUAL_PASSED" if outcome == "PASS" else "MANUAL_FAILED"
    v["reviewer_id"] = user_id
    touch(v)
    if outcome == "PASS":
        _bubble_up(app)
    else:
        app["status"] = "DECLINED"
        touch(app)
    return success_object(serialize(v))


# ---------------------------------------------------------------------------
# Loan
# ---------------------------------------------------------------------------

@bp.get("/loans/<lid>")
def get_loan(lid):
    require_roles(*READ_ROLES)
    rec = store.loans.get(lid)
    if rec is None:
        raise not_found("Loan not found")
    return success_object(serialize(rec))


@bp.get("/loans")
def list_loans():
    require_roles(*READ_ROLES)
    items, limit, offset, total = list_collection(
        store.loans.values(),
        [("holder_partner_id", "holder_partner_id"),
         ("application_id", "application_id"),
         ("status", "status"),
         ("allocation_channel", "allocation_channel")],
    )
    return success_list(items, limit, offset, total)


@bp.post("/loans/<lid>/payments")
def post_payment(lid):
    require_roles("ServicingAgent")
    loan = store.loans.get(lid)
    if loan is None:
        raise not_found("Loan not found")
    body = get_body()
    amount = body.get("amount_cents")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise payment_invalid("Payment amount must be a positive integer")
    if loan["status"] not in ("CURRENT", "DELINQUENT"):
        raise payment_invalid("Loan not in a payable state")
    expected = body.get("expected_loan_version")
    if expected is not None and expected != loan["version"]:
        raise stale_version()

    remaining = amount
    fee_payment = min(remaining, loan["late_fee_accrued_cents"])
    loan["late_fee_accrued_cents"] -= fee_payment
    remaining -= fee_payment
    interest_payment = min(remaining, loan["scheduled_interest_cents"])
    loan["scheduled_interest_cents"] -= interest_payment
    remaining -= interest_payment
    principal_payment = min(remaining, loan["outstanding_principal_cents"])
    loan["outstanding_principal_cents"] -= principal_payment
    remaining -= principal_payment
    # Any excess over all buckets is discarded (balance already zero).

    if loan["outstanding_principal_cents"] == 0:
        loan["days_delinquent"] = 0
        loan["late_fee_accrued_cents"] = 0
        loan["status"] = "PAID_OFF"
        add_event(loan, "PAYMENT_APPLIED", amount)
        add_event(loan, "PAYOFF_RECORDED", amount)
    else:
        # A delinquent loan returns to CURRENT only when the payment covered
        # the accrued late fees in full and the scheduled interest in full
        # for every elapsed unpaid period (PRD 3.10). The due interest for the
        # elapsed periods is the per-period interest (computed at funding on
        # the then-outstanding principal) times the number of elapsed unpaid
        # periods; the per-payment split is never re-rounded after the fact,
        # so no interest recomputation happens here.
        if loan["status"] == "DELINQUENT":
            elapsed_periods = loan["days_delinquent"] // 30
            interest_due = (
                loan.get("_interest_per_period_cents", 0) * elapsed_periods
            )
            if (
                loan["late_fee_accrued_cents"] == 0
                and interest_payment >= interest_due
            ):
                loan["status"] = "CURRENT"
                loan["days_delinquent"] = 0
                loan["late_fee_accrued_cents"] = 0
        add_event(loan, "PAYMENT_APPLIED", amount)
    touch(loan)
    return success_object(serialize(loan))


@bp.post("/loans/<lid>/advance-servicing")
def advance_servicing(lid):
    require_roles("ServicingAgent")
    loan = store.loans.get(lid)
    if loan is None:
        raise not_found("Loan not found")
    status = loan["status"]
    days = loan["days_delinquent"]
    if status == "CURRENT":
        loan["days_delinquent"] = 30
        fee = late_fee(loan)
        loan["late_fee_accrued_cents"] += fee
        loan["status"] = "DELINQUENT"
        add_event(loan, "LATE_FEE_ASSESSED", fee)
        add_event(loan, "DELINQUENCY_ADVANCED", 0)
    elif status == "DELINQUENT" and days == 90:
        loan["days_delinquent"] = 120
        loan["status"] = "DEFAULTED"
        add_event(loan, "DEFAULT_DECLARED", 0)
    elif status == "DELINQUENT" and days < 120:
        loan["days_delinquent"] = days + 30
        fee = late_fee(loan)
        loan["late_fee_accrued_cents"] += fee
        add_event(loan, "LATE_FEE_ASSESSED", fee)
        add_event(loan, "DELINQUENCY_ADVANCED", 0)
    else:
        raise loan_invalid_state()
    touch(loan)
    return success_object(serialize(loan))


@bp.post("/loans/<lid>/charge-off")
def charge_off(lid):
    user_id, _ = require_roles("CollectionsAgent")
    loan = store.loans.get(lid)
    if loan is None:
        raise not_found("Loan not found")
    if loan["status"] != "DEFAULTED":
        raise loan_invalid_state()
    holder = store.partners.get(loan.get("holder_partner_id") or "")
    if holder is not None and user_id == holder.get("activated_by_user_id"):
        raise segregation_of_duties(
            "Charge-off agent must differ from the partner activator"
        )
    amount = loan["outstanding_principal_cents"] + loan["late_fee_accrued_cents"]
    loan["status"] = "CHARGED_OFF"
    add_event(loan, "CHARGE_OFF_REPORTED", amount)
    if loan["allocation_channel"] == "SECURITIZATION":
        for pool in store.securitization_pools.values():
            if pool.get("trust_partner_id") == loan["holder_partner_id"] and pool["status"] == "OPEN":
                pool["allocated_principal_cents"] -= loan["principal_cents"]
                touch(pool)
                break
    touch(loan)
    return success_object(serialize(loan))


# ---------------------------------------------------------------------------
# ServicingEvent
# ---------------------------------------------------------------------------

@bp.get("/loans/<lid>/servicing-events")
def list_servicing_events(lid):
    require_roles(*READ_ROLES)
    if lid not in store.loans:
        raise not_found("Loan not found")
    events = [e for e in store.servicing_events.values() if e.get("loan_id") == lid]
    events.sort(key=lambda e: (e.get("occurred_at", ""), e.get("_seq", 0)))
    items, limit, offset, total = list_collection(events, [("event_type", "event_type")])
    return success_list(items, limit, offset, total)


# ---------------------------------------------------------------------------
# SecuritizationPool
# ---------------------------------------------------------------------------

@bp.post("/securitization-pools")
def create_pool():
    require_roles("PartnerAdmin")
    body = get_body()
    trust_id = body.get("trust_partner_id")
    if not isinstance(trust_id, str) or trust_id not in store.partners:
        raise referenced_not_found("trust_partner_id does not resolve")
    pool_label = req_str(body, "pool_label")
    target = req_int(body, "target_principal_cents")
    max_single = req_int(body, "max_single_loan_cents")
    rec = new_resource()
    rec.update({
        "trust_partner_id": trust_id,
        "pool_label": pool_label,
        "target_principal_cents": target,
        "allocated_principal_cents": 0,
        "max_single_loan_cents": max_single,
        "status": "OPEN",
    })
    store.securitization_pools[rec["id"]] = rec
    return success_object(serialize(rec), status=201)


@bp.get("/securitization-pools/<pid>")
def get_pool(pid):
    require_roles(*READ_ROLES)
    rec = store.securitization_pools.get(pid)
    if rec is None:
        raise not_found("SecuritizationPool not found")
    return success_object(serialize(rec))


@bp.get("/securitization-pools")
def list_pools():
    require_roles(*READ_ROLES)
    items, limit, offset, total = list_collection(
        store.securitization_pools.values(),
        [("trust_partner_id", "trust_partner_id"), ("status", "status")],
    )
    return success_list(items, limit, offset, total)


@bp.post("/securitization-pools/<pid>/close")
def close_pool(pid):
    require_roles("PartnerAdmin")
    rec = store.securitization_pools.get(pid)
    if rec is None:
        raise not_found("SecuritizationPool not found")
    if rec["status"] != "OPEN":
        raise pool_invalid_state()
    rec["status"] = "CLOSED"
    touch(rec)
    return success_object(serialize(rec))


# ---------------------------------------------------------------------------
# AllocationDecision
# ---------------------------------------------------------------------------

@bp.get("/allocation-decisions")
def list_allocation_decisions():
    require_roles(*READ_ROLES)
    items, limit, offset, total = list_collection(
        store.allocation_decisions.values(),
        [("application_id", "application_id"),
         ("channel", "channel"),
         ("chosen_partner_id", "chosen_partner_id")],
    )
    return success_list(items, limit, offset, total)


@bp.get("/allocation-decisions/<did>")
def get_allocation_decision(did):
    require_roles(*READ_ROLES)
    rec = store.allocation_decisions.get(did)
    if rec is None:
        raise not_found("AllocationDecision not found")
    return success_object(serialize(rec))
