"""Overpayment cases, waivers, and recovery (PRD §3.8): specialist-opened
cases enter NOTIFIED with the notice date stamped at creation; waiver
requests within 30 days (OCC-guarded); senior-adjudicator waiver decisions
with segregation from the creator; manual begin-recovery only after the
waiver window and only against an ENTITLED claim, electing the claim-level
recovery mode.
"""

from flask import Blueprint

import timeutil as tu
import validation as v
from db import store, stamp_common_new, touch
from envelope import ok
from errors import (
    ApiError,
    ERR_CLAIM_ALREADY_TERMINAL,
    ERR_CLAIM_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_OVERPAYMENT_NOT_FOUND,
    ERR_RECOVERY_RATE_TOO_LOW,
    ERR_SAME_ADJUDICATOR,
    ERR_STALE_VERSION,
    ERR_WAIVER_WINDOW_CLOSED,
    ERR_WAIVER_WINDOW_OPEN,
)
from security import (
    ROLE_CLAIMANT,
    ROLE_CLAIMS_SPECIALIST,
    ROLE_SENIOR_ADJUDICATOR,
    authenticate,
    claimant_owns,
    require_role,
)
from serializers import overpayment_dict

bp = Blueprint("overpayments", __name__)

REASONS = {"RECOMPUTATION", "FRAUD", "REPORTING_ERROR", "SYSTEM_ERROR"}
RECOVERY_MODES = {"FULL", "PARTIAL", "PROPORTIONAL"}
WAIVER_WINDOW_DAYS = 30


def load_overpayment(case_id):
    o = store.overpayments.get(case_id)
    if o is None:
        raise ApiError(ERR_OVERPAYMENT_NOT_FOUND, f"No overpayment case with id {case_id}.")
    return o


def _notice_date(case):
    return tu.parse_iso_to_date(case["created_at"])


@bp.route("/ssa/overpayment-cases", methods=["POST"])
def create_overpayment():
    ctx = authenticate()
    require_role(ctx, {ROLE_CLAIMS_SPECIALIST})
    body = v.get_body()
    claim_id = v.req_str(body, "claim_id")
    amount = v.req_int(body, "amount_cents", min_v=1)
    period_start = v.req_month(body, "period_start_month")
    period_end = v.req_month(body, "period_end_month")
    reason = v.req_enum(body, "reason", REASONS)
    if claim_id not in store.claims:
        raise ApiError(ERR_CLAIM_NOT_FOUND, f"No claim with id {claim_id}.")
    case = stamp_common_new(
        {
            "claim_id": claim_id,
            "amount_cents": amount,
            "period_start_month": period_start,
            "period_end_month": period_end,
            "reason": reason,
            "status": "NOTIFIED",
            "created_by": ctx["user_id"],
            "recovered_cents": 0,
            "waiver_grounds": None,
            "waiver_decided_by": None,
            "monthly_rate_cents": None,
        }
    )
    store.overpayments[case["id"]] = case
    return ok(overpayment_dict(case), 201)


@bp.route("/ssa/overpayment-cases/<case_id>/request-waiver", methods=["POST"])
def request_waiver(case_id):
    ctx = authenticate()
    require_role(ctx, {ROLE_CLAIMANT, ROLE_CLAIMS_SPECIALIST})
    case = load_overpayment(case_id)
    claim = store.claims.get(case["claim_id"])
    if claim is not None:
        claimant_owns(ctx, claim["worker_id"])
    body = v.get_body()
    expected = v.req_int(body, "expected_overpayment_version", min_v=0)
    grounds = v.req_str(body, "waiver_grounds")
    if case["status"] != "NOTIFIED":
        raise ApiError(ERR_INVALID_STATE, "Only a NOTIFIED case can accept a waiver request.")
    if expected != case["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_overpayment_version does not match the case's current version.",
        )
    if store.clock_date() > tu.plus_days(_notice_date(case), WAIVER_WINDOW_DAYS):
        raise ApiError(
            ERR_WAIVER_WINDOW_CLOSED, "Waiver requested more than 30 days after the notice."
        )
    case["status"] = "WAIVER_REVIEW"
    case["waiver_grounds"] = grounds
    touch(case)
    return ok(overpayment_dict(case))


@bp.route("/ssa/overpayment-cases/<case_id>/decide-waiver", methods=["POST"])
def decide_waiver(case_id):
    ctx = authenticate()
    require_role(ctx, {ROLE_SENIOR_ADJUDICATOR})
    # Layer 4 — body well-formedness precedes path resolution (PRD §2.9).
    body = v.get_body()
    outcome = v.req_enum(body, "outcome", {"GRANTED", "DENIED"})
    case = load_overpayment(case_id)
    if case["status"] != "WAIVER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, "Only a WAIVER_REVIEW case can be decided.")
    if ctx["user_id"] == case["created_by"]:
        raise ApiError(
            ERR_SAME_ADJUDICATOR, "The case creator may not decide its waiver."
        )
    case["waiver_decided_by"] = ctx["user_id"]
    case["status"] = "WAIVED" if outcome == "GRANTED" else "RECOVERY_ACTIVE"
    touch(case)
    return ok(overpayment_dict(case))


@bp.route("/ssa/overpayment-cases/<case_id>/begin-recovery", methods=["POST"])
def begin_recovery(case_id):
    ctx = authenticate()
    require_role(ctx, {ROLE_CLAIMS_SPECIALIST})
    # Layer 4 — body well-formedness precedes path resolution (PRD §2.9).
    body = v.get_body()
    mode = v.req_enum(body, "recovery_mode", RECOVERY_MODES)
    if mode == "PARTIAL":
        rate = v.req_int(body, "monthly_rate_cents", min_v=1)
    else:
        rate = v.opt_int(body, "monthly_rate_cents", min_v=1)
    case = load_overpayment(case_id)
    if case["status"] != "NOTIFIED":
        raise ApiError(ERR_INVALID_STATE, "Only a NOTIFIED case can begin recovery.")
    claim = store.claims.get(case["claim_id"])
    if claim is not None and claim["status"] in ("WITHDRAWN", "TERMINATED"):
        raise ApiError(
            ERR_CLAIM_ALREADY_TERMINAL, "Recovery is only from future benefits of an active claim."
        )
    if claim is None or claim["status"] != "ENTITLED":
        raise ApiError(
            ERR_INVALID_STATE, "Recovery is only from future benefits of an ENTITLED claim."
        )
    # Layer 10 — manual begin-recovery only after the 30-day waiver window.
    if store.clock_date() <= tu.plus_days(_notice_date(case), WAIVER_WINDOW_DAYS):
        raise ApiError(
            ERR_WAIVER_WINDOW_OPEN, "The 30-day waiver window is still open."
        )
    # Layer 12 — PARTIAL must withhold at least 10% of the monthly benefit.
    if mode == "PARTIAL" and rate * 10 < claim["monthly_benefit_cents"]:
        raise ApiError(
            ERR_RECOVERY_RATE_TOO_LOW,
            "PARTIAL recovery election is below 10% of the claim's monthly benefit.",
        )
    case["status"] = "RECOVERY_ACTIVE"
    case["monthly_rate_cents"] = rate if mode == "PARTIAL" else None
    touch(case)
    claim["recovery_mode"] = mode
    if mode == "PARTIAL":
        claim["partial_rate_cents"] = rate
    touch(claim)
    return ok(overpayment_dict(case))
