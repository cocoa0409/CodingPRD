"""Publications, research partners, access grants and the recognition ledger."""
from decimal import Decimal

from flask import Blueprint

import calc
import clock
import db
import guards
import response
import services
from errors import ApiError

bp = Blueprint("publications", __name__)

ALL_ROLES = ["ProgramAdmin", "Volunteer", "Expert", "ResearchPartner"]
SCOPES = ["AGGREGATE", "FULL", "SENSITIVE"]
TRUST_TIERS = ["STANDARD", "TRUSTED"]
AWARD_TYPES = ["OBSERVATION_ACCEPTED", "STREAK_BONUS", "MILESTONE", "REVERSAL"]


def _page(rows, filters):
    rows = guards.apply_filters(rows, filters)
    page, limit, offset, total = guards.paginate(rows)
    return response.list_response([db.serialize(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------
# Publications
# --------------------------------------------------------------------------
@bp.post("/citizen-science/publications")
def create_publication():
    guards.authenticate(["ProgramAdmin"])
    body = guards.validate_body([
        {"name": "campaign_id", "type": "id", "required": True},
        {"name": "doi", "type": "string", "required": True},
        {"name": "expected_campaign_version", "type": "integer", "required": True},
        {"name": "embargo_until", "type": "datetime", "required": False, "default": None},
    ])
    campaign = guards.get_campaign(body["campaign_id"])

    # priority 12 — optimistic concurrency
    if body["expected_campaign_version"] != campaign["version"]:
        raise ApiError("ERR_STALE_CAMPAIGN_VERSION")

    # priority 25 — publication state
    if campaign["status"] not in ("CLOSED", "PUBLISHED"):
        raise ApiError("ERR_PUBLICATION_STATE_INVALID")

    # priority 48 — uniqueness
    guards.require_unique(db.publications, "doi", body["doi"])

    prior = services.prior_publication(campaign["id"])

    # priority 52 — candidate count, counted AFTER step one would have run
    projected = list(services.candidate_observations(campaign["id"]))
    if prior is not None:
        for obs in services.bound_observations(prior["id"]):
            if obs["publication_status"] == "QUEUED":
                projected.append(obs)
    if len(projected) < calc.MIN_RECORD_FLOOR:
        raise ApiError("ERR_INSUFFICIENT_RECORDS")

    # STEP 1 — supersession runs first
    if prior is not None:
        services.supersede_publication(prior)

    row = db.new_row({
        "campaign_id": campaign["id"],
        "supersedes_publication_id": prior["id"] if prior is not None else None,
        "doi": body["doi"],
        "status": "DRAFT",
        "embargo_until": body["embargo_until"],
        "quality_floor": calc.rnd(Decimal("0.0"), 2),
        "record_count": 0,
        "mean_quality": calc.rnd(Decimal("0.0"), 2),
        "released_at": None,
    })
    db.publications[row["id"]] = row

    # STEP 2 — metrics over the refreshed candidate pool
    candidates = services.candidate_observations(campaign["id"])
    included = services.compute_publication_metrics(row, candidates)

    # STEP 3 — binding; the bound observations sit in QUEUED until release
    for obs in included:
        obs["publication_id"] = row["id"]
        obs["publication_status"] = "QUEUED"
        db.touch(obs)

    db.touch(campaign)
    return response.object_response(db.serialize(row), 201)


@bp.get("/citizen-science/publications")
def list_publications():
    actor = guards.authenticate(ALL_ROLES)
    guards.resolve_actor(actor)
    return _page(db.all_rows(db.publications),
                 ["campaign_id", "supersedes_publication_id", "status"])


@bp.get("/citizen-science/publications/<pid>")
def read_publication(pid):
    actor = guards.authenticate(ALL_ROLES)
    row = guards.get_publication(pid)
    guards.resolve_actor(actor)
    return response.object_response(db.serialize(row))


@bp.post("/citizen-science/publications/<pid>/release")
def release_publication(pid):
    guards.authenticate(["ProgramAdmin"])
    publication = guards.get_publication(pid)
    if publication["status"] != "DRAFT":
        raise ApiError("ERR_PUBLICATION_STATE_INVALID")
    if publication["record_count"] < calc.MIN_RECORD_FLOOR:
        raise ApiError("ERR_INSUFFICIENT_RECORDS")

    embargo = publication["embargo_until"]
    if embargo is None or clock.now() >= embargo:
        services.release_publication(publication)
    else:
        publication["status"] = "EMBARGOED"
        db.touch(publication)
    return response.object_response(db.serialize(publication))


@bp.post("/citizen-science/publications/<pid>/withdraw")
def withdraw_publication(pid):
    guards.authenticate(["ProgramAdmin"])
    publication = guards.get_publication(pid)
    guards.validate_body([
        {"name": "reason", "type": "string", "required": True},
    ])
    if publication["status"] not in ("DRAFT", "EMBARGOED", "RELEASED"):
        raise ApiError("ERR_PUBLICATION_STATE_INVALID")
    services.withdraw_publication(publication)
    return response.object_response(db.serialize(publication))


# --------------------------------------------------------------------------
# Research partners
# --------------------------------------------------------------------------
@bp.post("/citizen-science/partners")
def create_partner():
    guards.authenticate(["ProgramAdmin"])
    body = guards.validate_body([
        {"name": "org_name", "type": "string", "required": True},
        {"name": "contact_email", "type": "string", "required": True},
        {"name": "trust_tier", "type": "enum", "required": False,
         "values": TRUST_TIERS, "default": "STANDARD"},
        {"name": "data_use_agreement_signed_at", "type": "datetime",
         "required": False, "default": None},
    ])
    guards.require_unique(db.partners, "org_name", body["org_name"])
    row = db.new_row({
        "org_name": body["org_name"],
        "contact_email": body["contact_email"],
        "status": "PENDING",
        "data_use_agreement_signed_at": body["data_use_agreement_signed_at"],
        "trust_tier": body["trust_tier"],
        "active_grant_count": 0,
    })
    db.partners[row["id"]] = row
    return response.object_response(db.serialize(row), 201)


@bp.get("/citizen-science/partners")
def list_partners():
    guards.authenticate(["ProgramAdmin"])
    return _page(db.all_rows(db.partners), ["status", "trust_tier"])


@bp.get("/citizen-science/partners/<pid>")
def read_partner(pid):
    actor = guards.authenticate(["ProgramAdmin", "ResearchPartner"])
    row = guards.get_partner(pid)
    guards.resolve_actor(actor)
    return response.object_response(db.serialize(row))


@bp.post("/citizen-science/partners/<pid>/approve")
def approve_partner(pid):
    guards.authenticate(["ProgramAdmin"])
    partner = guards.get_partner(pid)
    if partner["status"] not in ("PENDING", "SUSPENDED"):
        raise ApiError("ERR_PARTNER_NOT_APPROVED")
    partner["status"] = "APPROVED"
    db.touch(partner)
    return response.object_response(db.serialize(partner))


# --------------------------------------------------------------------------
# Partner access grants
# --------------------------------------------------------------------------
@bp.post("/citizen-science/access-grants")
def create_grant():
    actor = guards.authenticate(["ProgramAdmin", "ResearchPartner"])
    guards.resolve_actor(actor)
    body = guards.validate_body([
        {"name": "publication_id", "type": "id", "required": True},
        {"name": "partner_id", "type": "id", "required": True},
        {"name": "scope", "type": "enum", "required": True, "values": SCOPES},
        {"name": "expires_at", "type": "datetime", "required": True},
    ])
    guards.get_publication(body["publication_id"])
    partner = guards.get_partner(body["partner_id"])

    # priority 8 — ownership
    if actor["role"] == "ResearchPartner" and partner["id"] != actor["id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    # priority 46 — expiry in the future
    if not body["expires_at"] > clock.now():
        raise ApiError("ERR_GRANT_EXPIRY_IN_PAST")

    row = db.new_row({
        "publication_id": body["publication_id"],
        "partner_id": partner["id"],
        "scope": body["scope"],
        "status": "REQUESTED",
        "expires_at": body["expires_at"],
        "denied_reason": "NONE",
    })
    db.grants[row["id"]] = row
    return response.object_response(db.serialize(row), 201)


@bp.get("/citizen-science/access-grants")
def list_grants():
    actor = guards.authenticate(["ProgramAdmin", "ResearchPartner"])
    guards.resolve_actor(actor)
    return _page(db.all_rows(db.grants), ["publication_id", "partner_id", "status"])


@bp.get("/citizen-science/access-grants/<pid>")
def read_grant(pid):
    actor = guards.authenticate(["ProgramAdmin", "ResearchPartner"])
    row = guards.get_grant(pid)
    guards.resolve_actor(actor)
    return response.object_response(db.serialize(row))


@bp.post("/citizen-science/access-grants/<pid>/approve")
def approve_grant(pid):
    guards.authenticate(["ProgramAdmin"])
    grant = guards.get_grant(pid)

    # priority 26 — grant state
    if grant["status"] != "REQUESTED":
        raise ApiError("ERR_GRANT_STATE_INVALID")

    partner = db.partners.get(grant["partner_id"])
    publication = db.publications.get(grant["publication_id"])

    # priority 27 — partner standing
    if partner is None or partner["status"] != "APPROVED":
        raise ApiError("ERR_PARTNER_NOT_APPROVED")

    # priority 38 — sensitive scope
    if grant["scope"] == "SENSITIVE" and partner["trust_tier"] != "TRUSTED":
        raise ApiError("ERR_SCOPE_NOT_PERMITTED")

    # priority 39 — data use agreement
    if grant["scope"] in ("FULL", "SENSITIVE") and partner["data_use_agreement_signed_at"] is None:
        raise ApiError("ERR_DUA_NOT_SIGNED")

    # priority 46 — expiry in the future
    if not grant["expires_at"] > clock.now():
        raise ApiError("ERR_GRANT_EXPIRY_IN_PAST")

    # priority 47 — embargo scope
    if publication is not None and publication["status"] == "EMBARGOED" \
            and grant["scope"] != "AGGREGATE":
        raise ApiError("ERR_EMBARGO_ACTIVE")

    if publication is None or publication["status"] not in ("RELEASED", "EMBARGOED"):
        raise ApiError("ERR_PUBLICATION_STATE_INVALID")

    grant["status"] = "APPROVED"
    db.touch(grant)
    partner["active_grant_count"] += 1
    db.touch(partner)
    return response.object_response(db.serialize(grant))


@bp.post("/citizen-science/access-grants/<pid>/revoke")
def revoke_grant(pid):
    guards.authenticate(["ProgramAdmin"])
    grant = guards.get_grant(pid)
    if grant["status"] != "APPROVED":
        raise ApiError("ERR_GRANT_STATE_INVALID")
    grant["status"] = "REVOKED"
    grant["denied_reason"] = "ADMIN_REVOKED"
    db.touch(grant)
    partner = db.partners.get(grant["partner_id"])
    if partner is not None:
        partner["active_grant_count"] = max(0, partner["active_grant_count"] - 1)
        db.touch(partner)
    return response.object_response(db.serialize(grant))


# --------------------------------------------------------------------------
# Recognition awards
# --------------------------------------------------------------------------
@bp.get("/citizen-science/awards")
def list_awards():
    actor = guards.authenticate(["ProgramAdmin", "Volunteer"])
    guards.resolve_actor(actor)
    return _page(db.all_rows(db.awards), ["volunteer_id", "observation_id", "award_type"])


@bp.get("/citizen-science/awards/<pid>")
def read_award(pid):
    actor = guards.authenticate(["ProgramAdmin", "Volunteer"])
    row = guards.get_award(pid)
    guards.resolve_actor(actor)
    return response.object_response(db.serialize(row))
