"""Liability policies and the coverage ledger (PRD 3.6)."""

from flask import Blueprint

import calc
from auth import authenticate, check_body_owner, check_owns
from clockmod import clock
from common import collection_response, find, must_exist, string_filters
from envelope import ok
from errors import ApiError
from shape import opt_bool, raw_body, req_dt, req_enum, req_int, req_str, soft_body
from store import store, touch
from views import view

bp = Blueprint("insurance", __name__)


@bp.post("/insurance-policies")
def create_policy():
    caller = authenticate(("Pilot", "ComplianceOfficer"))
    check_body_owner(caller, soft_body())
    body = raw_body()
    pilot_id = req_str(body, "pilot_id")
    insurer_name = req_str(body, "insurer_name", max_len=80)
    policy_number = req_str(body, "policy_number", max_len=40)
    coverage_limit_cents = req_int(body, "coverage_limit_cents", minimum=0)
    deductible_cents = req_int(body, "deductible_cents", minimum=0)
    effective_from = req_dt(body, "effective_from")
    effective_until = req_dt(body, "effective_until")
    indemnified = opt_bool(body, "indemnification_clause_accepted", default=False)
    if effective_until <= effective_from:
        raise ApiError("ERR_INVALID_WINDOW",
                       "effective_until must be strictly after effective_from")
    pilot = must_exist("pilots", pilot_id)
    for other in store.all("policies"):
        if other["pilot_id"] == pilot["id"] \
                and other["policy_number"] == policy_number:
            raise ApiError("ERR_DUPLICATE_POLICY_NUMBER")
    policy = store.insert("policies", {
        "pilot_id": pilot["id"],
        "insurer_name": insurer_name,
        "policy_number": policy_number,
        "coverage_limit_cents": coverage_limit_cents,
        "deductible_cents": deductible_cents,
        "effective_from": effective_from,
        "effective_until": effective_until,
        "indemnification_clause_accepted": indemnified,
        "coverage_status": "PENDING_VERIFICATION",
        # Filing grants nothing: the ledger opens only on verification.
        "open_reserved_cents_total": 0,
        "settled_cents_total": 0,
        "remaining_coverage_cents": 0,
    })
    return ok(view(policy), 201)


@bp.get("/insurance-policies/<policy_id>")
def read_policy(policy_id):
    caller = authenticate(("Pilot", "ComplianceOfficer", "InvestigationOfficer"))
    check_owns(caller, find("policies", policy_id))
    policy = must_exist("policies", policy_id)
    return ok(view(policy))


@bp.get("/insurance-policies")
def list_policies():
    caller = authenticate(("Pilot", "ComplianceOfficer", "InvestigationOfficer"))
    filters = string_filters("pilot_id", "coverage_status")
    return collection_response(caller, "policies", filters=filters)


@bp.post("/insurance-policies/<policy_id>/verify")
def verify_policy(policy_id):
    authenticate(("ComplianceOfficer",))
    policy = must_exist("policies", policy_id)
    body = raw_body()
    outcome = req_enum(body, "outcome", ("ACTIVE", "REJECTED"))
    if policy["coverage_status"] != "PENDING_VERIFICATION":
        raise ApiError("ERR_POLICY_INVALID_STATE")
    if outcome == "ACTIVE":
        if policy["effective_until"] <= clock.now():
            raise ApiError("ERR_POLICY_INVALID_STATE",
                           "cover has already run out and cannot be activated")
        policy["coverage_status"] = "ACTIVE"
        calc.recompute_policy_ledger(policy)
    else:
        policy["coverage_status"] = "REJECTED"
        policy["open_reserved_cents_total"] = 0
        policy["settled_cents_total"] = 0
        policy["remaining_coverage_cents"] = 0
    touch(policy)
    return ok(view(policy))
