"""Applicants, risk-management services, exposure assessments and binding."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import calc
import serialize
import store
from errors import ApiError
from envelope import created_response, list_response, object_response
from routes.common import (ALL_STAFF, by_created, own_applicant_filter,
                           scope_applicant, sorted_by)
from services import ledger
from validate import (ENUMS, F, auth, enum_filter, interval_order, no_body,
                      pagination, parse_body, str_filter)

bp = Blueprint("underwriting", __name__)

UW_READERS = ("PlatformAdmin", "Underwriter", "UnderwritingManager",
              "PolicyholderContact")
POLICY_READERS = ("PlatformAdmin", "Underwriter", "UnderwritingManager",
                  "ClaimsAdjuster", "ClaimsManager", "PolicyholderContact")


def _resolve_codes(primary_code, entries):
    """Body natural keys resolve before any semantic check (PRD 2.8 item 5)."""
    if primary_code is not None:
        if store.jurisdiction_by_code(primary_code) is None:
            raise ApiError("ERR_JURISDICTION_NOT_FOUND",
                           "Jurisdiction code '%s' is not registered."
                           % primary_code)
    if entries is not None:
        for entry in entries:
            if store.jurisdiction_by_code(entry["code"]) is None:
                raise ApiError("ERR_JURISDICTION_NOT_FOUND",
                               "Jurisdiction code '%s' is not registered."
                               % entry["code"])


def _check_allocation(total_headcount, entries, primary_code):
    if sum(e["headcount"] for e in entries) != total_headcount:
        raise ApiError("ERR_HEADCOUNT_ALLOCATION_MISMATCH",
                       "Jurisdiction headcounts must sum to total_headcount.")
    if primary_code not in [e["code"] for e in entries]:
        raise ApiError("ERR_HEADCOUNT_ALLOCATION_MISMATCH",
                       "primary_jurisdiction_code must appear in "
                       "jurisdiction_headcounts.")


# --------------------------------------------------------------------------
# applicants
# --------------------------------------------------------------------------
@bp.get("/epli/applicants/<applicant_id>")
def get_applicant(applicant_id):
    user_id, role = auth(UW_READERS)
    row = store.find(store.APPLICANTS, applicant_id, "ERR_APPLICANT_NOT_FOUND")
    scope_applicant(role, user_id, row["id"])
    return object_response(serialize.applicant(row))


@bp.post("/epli/applicants")
def create_applicant():
    auth(("Underwriter",))
    body = parse_body([
        F("legal_name", "str", required=True),
        F("total_headcount", "int", required=True, min=1),
        F("prior_year_separations", "int", required=True, min=0),
        F("jurisdiction_headcounts", "jh", required=True),
        F("primary_jurisdiction_code", "id", required=True),
        F("separations_since_assessment", "int", default=0, min=0),
    ])
    _resolve_codes(body["primary_jurisdiction_code"],
                   body["jurisdiction_headcounts"])
    _check_allocation(body["total_headcount"], body["jurisdiction_headcounts"],
                      body["primary_jurisdiction_code"])
    row = store.new_row({
        "legal_name": body["legal_name"],
        "total_headcount": body["total_headcount"],
        "prior_year_separations": body["prior_year_separations"],
        "separations_since_assessment": body["separations_since_assessment"],
        "jurisdiction_headcounts": body["jurisdiction_headcounts"],
        "primary_jurisdiction_code": body["primary_jurisdiction_code"],
    })
    store.APPLICANTS[row["id"]] = row
    ledger.recompute_applicant(row, bump=False)
    return created_response(serialize.applicant(row))


@bp.patch("/epli/applicants/<applicant_id>")
def revise_applicant(applicant_id):
    auth(("Underwriter",))
    body = parse_body([
        F("total_headcount", "int", min=1),
        F("prior_year_separations", "int", min=0),
        F("separations_since_assessment", "int", min=0),
        F("jurisdiction_headcounts", "jh"),
        F("primary_jurisdiction_code", "id"),
    ])
    row = store.find(store.APPLICANTS, applicant_id, "ERR_APPLICANT_NOT_FOUND")
    present = body["_present"]
    _resolve_codes(body["primary_jurisdiction_code"] if
                   "primary_jurisdiction_code" in present else None,
                   body["jurisdiction_headcounts"] if
                   "jurisdiction_headcounts" in present else None)
    total = (body["total_headcount"] if "total_headcount" in present
             else row["total_headcount"])
    entries = (body["jurisdiction_headcounts"]
               if "jurisdiction_headcounts" in present
               else row["jurisdiction_headcounts"])
    primary = (body["primary_jurisdiction_code"]
               if "primary_jurisdiction_code" in present
               else row["primary_jurisdiction_code"])
    if present & {"total_headcount", "jurisdiction_headcounts",
                  "primary_jurisdiction_code"}:
        _check_allocation(total, entries, primary)
    row["total_headcount"] = total
    row["jurisdiction_headcounts"] = entries
    row["primary_jurisdiction_code"] = primary
    if "prior_year_separations" in present:
        row["prior_year_separations"] = body["prior_year_separations"]
    if "separations_since_assessment" in present:
        row["separations_since_assessment"] = body["separations_since_assessment"]
    ledger.recompute_applicant(row)
    if present & {"total_headcount", "prior_year_separations",
                  "jurisdiction_headcounts", "primary_jurisdiction_code"}:
        ledger.stale_priced_assessments(row["id"])
    return object_response(serialize.applicant(row))


# --------------------------------------------------------------------------
# risk-management services
# --------------------------------------------------------------------------
@bp.get("/epli/risk-management-services/<service_id>")
def get_service(service_id):
    user_id, role = auth(UW_READERS)
    row = store.find(store.SERVICES, service_id, "ERR_SERVICE_NOT_FOUND")
    scope_applicant(role, user_id, row["applicant_id"])
    return object_response(serialize.service(row))


@bp.get("/epli/risk-management-services")
def list_services():
    user_id, role = auth(UW_READERS)
    limit, offset = pagination()
    applicant_id = str_filter("applicant_id")
    service_type = enum_filter("service_type", "service_type")
    status = enum_filter("status", "service_status")
    rows = list(store.SERVICES.values())
    if applicant_id is not None:
        rows = [r for r in rows if r["applicant_id"] == applicant_id]
    if service_type is not None:
        rows = [r for r in rows if r["service_type"] == service_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = own_applicant_filter(role, user_id, rows,
                                lambda r: r["applicant_id"])
    return list_response([serialize.service(r) for r in by_created(rows)],
                         limit, offset)


@bp.post("/epli/applicants/<applicant_id>/risk-management-services")
def create_service(applicant_id):
    auth(("Underwriter",))
    body = parse_body([
        F("service_type", "enum", required=True, values=ENUMS["service_type"]),
        F("credit_pct", "num", required=True, dp=2, min=0, max=0.15),
        F("effective_from", "instant", required=True),
        F("effective_to", "instant", required=True),
    ])
    interval_order(body["effective_from"], body["effective_to"],
                   "effective_from", "effective_to")
    applicant = store.find(store.APPLICANTS, applicant_id,
                           "ERR_APPLICANT_NOT_FOUND")
    buffer_delta = timedelta(days=calc.SERVICE_GAP_BUFFER_DAYS)
    for existing in store.services_of_applicant(applicant["id"]):
        if existing["status"] == "REVOKED":
            continue
        if existing["service_type"] != body["service_type"]:
            continue
        if (body["effective_from"] < existing["effective_to"] + buffer_delta
                and existing["effective_from"] < body["effective_to"]):
            raise ApiError("ERR_SERVICE_WINDOW_CONFLICT",
                           "This window conflicts with an existing %s service."
                           % body["service_type"])
    row = store.new_row({
        "applicant_id": applicant["id"],
        "service_type": body["service_type"],
        "credit_pct": body["credit_pct"],
        "effective_from": body["effective_from"],
        "effective_to": body["effective_to"],
        "completed_at": None,
        "revocation_reason": None,
        "status": "PENDING",
    })
    store.SERVICES[row["id"]] = row
    return created_response(serialize.service(row))


@bp.post("/epli/risk-management-services/<service_id>/complete")
def complete_service(service_id):
    auth(("Underwriter",))
    no_body()
    row = store.find(store.SERVICES, service_id, "ERR_SERVICE_NOT_FOUND")
    now = store.clock_now()
    if (row["status"] != "PENDING" or now < row["effective_from"]
            or now >= row["effective_to"]):
        raise ApiError("ERR_SERVICE_NOT_COMPLETABLE",
                       "The service must be PENDING with the logical clock "
                       "inside its window.")
    row["status"] = "ACTIVE"
    row["completed_at"] = now
    store.touch(row)
    ledger.service_change_cascade(row)
    return object_response(serialize.service(row))


@bp.post("/epli/risk-management-services/<service_id>/revoke")
def revoke_service(service_id):
    auth(("Underwriter",))
    body = parse_body([F("revocation_reason", "str", required=True)])
    row = store.find(store.SERVICES, service_id, "ERR_SERVICE_NOT_FOUND")
    if row["status"] not in ("PENDING", "ACTIVE"):
        raise ApiError("ERR_SERVICE_NOT_REVOCABLE",
                       "Only a PENDING or ACTIVE service may be revoked.")
    row["status"] = "REVOKED"
    row["revocation_reason"] = body["revocation_reason"]
    store.touch(row)
    ledger.service_change_cascade(row)
    return object_response(serialize.service(row))


# --------------------------------------------------------------------------
# exposure assessments
# --------------------------------------------------------------------------
@bp.get("/epli/exposure-assessments/<assessment_id>")
def get_assessment(assessment_id):
    user_id, role = auth(UW_READERS)
    row = store.find(store.ASSESSMENTS, assessment_id,
                     "ERR_ASSESSMENT_NOT_FOUND")
    scope_applicant(role, user_id, row["applicant_id"])
    return object_response(serialize.assessment(row))


@bp.get("/epli/exposure-assessments")
def list_assessments():
    user_id, role = auth(UW_READERS)
    limit, offset = pagination()
    applicant_id = str_filter("applicant_id")
    rate_plan_id = str_filter("rate_plan_id")
    status = enum_filter("status", "assessment_status")
    rows = list(store.ASSESSMENTS.values())
    if applicant_id is not None:
        rows = [r for r in rows if r["applicant_id"] == applicant_id]
    if rate_plan_id is not None:
        rows = [r for r in rows if r["rate_plan_id"] == rate_plan_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = own_applicant_filter(role, user_id, rows,
                                lambda r: r["applicant_id"])
    return list_response([serialize.assessment(r) for r in by_created(rows)],
                         limit, offset)


SUPERSEDABLE = ("PRICED", "REFERRED", "APPROVED")


@bp.post("/epli/exposure-assessments")
def create_assessment():
    auth(("Underwriter",))
    body = parse_body([
        F("applicant_id", "id", required=True),
        F("rate_plan_id", "id", required=True),
        F("requested_aggregate_limit_cents", "int", required=True,
          min=1000000),
        F("requested_retention_cents", "int", required=True, min=0),
        F("expected_applicant_version", "int", required=True),
        F("third_party_coverage_requested", "bool", default=False),
    ])
    applicant = store.find(store.APPLICANTS, body["applicant_id"],
                           "ERR_APPLICANT_NOT_FOUND")
    plan = store.find(store.RATE_PLANS, body["rate_plan_id"],
                      "ERR_RATE_PLAN_NOT_FOUND")
    if body["expected_applicant_version"] != applicant["version"]:
        raise ApiError("ERR_STALE_APPLICANT_VERSION",
                       "The applicant has been modified since it was read.")
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_RATE_PLAN_NOT_ACTIVE",
                       "Only an ACTIVE rate plan may be referenced.")
    row = store.new_row({
        "applicant_id": applicant["id"],
        "rate_plan_id": plan["id"],
        "requested_aggregate_limit_cents":
            body["requested_aggregate_limit_cents"],
        "requested_retention_cents": body["requested_retention_cents"],
        "third_party_coverage_requested":
            body["third_party_coverage_requested"],
        "priced_by_user_id": None,
        "approved_by_user_id": None,
        "rejection_reason": None,
        "exposure_score_snapshot": None,
        "turnover_pct_snapshot": None,
        "base_premium_cents": None,
        "turnover_load_cents": None,
        "hazard_load_cents": None,
        "limit_load_cents": None,
        "retention_credit_cents": None,
        "risk_mgmt_credit_cents": None,
        "indicated_premium_cents": None,
        "credit_basis_stale": False,
        "status": "DRAFT",
    })
    for existing in sorted(store.assessments_of_applicant(applicant["id"]),
                           key=store.sort_key_created):
        if existing["status"] in SUPERSEDABLE:
            existing["status"] = "SUPERSEDED"
            store.touch(existing)
    store.ASSESSMENTS[row["id"]] = row
    store.touch(applicant)
    return created_response(serialize.assessment(row))


@bp.post("/epli/exposure-assessments/<assessment_id>/price")
def price_assessment(assessment_id):
    user_id, _role = auth(("Underwriter",))
    no_body()
    row = store.find(store.ASSESSMENTS, assessment_id,
                     "ERR_ASSESSMENT_NOT_FOUND")
    if row["status"] not in ("DRAFT", "REFERRED"):
        raise ApiError("ERR_ASSESSMENT_NOT_PRICEABLE",
                       "Only a DRAFT or REFERRED assessment may be priced.")
    plan = store.RATE_PLANS[row["rate_plan_id"]]
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_RATE_PLAN_NOT_ACTIVE",
                       "The assessment's rate plan is no longer ACTIVE.")
    applicant = store.APPLICANTS[row["applicant_id"]]
    ledger.recompute_applicant(applicant, bump=False)
    components = calc.indicated_premium(
        plan, applicant, row["requested_aggregate_limit_cents"],
        row["requested_retention_cents"], applicant["turnover_pct"],
        applicant["risk_credit_pct"])
    row["exposure_score_snapshot"] = applicant["exposure_score"]
    row["turnover_pct_snapshot"] = applicant["turnover_pct"]
    for field in ("base_premium_cents", "turnover_load_cents",
                  "hazard_load_cents", "limit_load_cents",
                  "retention_credit_cents", "risk_mgmt_credit_cents",
                  "indicated_premium_cents"):
        row[field] = components[field]
    row["priced_by_user_id"] = user_id
    row["credit_basis_stale"] = False
    row["status"] = ("REFERRED"
                     if applicant["exposure_score"]
                     >= calc.REFERRAL_SCORE_THRESHOLD else "PRICED")
    store.touch(row)
    return object_response(serialize.assessment(row))


@bp.post("/epli/exposure-assessments/<assessment_id>/approve")
def approve_assessment(assessment_id):
    user_id, _role = auth(("UnderwritingManager",))
    no_body()
    row = store.find(store.ASSESSMENTS, assessment_id,
                     "ERR_ASSESSMENT_NOT_FOUND")
    if row["status"] not in ("PRICED", "REFERRED"):
        raise ApiError("ERR_ASSESSMENT_NOT_DECIDABLE",
                       "Only a PRICED or REFERRED assessment may be decided.")
    if user_id == row["priced_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The approver must differ from the pricing user.")
    if row["credit_basis_stale"]:
        raise ApiError("ERR_CREDIT_BASIS_STALE",
                       "The credit basis is stale; re-price before release.")
    row["approved_by_user_id"] = user_id
    row["status"] = "APPROVED"
    store.touch(row)
    return object_response(serialize.assessment(row))


@bp.post("/epli/exposure-assessments/<assessment_id>/reject")
def reject_assessment(assessment_id):
    auth(("UnderwritingManager",))
    body = parse_body([F("rejection_reason", "str", required=True)])
    row = store.find(store.ASSESSMENTS, assessment_id,
                     "ERR_ASSESSMENT_NOT_FOUND")
    if row["status"] not in ("PRICED", "REFERRED"):
        raise ApiError("ERR_ASSESSMENT_NOT_DECIDABLE",
                       "Only a PRICED or REFERRED assessment may be decided.")
    row["rejection_reason"] = body["rejection_reason"]
    row["status"] = "REJECTED"
    store.touch(row)
    return object_response(serialize.assessment(row))


# --------------------------------------------------------------------------
# policies
# --------------------------------------------------------------------------
@bp.get("/epli/policies/<policy_id>")
def get_policy(policy_id):
    user_id, role = auth(POLICY_READERS)
    row = store.find(store.POLICIES, policy_id, "ERR_POLICY_NOT_FOUND")
    scope_applicant(role, user_id, row["applicant_id"])
    return object_response(serialize.policy(row))


@bp.get("/epli/policies")
def list_policies():
    user_id, role = auth(POLICY_READERS)
    limit, offset = pagination()
    applicant_id = str_filter("applicant_id")
    assessment_id = str_filter("exposure_assessment_id")
    status = enum_filter("status", "policy_status")
    posture = enum_filter("limit_posture", "limit_posture")
    rows = list(store.POLICIES.values())
    if applicant_id is not None:
        rows = [r for r in rows if r["applicant_id"] == applicant_id]
    if assessment_id is not None:
        rows = [r for r in rows
                if r["exposure_assessment_id"] == assessment_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if posture is not None:
        rows = [r for r in rows
                if ledger.policy_limit_posture(r) == posture]
    rows = own_applicant_filter(role, user_id, rows,
                                lambda r: r["applicant_id"])
    rows = sorted_by(rows, [lambda r: r["effective_from"],
                            lambda r: r["created_at"]])
    return list_response([serialize.policy(r) for r in rows], limit, offset)


@bp.get("/epli/policies/<policy_id>/limit-ledger")
def get_limit_ledger(policy_id):
    auth(ALL_STAFF)
    row = store.find(store.POLICIES, policy_id, "ERR_POLICY_NOT_FOUND")
    return object_response(ledger.limit_ledger(row))


def _bound_audit(plan, applicant, assessment, effective_from):
    """The bound-audit premium variant of PRD 3.3."""
    separations = (applicant["prior_year_separations"]
                   + applicant["separations_since_assessment"])
    turnover_basis = calc.turnover_pct(separations,
                                       applicant["total_headcount"])
    eligible = [s for s in store.services_of_applicant(applicant["id"])
                if s["status"] == "ACTIVE" and s["completed_at"] is not None
                and s["completed_at"] <= effective_from]
    credit_basis = calc.risk_credit_pct(eligible)
    return calc.indicated_premium(
        plan, applicant, assessment["requested_aggregate_limit_cents"],
        assessment["requested_retention_cents"], turnover_basis, credit_basis)


@bp.post("/epli/policies")
def bind_policy():
    auth(("Underwriter",))
    body = parse_body([
        F("exposure_assessment_id", "id", required=True),
        F("effective_from", "instant", required=True),
        F("effective_to", "instant", required=True),
    ])
    interval_order(body["effective_from"], body["effective_to"],
                   "effective_from", "effective_to")
    assessment = store.find(store.ASSESSMENTS, body["exposure_assessment_id"],
                            "ERR_ASSESSMENT_NOT_FOUND")
    if assessment["status"] != "APPROVED":
        raise ApiError("ERR_ASSESSMENT_NOT_DECIDABLE",
                       "Only an APPROVED assessment may be bound.")
    applicant = store.APPLICANTS[assessment["applicant_id"]]
    for existing in store.POLICIES.values():
        if existing["applicant_id"] != applicant["id"]:
            continue
        if existing["status"] == "EXPIRED":
            continue
        if (body["effective_from"] < existing["effective_to"]
                and existing["effective_from"] < body["effective_to"]):
            raise ApiError("ERR_POLICY_PERIOD_OVERLAP",
                           "This period overlaps an existing policy period.")
    plan = store.RATE_PLANS[assessment["rate_plan_id"]]
    limit_cents = assessment["requested_aggregate_limit_cents"]
    audit = _bound_audit(plan, applicant, assessment, body["effective_from"])
    now = store.clock_now()
    active = (body["effective_from"] <= now < body["effective_to"])
    row = store.new_row({
        "applicant_id": applicant["id"],
        "exposure_assessment_id": assessment["id"],
        "effective_from": body["effective_from"],
        "effective_to": body["effective_to"],
        "aggregate_limit_cents": limit_cents,
        "per_claim_retention_cents": assessment["requested_retention_cents"],
        "third_party_coverage_elected":
            assessment["third_party_coverage_requested"],
        "wage_hour_sublimit_cents": calc.round_cents(
            Decimal(limit_cents) * plan["wage_hour_sublimit_pct"]),
        "third_party_sublimit_cents": calc.round_cents(
            Decimal(limit_cents) * plan["third_party_sublimit_pct"]),
        "bound_premium_cents": audit["indicated_premium_cents"],
        "premium_variance_cents": (audit["indicated_premium_cents"]
                                   - assessment["indicated_premium_cents"]),
        "suspension_reason": None,
        "suspended_at": None,
        "status": "ACTIVE" if active else "BOUND",
    })
    store.POLICIES[row["id"]] = row
    assessment["status"] = "BOUND"
    store.touch(assessment)
    return created_response(serialize.policy(row))


@bp.post("/epli/policies/<policy_id>/suspend")
def suspend_policy(policy_id):
    auth(("UnderwritingManager",))
    body = parse_body([F("suspension_reason", "str", required=True)])
    row = store.find(store.POLICIES, policy_id, "ERR_POLICY_NOT_FOUND")
    if row["status"] != "ACTIVE":
        raise ApiError("ERR_POLICY_NOT_SUSPENDABLE",
                       "Only an ACTIVE policy may be suspended.")
    row["status"] = "SUSPENDED"
    row["suspension_reason"] = body["suspension_reason"]
    row["suspended_at"] = store.clock_now()
    store.touch(row)
    ledger.suspend_cascade(row)
    return object_response(serialize.policy(row))


@bp.post("/epli/policies/<policy_id>/reinstate")
def reinstate_policy(policy_id):
    auth(("UnderwritingManager",))
    no_body()
    row = store.find(store.POLICIES, policy_id, "ERR_POLICY_NOT_FOUND")
    if (row["status"] != "SUSPENDED"
            or store.clock_now() >= row["effective_to"]):
        raise ApiError("ERR_POLICY_NOT_REINSTATABLE",
                       "Only a SUSPENDED policy still inside its term may be "
                       "reinstated.")
    row["status"] = "ACTIVE"
    row["suspension_reason"] = None
    row["suspended_at"] = None
    store.touch(row)
    ledger.reinstate_cascade(row)
    return object_response(serialize.policy(row))
