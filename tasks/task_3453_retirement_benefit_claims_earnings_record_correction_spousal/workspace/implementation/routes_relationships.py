"""Relationship assertion and verification (PRD §3.3).

Assertion enters ASSERTED; verification (ASSERTED -> VERIFIED) enforces, in
rejection order: state legality, verified-marriage interval exclusivity with
half-open [marriage_date, divorce_date) semantics on any shared endpoint
worker (ERR_RELATIONSHIP_OVERLAP), then WIDOW-requires-deceased
(ERR_WORKER_NOT_DECEASED). Rejection has no preconditions.
"""

from flask import Blueprint

import timeutil as tu
import validation as v
from db import store, stamp_common_new, touch
from envelope import ok
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_RELATIONSHIP_NOT_FOUND,
    ERR_RELATIONSHIP_OVERLAP,
    ERR_WORKER_NOT_DECEASED,
    ERR_WORKER_NOT_FOUND,
)
from security import (
    ROLE_CLAIMANT,
    ROLE_CLAIMS_SPECIALIST,
    authenticate,
    claimant_involved,
    require_role,
)
from serializers import relationship_dict

bp = Blueprint("relationships", __name__)

RELATIONSHIP_TYPES = {"CURRENT_SPOUSE", "DIVORCED_SPOUSE", "WIDOW"}


def load_relationship(relationship_id):
    r = store.relationships.get(relationship_id)
    if r is None:
        raise ApiError(ERR_RELATIONSHIP_NOT_FOUND, f"No relationship with id {relationship_id}.")
    return r


def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap; a None end is open-ended. An interval
    ending exactly when another begins does NOT overlap."""
    if a_end is not None and b_start >= a_end:
        return False
    if b_end is not None and a_start >= b_end:
        return False
    return True


@bp.route("/ssa/relationships", methods=["POST"])
def create_relationship():
    ctx = authenticate()
    require_role(ctx, {ROLE_CLAIMANT, ROLE_CLAIMS_SPECIALIST})
    body = v.get_body()
    worker_id = v.req_str(body, "worker_id")
    spouse_worker_id = v.req_str(body, "spouse_worker_id")
    # Layer 3 — ownership precedes the remaining body checks (PRD §2.9).
    claimant_involved(ctx, worker_id, spouse_worker_id)
    rtype = v.req_enum(body, "relationship_type", RELATIONSHIP_TYPES)
    marriage_date = v.req_date(body, "marriage_date")
    if rtype == "DIVORCED_SPOUSE":
        divorce_date = v.req_date(body, "divorce_date")
    else:
        divorce_date = v.opt_date(body, "divorce_date")
        if divorce_date is not None:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "divorce_date is present exactly when relationship_type is DIVORCED_SPOUSE.",
            )
    if worker_id not in store.workers:
        raise ApiError(ERR_WORKER_NOT_FOUND, f"No worker with id {worker_id}.")
    if spouse_worker_id not in store.workers:
        raise ApiError(ERR_WORKER_NOT_FOUND, f"No worker with id {spouse_worker_id}.")
    rel = stamp_common_new(
        {
            "worker_id": worker_id,
            "spouse_worker_id": spouse_worker_id,
            "relationship_type": rtype,
            "marriage_date": marriage_date,
            "divorce_date": divorce_date,
            "status": "ASSERTED",
            "verified_at": None,
        }
    )
    store.relationships[rel["id"]] = rel
    return ok(relationship_dict(rel), 201)


@bp.route("/ssa/relationships/<relationship_id>/verify", methods=["POST"])
def verify_relationship(relationship_id):
    ctx = authenticate()
    require_role(ctx, {ROLE_CLAIMS_SPECIALIST})
    rel = load_relationship(relationship_id)
    if rel["status"] != "ASSERTED":
        raise ApiError(ERR_INVALID_STATE, "Only an ASSERTED relationship can be verified.")
    if rel["relationship_type"] == "DIVORCED_SPOUSE" and not rel["divorce_date"]:
        raise ApiError(ERR_INVALID_REQUEST, "A DIVORCED_SPOUSE relationship requires a divorce_date.")
    # Layer 9 — verified-marriage interval exclusivity on a shared endpoint.
    this_start = tu.parse_date_str(rel["marriage_date"])
    this_end = tu.parse_date_str(rel["divorce_date"]) if rel["divorce_date"] else None
    endpoints = {rel["worker_id"], rel["spouse_worker_id"]}
    for other in store.relationships.values():
        if other["id"] == rel["id"] or other["status"] != "VERIFIED":
            continue
        if not ({other["worker_id"], other["spouse_worker_id"]} & endpoints):
            continue
        o_start = tu.parse_date_str(other["marriage_date"])
        o_end = tu.parse_date_str(other["divorce_date"]) if other["divorce_date"] else None
        if _intervals_overlap(this_start, this_end, o_start, o_end):
            raise ApiError(
                ERR_RELATIONSHIP_OVERLAP,
                "Verifying would create overlapping VERIFIED marriage intervals on a shared worker.",
            )
    # Layer 11 — WIDOW verification requires a deceased covered worker.
    if rel["relationship_type"] == "WIDOW":
        covered = store.workers.get(rel["worker_id"])
        if covered is None or covered["status"] != "DECEASED":
            raise ApiError(
                ERR_WORKER_NOT_DECEASED,
                "A WIDOW relationship may only be verified for a deceased covered worker.",
            )
    rel["status"] = "VERIFIED"
    rel["verified_at"] = store.now_iso()
    touch(rel)
    return ok(relationship_dict(rel))


@bp.route("/ssa/relationships/<relationship_id>/reject", methods=["POST"])
def reject_relationship(relationship_id):
    ctx = authenticate()
    require_role(ctx, {ROLE_CLAIMS_SPECIALIST})
    # Layer 4 — body well-formedness precedes path resolution (PRD §2.9).
    body = v.get_body()
    v.req_str(body, "rejection_reason")
    rel = load_relationship(relationship_id)
    if rel["status"] != "ASSERTED":
        raise ApiError(ERR_INVALID_STATE, "Only an ASSERTED relationship can be rejected.")
    rel["status"] = "REJECTED"
    touch(rel)
    return ok(relationship_dict(rel))
