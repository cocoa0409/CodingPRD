"""Proof-of-insurance filings: creation with supersession, and cancellation (PRD 3.5)."""

from flask import Blueprint, request

import clock
import domain
import helpers
import store
from errors import ApiError, invalid
from validation import FILING_TYPES, Body, authenticate

bp = Blueprint("filings", __name__)

ALL_ROLES = ("CarrierRep", "InsuranceFiler", "VettingAnalyst", "ComplianceOfficer", "RegistryAdmin")


@bp.post("/insurance-filings")
def create_filing():
    uid, role = authenticate(("InsuranceFiler",))
    raw = request.get_json(silent=True)
    raw = raw if isinstance(raw, dict) else {}

    # rung 5: the acting insurer must be the filing party named in the body
    insurer_ref = raw.get("insurer_id")
    if isinstance(insurer_ref, str):
        helpers.require_filing_party(role, uid, insurer_ref)

    # rung 6: body foreign keys resolve
    authority_ref = raw.get("authority_id")
    if isinstance(authority_ref, str):
        helpers.resolve_body_ref(store.AUTHORITIES, authority_ref)
    if isinstance(insurer_ref, str):
        helpers.resolve_body_ref(store.INSURERS, insurer_ref)

    # rung 7: structure
    body = Body()
    authority = store.AUTHORITIES[body.req_str("authority_id", min_len=None)]
    insurer = store.INSURERS[body.req_str("insurer_id", min_len=None)]
    filing_type = body.req_enum("filing_type", FILING_TYPES)
    coverage_limit = body.req_int("coverage_limit_cents", min_v=1)
    policy_number = body.req_str("policy_number", min_len=1, max_len=64)
    effective_at = body.req_instant("effective_at")
    expected_version = body.req_int("expected_authority_version")
    for existing in store.FILINGS.values():
        if existing["insurer_id"] == insurer["id"] and existing["policy_number"] == policy_number:
            raise invalid("Field 'policy_number' must be unique among this insurer's filings.")

    # rung 8: the authority version guard
    if expected_version != authority["version"]:
        raise ApiError("ERR_STALE_AUTHORITY_VERSION")

    # rung 20: slot occupancy -- supersede the incumbent or refuse outright
    superseded = None
    for incumbent in domain.active_filings(authority["id"], (filing_type,)):
        end = incumbent["cancellation_effective_at"]
        overlaps = end is None or effective_at < end
        if not overlaps:
            continue
        if effective_at > incumbent["effective_at"]:
            superseded = incumbent
        else:
            raise ApiError("ERR_FILING_INTERVAL_OVERLAP")

    # rung 23: the insurer must be admitted where the carrier lives
    carrier = store.CARRIERS[authority["carrier_id"]]
    if carrier["domicile_state"] not in insurer["authorized_states"]:
        raise ApiError("ERR_INSURER_NOT_AUTHORIZED_IN_STATE")

    # rung 28: money last -- the coverage must be adequate
    minimum = domain.required_minimum_for_type(authority, filing_type)
    if coverage_limit < minimum:
        raise ApiError("ERR_INSURANCE_BELOW_MINIMUM")

    if superseded is not None:
        superseded["status"] = "CANCELLED"
        superseded["cancellation_effective_at"] = effective_at
        domain.touch(superseded)

    rec = store.base_record()
    rec.update({
        "authority_id": authority["id"],
        "insurer_id": insurer["id"],
        "supersedes_filing_id": None if superseded is None else superseded["id"],
        "filing_type": filing_type,
        "coverage_limit_cents": coverage_limit,
        "policy_number": policy_number,
        "effective_at": effective_at,
        "cancellation_effective_at": None,
        "status": "ACTIVE",
        "meets_required_minimum": coverage_limit >= minimum,
    })
    store.insert(store.FILINGS, rec)

    domain.recompute_insurance_status(authority)
    return helpers.one(rec, 201)


@bp.get("/insurance-filings/<filing_id>")
def read_filing(filing_id):
    authenticate(ALL_ROLES)
    return helpers.one(helpers.need_filing(filing_id))


@bp.get("/insurance-filings")
def list_filings():
    authenticate(ALL_ROLES)
    return helpers.listing(store.all_of(store.FILINGS), {
        "authority_id": "authority_id",
        "insurer_id": "insurer_id",
        "supersedes_filing_id": "supersedes_filing_id",
        "filing_type": "filing_type",
        "status": "status",
    })


@bp.post("/insurance-filings/<filing_id>/cancel")
def cancel_filing(filing_id):
    uid, role = authenticate(("InsuranceFiler",))
    filing = helpers.need_filing(filing_id)
    helpers.require_filing_party(role, uid, filing["insurer_id"])

    body = Body()
    cancellation_effective_at = body.req_instant("cancellation_effective_at")

    if filing["status"] != "ACTIVE":
        raise ApiError("ERR_FILING_NOT_ACTIVE")

    authority = store.AUTHORITIES.get(filing["authority_id"])
    if authority is not None and authority["authority_status"] in ("REVOKED", "RESCINDED"):
        raise ApiError("ERR_AUTHORITY_INVALID_STATE")

    if cancellation_effective_at < filing["effective_at"]:
        raise invalid("Field 'cancellation_effective_at' must not precede the filing's effective_at.")

    filing["status"] = "CANCELLED"
    filing["cancellation_effective_at"] = cancellation_effective_at
    domain.touch(filing)

    if authority is not None:
        old, new = domain.recompute_insurance_status(authority)
        if new == "LAPSED" and old != "LAPSED":
            domain.open_proceeding(authority, "INSURANCE_LAPSE")
            if authority["authority_status"] == "ACTIVE":
                domain.suspend(authority, "INSURANCE_LAPSE")
    return helpers.one(filing)
