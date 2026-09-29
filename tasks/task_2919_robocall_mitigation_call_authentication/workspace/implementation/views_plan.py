"""Robocall mitigation plan filing workflow (PRD 3.1)."""
from flask import Blueprint

import auth
import derive
import envelope
import errors
import ser
import store
import valid
from store import db, touch
from views_provider import load_provider

bp = Blueprint("plans", __name__)

PRACTICES = ("KYC_ONBOARDING", "TRAFFIC_PATTERN_MONITORING",
             "CONTRACT_TERMS_PROHIBITION", "CALL_BLOCKING_ANALYTICS",
             "TRACEBACK_COOPERATION")
FILING_STATES = ("DRAFT", "SUBMITTED", "ACCEPTED", "DEFICIENT", "WITHDRAWN",
                 "SUPERSEDED")
DECISIONS = ("ACCEPT", "DEFICIENT")
MINIMUM_PRACTICES = 3
MANDATORY_PRACTICES = ("KYC_ONBOARDING", "TRACEBACK_COOPERATION")
SUPERSEDABLE = ("DRAFT", "SUBMITTED", "ACCEPTED", "DEFICIENT")

READ_ROLES = (auth.REGULATOR, auth.COMPLIANCE_OFFICER, auth.PROVIDER_ADMIN)


def load_plan(plan_id):
    row = db.plans.get(plan_id)
    if row is None:
        errors.fail(errors.ERR_PLAN_NOT_FOUND, "No plan with id %s" % plan_id)
    return row


def _bad_state(message):
    errors.fail(errors.ERR_PLAN_STATE_INVALID, message)


@bp.route("/rmd/mitigation-plans", methods=["POST"])
@auth.require(auth.COMPLIANCE_OFFICER)
def draft_plan():
    data = valid.body()
    provider_id = valid.req_str(data, "provider_id")
    practices = valid.req_enum_list(data, "prevention_practices", PRACTICES)
    expected = valid.req_int(data, "expected_provider_version")
    provider = load_provider(provider_id)
    if expected != provider["version"]:
        errors.fail(errors.ERR_STALE_PROVIDER_VERSION,
                    "expected_provider_version does not match the provider")

    for other in store.order_rows(derive.plans_of(provider_id)):
        if other["filing_state"] in SUPERSEDABLE:
            other["filing_state"] = "SUPERSEDED"
            touch(other)

    row = store.base_row()
    row.update({
        "provider_id": provider_id,
        "prevention_practices": practices,
        "filing_state": "DRAFT",
        "filed_by_user_id": None,
        "submitted_at": None,
        "decided_at": None,
        "deficiency_reasons": [],
        "deficiency_count": 0,
        "revision_count": 0,
    })
    db.plans[row["id"]] = row
    derive.recompute_provider(provider)
    return envelope.created(ser.plan(row))


@bp.route("/rmd/mitigation-plans/<plan_id>/submit", methods=["POST"])
@auth.require(auth.COMPLIANCE_OFFICER)
def submit_plan(plan_id):
    row = load_plan(plan_id)
    if row["filing_state"] not in ("DRAFT", "DEFICIENT"):
        _bad_state("Only a DRAFT or DEFICIENT plan can be submitted")

    practices = row["prevention_practices"]
    if len(practices) < MINIMUM_PRACTICES or any(
            p not in practices for p in MANDATORY_PRACTICES):
        errors.fail(errors.ERR_PRACTICES_INSUFFICIENT,
                    "The filing must describe at least three practices "
                    "including KYC_ONBOARDING and TRACEBACK_COOPERATION")

    resubmission = row["filing_state"] == "DEFICIENT"
    row["filing_state"] = "SUBMITTED"
    row["submitted_at"] = db.now()
    row["filed_by_user_id"] = auth.acting_id()
    if resubmission:
        row["revision_count"] = row["revision_count"] + 1
        row["deficiency_reasons"] = []
    touch(row)
    derive.recompute_provider_by_id(row["provider_id"])
    return envelope.ok(ser.plan(row))


@bp.route("/rmd/mitigation-plans/<plan_id>/decision", methods=["POST"])
@auth.require(auth.REGULATOR)
def decide_plan(plan_id):
    data = valid.body()
    decision = valid.req_enum(data, "decision", DECISIONS)
    reasons = None
    if decision == "DEFICIENT":
        reasons = valid.req_str_list(data, "deficiency_reasons", min_len=1)
    row = load_plan(plan_id)
    if row["filing_state"] != "SUBMITTED":
        _bad_state("Only a SUBMITTED plan can be decided")

    row["decided_at"] = db.now()
    if decision == "ACCEPT":
        row["filing_state"] = "ACCEPTED"
    else:
        row["filing_state"] = "DEFICIENT"
        row["deficiency_reasons"] = reasons
        row["deficiency_count"] = row["deficiency_count"] + 1
    touch(row)
    derive.recompute_provider_by_id(row["provider_id"])
    return envelope.ok(ser.plan(row))


@bp.route("/rmd/mitigation-plans/<plan_id>/withdraw", methods=["POST"])
@auth.require(auth.COMPLIANCE_OFFICER)
def withdraw_plan(plan_id):
    row = load_plan(plan_id)
    if row["filing_state"] in ("WITHDRAWN", "SUPERSEDED"):
        _bad_state("A terminal plan cannot be withdrawn")
    row["filing_state"] = "WITHDRAWN"
    touch(row)
    derive.recompute_provider_by_id(row["provider_id"])
    return envelope.ok(ser.plan(row))


@bp.route("/rmd/mitigation-plans/<plan_id>", methods=["GET"])
@auth.require(*READ_ROLES)
def read_plan(plan_id):
    row = load_plan(plan_id)
    auth.own_provider(row["provider_id"])
    return envelope.ok(ser.plan(row))


@bp.route("/rmd/mitigation-plans", methods=["GET"])
@auth.require(*READ_ROLES)
def list_plans():
    limit, offset = envelope.pagination()
    provider_id = valid.arg_str("provider_id")
    filing_state = valid.arg_enum("filing_state", FILING_STATES)

    rows = auth.scope_rows(db.plans.values(),
                           provider_of=lambda r: r["provider_id"])
    if provider_id is not None:
        rows = [r for r in rows if r["provider_id"] == provider_id]
    if filing_state is not None:
        rows = [r for r in rows if r["filing_state"] == filing_state]
    return envelope.collection(rows, ser.plan, limit, offset)
