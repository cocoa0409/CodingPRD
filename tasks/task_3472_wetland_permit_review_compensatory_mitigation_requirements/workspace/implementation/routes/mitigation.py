"""MitigationPlan endpoints (PRD §3.6)."""

from decimal import Decimal

from flask import Blueprint

import calculations as calc
from db import STORE, bump, get_clock, new_entity
from errors import api_err
from helpers import (get_body, opt_bool, opt_number, opt_str, req_enum,
                     req_number)
from middleware import check_ownership, require_roles
from response import apply_filters, list_response, success_obj
from serialization import plan_out

bp = Blueprint("mitigation", __name__)

ALL_ROLES = ("SystemAdmin", "Applicant", "Reviewer", "DistrictEngineer",
             "AgencyReviewer", "EnforcementOfficer")
MECHANISMS = ("BANK_CREDITS", "IN_LIEU_FEE", "PERMITTEE_RESPONSIBLE",
              "COMBINATION")
PLAN_VERDICTS = ("APPROVE", "REQUEST_REVISION")
PLAN_TERMINAL = ("COMPLETED", "DEFAULTED", "CANCELLED")


def _get_plan_or_404(plan_id):
    plan = STORE["plans"].get(plan_id)
    if plan is None:
        raise api_err("ERR_PLAN_NOT_FOUND",
                      "No MitigationPlan with id %s" % plan_id)
    return plan


def _app_of(plan):
    return STORE["applications"].get(plan["application_id"])


def _validate_mechanism_fields(mechanism, stewardship_entity_name):
    """stewardship_entity_name is required for PERMITTEE_RESPONSIBLE and
    COMBINATION."""
    if mechanism in ("PERMITTEE_RESPONSIBLE", "COMBINATION") \
            and not stewardship_entity_name:
        raise api_err("ERR_INVALID_REQUEST",
                      "stewardship_entity_name is required for "
                      "PERMITTEE_RESPONSIBLE and COMBINATION mechanisms")


def _recompute_money_fields(plan, application):
    """(Re)compute the mechanism-attached money fields from the plan's
    required_credits_by_type."""
    if plan["mechanism"] in ("IN_LIEU_FEE", "COMBINATION"):
        plan["ilf_fee_due_dollars"] = calc.ilf_fee(
            plan["required_credits_by_type"])
    else:
        plan["ilf_fee_due_dollars"] = None
    if plan["mechanism"] in ("PERMITTEE_RESPONSIBLE", "COMBINATION"):
        plan["assurance_required_dollars"] = calc.assurance_required(
            plan["required_credits_by_type"])
    else:
        plan["assurance_required_dollars"] = None


@bp.post("/wetland-permits/mitigation-plans")
def create_plan():
    user_id, role = require_roles(["Applicant"])
    body = get_body()
    # Tier 5: body FK existence (also needed for ownership).
    application_id = body.get("application_id")
    app = None
    if application_id is not None and isinstance(application_id, str):
        app = STORE["applications"].get(application_id)
        if app is None:
            raise api_err("ERR_APPLICATION_NOT_FOUND",
                          "No PermitApplication with id %s" % application_id)
    # Tier 6: shape — application_id is a required field.
    if not isinstance(application_id, str):
        raise api_err("ERR_INVALID_REQUEST",
                      "Field application_id is required")
    # Tier 4: ownership via the parent application.
    check_ownership(user_id, role, app["applicant_id"])
    mechanism = req_enum(body, "mechanism", MECHANISMS)
    financial_assurance = opt_number(body, "financial_assurance_dollars",
                                     default=Decimal("0"),
                                     minimum=Decimal("0"))
    stewardship_entity_name = opt_str(body, "stewardship_entity_name")
    lts = opt_bool(body, "long_term_stewardship_secured", default=False)
    _validate_mechanism_fields(mechanism, stewardship_entity_name)
    # Tier 7 / priority 19: creation sequencing.
    if app["pathway"] in ("GENERAL", "ATF_GENERAL"):
        # General pathways skipped alternatives review; the application must
        # sit in DECISION_PENDING (state tier).
        if app["status"] != "DECISION_PENDING":
            raise api_err("ERR_APPLICATION_INVALID_STATE",
                          "Plan creation for a general pathway requires the "
                          "application in DECISION_PENDING")
    else:
        # Individual pathways: avoidance and minimization before
        # compensation — the analysis must be ACCEPTED.
        accepted = any(aa["application_id"] == app["id"]
                       and aa["status"] == "ACCEPTED"
                       for aa in STORE["analyses"].values())
        if not accepted:
            raise api_err("ERR_AA_NOT_ACCEPTED",
                          "The alternatives analysis must be ACCEPTED "
                          "before a mitigation plan is created")
    # Priority 24: at most one non-terminal plan per application.
    for existing in STORE["plans"].values():
        if existing["application_id"] == app["id"] \
                and existing["status"] not in PLAN_TERMINAL:
            raise api_err("ERR_ACTIVE_PLAN_EXISTS",
                          "The application already has an active mitigation "
                          "plan")
    plan = new_entity({
        "application_id": app["id"],
        "mechanism": mechanism,
        "financial_assurance_dollars": financial_assurance,
        "stewardship_entity_name": stewardship_entity_name,
        "long_term_stewardship_secured": lts,
        "required_credits_by_type": calc.provisional_credits(app),
        "final_credits_required_by_type": None,
        "ilf_fee_due_dollars": None,
        "ilf_fee_paid_dollars": Decimal("0"),
        "assurance_required_dollars": None,
        "secured_date": None,
        "status": "DRAFT",
    })
    _recompute_money_fields(plan, app)
    STORE["plans"][plan["id"]] = plan
    return success_obj(plan_out(plan), 201)


@bp.get("/wetland-permits/mitigation-plans")
def list_plans():
    require_roles(list(ALL_ROLES))
    items = apply_filters(STORE["plans"].values(), {
        "application_id": "application_id",
        "mechanism": "mechanism",
        "status": "status",
    })
    return list_response(items, plan_out)


@bp.get("/wetland-permits/mitigation-plans/<id>")
def get_plan(id):
    require_roles(list(ALL_ROLES))
    return success_obj(plan_out(_get_plan_or_404(id)))


@bp.patch("/wetland-permits/mitigation-plans/<id>")
def patch_plan(id):
    user_id, role = require_roles(["Applicant"])
    plan = _get_plan_or_404(id)
    app = _app_of(plan)
    check_ownership(user_id, role, app["applicant_id"] if app else None)
    body = get_body()
    # Tier 6: shape — OCC field required; provided fields valid.
    if "expected_plan_version" not in body \
            or body.get("expected_plan_version") is None:
        raise api_err("ERR_INVALID_REQUEST",
                      "Field expected_plan_version is required")
    expected = body["expected_plan_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise api_err("ERR_INVALID_REQUEST",
                      "Field expected_plan_version must be an integer")
    if "mechanism" in body and body.get("mechanism") is not None \
            and body["mechanism"] not in MECHANISMS:
        raise api_err("ERR_INVALID_REQUEST",
                      "Field mechanism must be one of %s"
                      % ", ".join(MECHANISMS))
    new_assurance = opt_number(body, "financial_assurance_dollars",
                               default=None, minimum=Decimal("0"))
    if "stewardship_entity_name" in body \
            and body.get("stewardship_entity_name") is not None \
            and not isinstance(body["stewardship_entity_name"], str):
        raise api_err("ERR_INVALID_REQUEST",
                      "Field stewardship_entity_name must be a string")
    if "long_term_stewardship_secured" in body \
            and body.get("long_term_stewardship_secured") is not None:
        opt_bool(body, "long_term_stewardship_secured")
    merged_mechanism = body.get("mechanism") \
        if body.get("mechanism") is not None else plan["mechanism"]
    merged_stewardship = body.get("stewardship_entity_name") \
        if "stewardship_entity_name" in body else plan["stewardship_entity_name"]
    _validate_mechanism_fields(merged_mechanism, merged_stewardship)
    # Tier 7: state — DRAFT stays DRAFT; REVISION_REQUESTED returns to
    # SUBMITTED.
    if plan["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise api_err("ERR_PLAN_INVALID_STATE",
                      "Only a DRAFT or REVISION_REQUESTED plan can be "
                      "edited")
    # Tier 8: optimistic concurrency.
    if expected != plan["version"]:
        raise api_err("ERR_STALE_VERSION",
                      "expected_plan_version does not match the plan's "
                      "current version")
    if body.get("mechanism") is not None:
        plan["mechanism"] = body["mechanism"]
    if new_assurance is not None:
        plan["financial_assurance_dollars"] = new_assurance
    if "stewardship_entity_name" in body:
        plan["stewardship_entity_name"] = body.get("stewardship_entity_name")
    if "long_term_stewardship_secured" in body \
            and body.get("long_term_stewardship_secured") is not None:
        plan["long_term_stewardship_secured"] = \
            body["long_term_stewardship_secured"]
    _recompute_money_fields(plan, app)
    if plan["status"] == "REVISION_REQUESTED":
        plan["status"] = "SUBMITTED"
    bump(plan)
    return success_obj(plan_out(plan))


@bp.post("/wetland-permits/mitigation-plans/<id>/submit")
def submit_plan(id):
    user_id, role = require_roles(["Applicant"])
    plan = _get_plan_or_404(id)
    app = _app_of(plan)
    check_ownership(user_id, role, app["applicant_id"] if app else None)
    get_body()
    if plan["status"] != "DRAFT":
        raise api_err("ERR_PLAN_INVALID_STATE",
                      "Only a DRAFT plan can be submitted")
    plan["status"] = "SUBMITTED"
    bump(plan)
    return success_obj(plan_out(plan))


@bp.post("/wetland-permits/mitigation-plans/<id>/review")
def review_plan(id):
    require_roles(["Reviewer"])
    plan = _get_plan_or_404(id)
    body = get_body()
    verdict = req_enum(body, "verdict", PLAN_VERDICTS)
    opt_str(body, "revision_notes")
    if plan["status"] != "SUBMITTED":
        raise api_err("ERR_PLAN_INVALID_STATE",
                      "Only a SUBMITTED plan can be reviewed")
    plan["status"] = "APPROVED" if verdict == "APPROVE" else \
        "REVISION_REQUESTED"
    bump(plan)
    return success_obj(plan_out(plan))


def _purchased_credits_by_type(plan_id):
    totals = {}
    for txn in STORE["credit_txns"].values():
        if txn["plan_id"] == plan_id and txn["status"] == "PURCHASED":
            totals[txn["resource_type"]] = totals.get(
                txn["resource_type"], Decimal("0")) + txn["credits"]
    return totals


@bp.post("/wetland-permits/mitigation-plans/<id>/secure-credits")
def secure_credits(id):
    user_id, role = require_roles(["Applicant"])
    plan = _get_plan_or_404(id)
    app = _app_of(plan)
    check_ownership(user_id, role, app["applicant_id"] if app else None)
    get_body()
    # Tier 7: the plan must be APPROVED; the IN_LIEU_FEE mechanism is
    # rejected here as a state error (it secures via pay-in-lieu-fee).
    if plan["status"] != "APPROVED" or plan["mechanism"] == "IN_LIEU_FEE":
        raise api_err("ERR_PLAN_INVALID_STATE",
                      "secure-credits requires an APPROVED BANK_CREDITS, "
                      "PERMITTEE_RESPONSIBLE, or COMBINATION plan")
    # The provisional requirement becomes final: recompute with the true
    # location, lag, and ATF multipliers and store.
    final = calc.final_credits(app, plan)
    plan["final_credits_required_by_type"] = final
    # Recompute the assurance requirement against the final requirement for
    # PERMITTEE_RESPONSIBLE / COMBINATION (see calculations.assurance_required
    # for the documented interpretation).
    if plan["mechanism"] in ("PERMITTEE_RESPONSIBLE", "COMBINATION"):
        plan["assurance_required_dollars"] = calc.assurance_required(final)
    purchased = _purchased_credits_by_type(plan["id"])
    mechanism = plan["mechanism"]
    if mechanism == "BANK_CREDITS":
        for rtype, required in final.items():
            if purchased.get(rtype, Decimal("0")) < required:
                raise api_err("ERR_CREDITS_NOT_SECURED",
                              "Purchased credits for %s are below the final "
                              "requirement" % rtype)
    elif mechanism == "PERMITTEE_RESPONSIBLE":
        if plan["financial_assurance_dollars"] < \
                plan["assurance_required_dollars"] \
                or not plan["long_term_stewardship_secured"]:
            raise api_err("ERR_INSUFFICIENT_FINANCIAL_ASSURANCE",
                          "Financial assurance is below the required amount "
                          "or long-term stewardship is not secured")
    else:  # COMBINATION — both halves at half weight.
        for rtype, required in final.items():
            half = calc.q2(Decimal("0.5") * required)
            if purchased.get(rtype, Decimal("0")) < half:
                raise api_err("ERR_CREDITS_NOT_SECURED",
                              "Purchased credits for %s are below half the "
                              "final requirement" % rtype)
        half_assurance = calc.q2(
            Decimal("0.5") * plan["assurance_required_dollars"])
        if plan["financial_assurance_dollars"] < half_assurance \
                or not plan["long_term_stewardship_secured"]:
            raise api_err("ERR_INSUFFICIENT_FINANCIAL_ASSURANCE",
                          "Financial assurance is below half the required "
                          "amount or long-term stewardship is not secured")
    plan["status"] = "CREDITS_SECURED"
    plan["secured_date"] = get_clock()
    bump(plan)
    return success_obj(plan_out(plan))


@bp.post("/wetland-permits/mitigation-plans/<id>/pay-in-lieu-fee")
def pay_in_lieu_fee(id):
    user_id, role = require_roles(["Applicant"])
    plan = _get_plan_or_404(id)
    app = _app_of(plan)
    check_ownership(user_id, role, app["applicant_id"] if app else None)
    body = get_body()
    amount = req_number(body, "amount_dollars", minimum=Decimal("0"))
    # Tier 7: APPROVED plan with the IN_LIEU_FEE mechanism.
    if plan["status"] != "APPROVED" or plan["mechanism"] != "IN_LIEU_FEE":
        raise api_err("ERR_PLAN_INVALID_STATE",
                      "pay-in-lieu-fee requires an APPROVED IN_LIEU_FEE plan")
    # Priority 29: the amount must equal ilf_fee_due_dollars exactly.
    if amount != plan["ilf_fee_due_dollars"]:
        raise api_err("ERR_PAYMENT_AMOUNT_MISMATCH",
                      "amount_dollars must equal ilf_fee_due_dollars "
                      "exactly")
    # The final-variant credit requirement is computed and stored at
    # securing; the fee itself was fixed at creation and never recomputed.
    plan["final_credits_required_by_type"] = calc.final_credits(app, plan)
    plan["ilf_fee_paid_dollars"] = amount
    plan["status"] = "CREDITS_SECURED"
    plan["secured_date"] = get_clock()
    bump(plan)
    return success_obj(plan_out(plan))
