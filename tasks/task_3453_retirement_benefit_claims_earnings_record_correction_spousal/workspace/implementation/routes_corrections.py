"""Earnings-record correction requests (PRD §3.2): filing under the statute
of limitations, the PENDING_REVIEW <-> EVIDENCE_REQUESTED conversation,
approval with its three-hop recomputation cascade, denial, and the 60-day
denial-reopen loop with adjudicator segregation.
"""

from datetime import timedelta

from flask import Blueprint

import timeutil as tu
import validation as v
from db import store, stamp_common_new, touch, created_key
from envelope import ok
from errors import (
    ApiError,
    ERR_CORRECTION_NOT_FOUND,
    ERR_CORRECTION_TIME_BARRED,
    ERR_DUPLICATE_PENDING_CORRECTION,
    ERR_INVALID_STATE,
    ERR_NO_EARNINGS_DISCREPANCY,
    ERR_REOPEN_WINDOW_EXPIRED,
    ERR_SAME_ADJUDICATOR,
    ERR_WORKER_NOT_FOUND,
)
from security import (
    ROLE_CLAIMANT,
    ROLE_CLAIMS_SPECIALIST,
    ROLE_SENIOR_ADJUDICATOR,
    authenticate,
    claimant_owns,
    require_role,
)
from serializers import correction_dict

bp = Blueprint("corrections", __name__)

EVIDENCE_TYPES = {"WAGE_STATEMENT", "TAX_RETURN", "EMPLOYER_LETTER", "OTHER"}
REOPEN_WINDOW_DAYS = 60


def load_correction(correction_id):
    c = store.corrections.get(correction_id)
    if c is None:
        raise ApiError(ERR_CORRECTION_NOT_FOUND, f"No correction request with id {correction_id}.")
    return c


def _posted_for(worker_id, tax_year):
    """Current posted earnings for (worker, year); a missing row counts as 0."""
    for r in store.earnings_years.values():
        if r["worker_id"] == worker_id and r["tax_year"] == tax_year:
            return r["posted_earnings_cents"]
    return 0


def _check_statute(correction):
    if store.clock_date() > tu.parse_date_str(correction["statute_deadline"]):
        raise ApiError(
            ERR_CORRECTION_TIME_BARRED,
            "The 3-year/3-month/15-day correction statute has run.",
        )


def _in_reopen_window(correction):
    if correction["status"] != "DENIED" or not correction["decided_at"]:
        return False
    decided = tu.parse_iso8601(correction["decided_at"])
    return store.clock <= decided + timedelta(days=REOPEN_WINDOW_DAYS)


@bp.route("/ssa/correction-requests", methods=["POST"])
def create_correction():
    ctx = authenticate()
    require_role(ctx, {ROLE_CLAIMANT, ROLE_CLAIMS_SPECIALIST})
    body = v.get_body()
    worker_id = v.req_str(body, "worker_id")
    # Layer 3 — ownership precedes the remaining body checks (PRD §2.9).
    claimant_owns(ctx, worker_id)
    tax_year = v.req_int(body, "tax_year")
    claimed = v.req_int(body, "claimed_earnings_cents", min_v=0)
    evidence_type = v.req_enum(body, "evidence_type", EVIDENCE_TYPES)
    if worker_id not in store.workers:
        raise ApiError(ERR_WORKER_NOT_FOUND, f"No worker with id {worker_id}.")
    # Layer 9 — one non-terminal correction per (worker, tax_year): an
    # existing PENDING_REVIEW / EVIDENCE_REQUESTED, or a DENIED request still
    # inside its reopen window, blocks a new filing.
    for other in store.corrections.values():
        if other["worker_id"] != worker_id or other["tax_year"] != tax_year:
            continue
        if other["status"] in ("PENDING_REVIEW", "EVIDENCE_REQUESTED") or _in_reopen_window(other):
            raise ApiError(
                ERR_DUPLICATE_PENDING_CORRECTION,
                "A non-terminal correction already exists for this worker and tax year.",
            )
    # Layer 9 — the request must allege a real discrepancy.
    if claimed == _posted_for(worker_id, tax_year):
        raise ApiError(
            ERR_NO_EARNINGS_DISCREPANCY,
            "Claimed earnings equal the posted amount for that year.",
        )
    # Layer 10 — the statute binds from the first moment.
    deadline = tu.statute_deadline(tax_year)
    if store.clock_date() > deadline:
        raise ApiError(
            ERR_CORRECTION_TIME_BARRED,
            "The 3-year/3-month/15-day correction statute has run.",
        )
    correction = stamp_common_new(
        {
            "worker_id": worker_id,
            "tax_year": tax_year,
            "claimed_earnings_cents": claimed,
            "evidence_type": evidence_type,
            "status": "PENDING_REVIEW",
            "statute_deadline": deadline.isoformat(),
            "decided_by": None,
            "decided_at": None,
            "denial_reason": None,
        }
    )
    store.corrections[correction["id"]] = correction
    return ok(correction_dict(correction), 201)


@bp.route("/ssa/correction-requests/<correction_id>/request-evidence", methods=["POST"])
def request_evidence(correction_id):
    ctx = authenticate()
    require_role(ctx, {ROLE_CLAIMS_SPECIALIST})
    # Layer 4 — body well-formedness precedes path resolution (PRD §2.9).
    body = v.get_body()
    v.opt_str(body, "evidence_note")
    c = load_correction(correction_id)
    if c["status"] != "PENDING_REVIEW":
        raise ApiError(ERR_INVALID_STATE, "Only a PENDING_REVIEW request can move to EVIDENCE_REQUESTED.")
    _check_statute(c)
    c["status"] = "EVIDENCE_REQUESTED"
    touch(c)
    return ok(correction_dict(c))


@bp.route("/ssa/correction-requests/<correction_id>/submit-evidence", methods=["POST"])
def submit_evidence(correction_id):
    ctx = authenticate()
    require_role(ctx, {ROLE_CLAIMANT, ROLE_CLAIMS_SPECIALIST})
    c = load_correction(correction_id)
    claimant_owns(ctx, c["worker_id"])
    body = v.get_body()
    v.req_str(body, "evidence_detail")
    if c["status"] != "EVIDENCE_REQUESTED":
        raise ApiError(ERR_INVALID_STATE, "Only an EVIDENCE_REQUESTED request can accept evidence.")
    _check_statute(c)
    c["status"] = "PENDING_REVIEW"
    touch(c)
    return ok(correction_dict(c))


@bp.route("/ssa/correction-requests/<correction_id>/approve", methods=["POST"])
def approve_correction(correction_id):
    ctx = authenticate()
    require_role(ctx, {ROLE_CLAIMS_SPECIALIST})
    c = load_correction(correction_id)
    if c["status"] != "PENDING_REVIEW":
        raise ApiError(ERR_INVALID_STATE, "Only a PENDING_REVIEW request can be approved.")
    _check_statute(c)
    if c["claimed_earnings_cents"] == _posted_for(c["worker_id"], c["tax_year"]):
        raise ApiError(
            ERR_NO_EARNINGS_DISCREPANCY,
            "Claimed earnings equal the posted amount for that year.",
        )
    c["status"] = "APPROVED"
    c["decided_by"] = ctx["user_id"]
    c["decided_at"] = store.now_iso()
    touch(c)
    # Cascade hop 1 — upsert the earnings row with the claimed amount.
    row = None
    for r in store.earnings_years.values():
        if r["worker_id"] == c["worker_id"] and r["tax_year"] == c["tax_year"]:
            row = r
            break
    if row is None:
        row = stamp_common_new(
            {
                "worker_id": c["worker_id"],
                "tax_year": c["tax_year"],
                "posted_earnings_cents": c["claimed_earnings_cents"],
                "noncovered_earnings_cents": 0,
                "corrected": True,
            }
        )
        store.earnings_years[row["id"]] = row
    else:
        row["posted_earnings_cents"] = c["claimed_earnings_cents"]
        row["corrected"] = True
        touch(row)
    # Cascade hops 2-3 — recompute the worker's ENTITLED/SUSPENDED claims;
    # each retro delta settles as underpayment credit or an auto-opened
    # OverpaymentCase inside recompute_claim.
    from benefits import recompute_claim  # local import: benefits <- routes cycle guard

    affected = [
        cl
        for cl in store.claims.values()
        if cl["worker_id"] == c["worker_id"] and cl["status"] in ("ENTITLED", "SUSPENDED")
    ]
    affected.sort(key=created_key)
    for cl in affected:
        recompute_claim(cl, "CORRECTION_APPROVED")
        touch(cl)
    return ok(correction_dict(c))


@bp.route("/ssa/correction-requests/<correction_id>/deny", methods=["POST"])
def deny_correction(correction_id):
    ctx = authenticate()
    require_role(ctx, {ROLE_CLAIMS_SPECIALIST})
    # Layer 4 — body well-formedness precedes path resolution (PRD §2.9).
    body = v.get_body()
    reason = v.req_str(body, "denial_reason")
    c = load_correction(correction_id)
    if c["status"] != "PENDING_REVIEW":
        raise ApiError(ERR_INVALID_STATE, "Only a PENDING_REVIEW request can be denied.")
    _check_statute(c)
    c["status"] = "DENIED"
    c["decided_by"] = ctx["user_id"]
    c["decided_at"] = store.now_iso()
    c["denial_reason"] = reason
    touch(c)
    return ok(correction_dict(c))


@bp.route("/ssa/correction-requests/<correction_id>/reopen", methods=["POST"])
def reopen_correction(correction_id):
    ctx = authenticate()
    require_role(ctx, {ROLE_SENIOR_ADJUDICATOR})
    # Layer 4 — body well-formedness precedes path resolution (PRD §2.9).
    body = v.get_body()
    v.req_str(body, "reopen_reason")
    c = load_correction(correction_id)
    if c["status"] != "DENIED":
        raise ApiError(ERR_INVALID_STATE, "Only a DENIED request can be reopened.")
    # Layer 8 — segregation of duties precedes the temporal windows (§2.9).
    if ctx["user_id"] == c["decided_by"]:
        raise ApiError(ERR_SAME_ADJUDICATOR, "The denying operator may not reopen this request.")
    # Layer 10 — correction statute, then the 60-day reopen window (the
    # order given in PRD §2.9's temporal layer).
    _check_statute(c)
    decided = tu.parse_iso8601(c["decided_at"])
    if store.clock > decided + timedelta(days=REOPEN_WINDOW_DAYS):
        raise ApiError(ERR_REOPEN_WINDOW_EXPIRED, "More than 60 days have passed since the denial.")
    c["status"] = "PENDING_REVIEW"
    c["denial_reason"] = None
    c["decided_by"] = None
    c["decided_at"] = None
    touch(c)
    return ok(correction_dict(c))
