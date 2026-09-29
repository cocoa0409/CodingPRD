"""Farmer agreement endpoints (PRD 3.6)."""

from flask import Blueprint, g

import store
from auth import roles
from derive import defer_events_of_agreement
from envelope import object_response
from errors import fail
from listing import emit_list
from store import D, iso, now, now_iso, parse_dt, public, r2, touch
from validate import (get_body, present, qenum, qstr, resolve_fks, vdt, vint, vnum,
                      vstr)

bp = Blueprint("agreements", __name__, url_prefix="/api/v1/farmer-agreements")

AGREEMENT_STATUSES = ("DRAFT", "PROPOSED", "COUNTERED", "SIGNED", "ACTIVE",
                      "TERMINATED", "EXPIRED", "WITHDRAWN")
READ_ROLES = ("Agronomist", "ComplianceOfficer", "Farmer", "FacilityOperator")


def get_agreement(agreement_id):
    agreement = store.agreements.get(agreement_id)
    if agreement is None:
        fail("ERR_AGREEMENT_NOT_FOUND", "Agreement %s does not exist." % agreement_id)
    return agreement


def require_party(agreement):
    if g.user_id != agreement["farmer_user_id"]:
        fail("ERR_ACTOR_NOT_PARTY", "The caller is not the party to this agreement.")


@bp.post("")
@roles("Agronomist")
def create_agreement():
    body = get_body()
    fks = resolve_fks(body, ("site_id",))
    site_id = body.get("site_id")
    if not isinstance(site_id, str) or not site_id.strip():
        fail("ERR_INVALID_REQUEST", "Field 'site_id' is required.")
    site = fks["site_id"]
    expected_site_version = vint(body, "expected_site_version", required=True)
    farmer_user_id = vstr(body, "farmer_user_id", required=True, min_len=1)
    farm_name = vstr(body, "farm_name", required=True, min_len=1, max_len=120)
    term_start = vdt(body, "term_start", required=True)
    term_end = vdt(body, "term_end", required=True)
    if not term_end > term_start:
        fail("ERR_INVALID_REQUEST", "term_end must be strictly after term_start.")
    max_rate = vnum(body, "max_dry_tons_per_acre", required=True, gt=0)
    notice_days = vint(body, "notice_days", required=False, default=14, ge=0)

    if expected_site_version != site["version"]:
        fail("ERR_STALE_SITE_VERSION",
             "Site version is %d but expected_site_version was %d."
             % (site["version"], expected_site_version))

    agreement = store.new_record({
        "site_id": site["id"],
        "farmer_user_id": farmer_user_id,
        "farm_name": farm_name,
        "term_start": iso(term_start),
        "term_end": iso(term_end),
        "max_dry_tons_per_acre": r2(max_rate),
        "notice_days": notice_days,
        "status": "DRAFT",
        "round_index": 0,
        "last_proposed_by_role": "NONE",
        "signed_at": None,
        "terminated_at": None,
        "termination_reason": None,
        "updated_at": now_iso(),
        "version": 1,
    })
    store.agreements[agreement["id"]] = agreement
    touch(site)
    return object_response(public(agreement), 201)


@bp.get("/<agreement_id>")
@roles(*READ_ROLES)
def read_agreement(agreement_id):
    return object_response(public(get_agreement(agreement_id)))


@bp.get("")
@roles(*READ_ROLES)
def list_agreements():
    site_id = qstr("site_id")
    farmer_user_id = qstr("farmer_user_id")
    status = qenum("status", AGREEMENT_STATUSES)
    rows = [a for a in store.agreements.values()
            if (site_id is None or a["site_id"] == site_id)
            and (farmer_user_id is None or a["farmer_user_id"] == farmer_user_id)
            and (status is None or a["status"] == status)]
    return emit_list(rows, ("created_at",))


def _apply_overrides(agreement, body):
    if present(body, "max_dry_tons_per_acre"):
        agreement["max_dry_tons_per_acre"] = r2(
            vnum(body, "max_dry_tons_per_acre", required=True, gt=0))
    if present(body, "notice_days"):
        agreement["notice_days"] = vint(body, "notice_days", required=True, ge=0)


@bp.post("/<agreement_id>/propose")
@roles("Agronomist")
def propose(agreement_id):
    agreement = get_agreement(agreement_id)
    body = get_body()
    if present(body, "max_dry_tons_per_acre"):
        vnum(body, "max_dry_tons_per_acre", required=True, gt=0)
    if present(body, "notice_days"):
        vint(body, "notice_days", required=True, ge=0)
    if agreement["status"] not in ("DRAFT", "COUNTERED"):
        fail("ERR_AGREEMENT_INVALID_STATE",
             "Only a DRAFT or COUNTERED agreement may be proposed.")
    site = store.sites.get(agreement["site_id"])
    if site is None or site["status"] != "PERMITTED":
        fail("ERR_SITE_NOT_PERMITTED", "The anchoring site is not PERMITTED.")
    agreement["status"] = "PROPOSED"
    agreement["last_proposed_by_role"] = "Agronomist"
    _apply_overrides(agreement, body)
    touch(agreement)
    return object_response(public(agreement))


@bp.post("/<agreement_id>/counter")
@roles("Farmer")
def counter(agreement_id):
    agreement = get_agreement(agreement_id)
    body = get_body()
    if present(body, "max_dry_tons_per_acre"):
        vnum(body, "max_dry_tons_per_acre", required=True, gt=0)
    if present(body, "notice_days"):
        vint(body, "notice_days", required=True, ge=0)
    require_party(agreement)
    if agreement["status"] != "PROPOSED":
        fail("ERR_AGREEMENT_INVALID_STATE",
             "Only a PROPOSED agreement may be countered.")
    if not agreement["round_index"] < 3:
        fail("ERR_AGREEMENT_ROUND_LIMIT", "The negotiation round limit is reached.")
    agreement["status"] = "COUNTERED"
    agreement["last_proposed_by_role"] = "Farmer"
    agreement["round_index"] = agreement["round_index"] + 1
    _apply_overrides(agreement, body)
    touch(agreement)
    return object_response(public(agreement))


@bp.post("/<agreement_id>/sign")
@roles("Farmer")
def sign(agreement_id):
    agreement = get_agreement(agreement_id)
    get_body()
    require_party(agreement)
    if agreement["status"] != "PROPOSED":
        fail("ERR_AGREEMENT_INVALID_STATE", "Only a PROPOSED agreement may be signed.")
    if agreement["last_proposed_by_role"] != "Agronomist":
        fail("ERR_AGREEMENT_INVALID_STATE",
             "The standing offer was not made by the Agronomist.")
    agreement["status"] = "SIGNED"
    agreement["signed_at"] = now_iso()
    touch(agreement)
    return object_response(public(agreement))


@bp.post("/<agreement_id>/activate")
@roles("Agronomist")
def activate(agreement_id):
    agreement = get_agreement(agreement_id)
    get_body()
    if agreement["status"] != "SIGNED":
        fail("ERR_AGREEMENT_INVALID_STATE", "Only a SIGNED agreement may be activated.")
    term_start = parse_dt(agreement["term_start"])
    term_end = parse_dt(agreement["term_end"])
    if not (term_start <= now() < term_end):
        fail("ERR_AGREEMENT_INVALID_STATE",
             "The logical clock is outside the agreement term.")
    for other in store.agreements.values():
        if other["id"] == agreement["id"] or other["site_id"] != agreement["site_id"]:
            continue
        if other["status"] != "ACTIVE":
            continue
        other_start = parse_dt(other["term_start"])
        other_end = parse_dt(other["term_end"])
        if term_start < other_end and other_start < term_end:
            fail("ERR_AGREEMENT_TERM_OVERLAP",
                 "Another ACTIVE agreement on this site overlaps this term.")
    agreement["status"] = "ACTIVE"
    touch(agreement)
    return object_response(public(agreement))


@bp.post("/<agreement_id>/withdraw")
@roles("Agronomist")
def withdraw(agreement_id):
    agreement = get_agreement(agreement_id)
    get_body()
    if agreement["status"] not in ("DRAFT", "PROPOSED", "COUNTERED"):
        fail("ERR_AGREEMENT_INVALID_STATE",
             "Only a negotiation in progress may be withdrawn.")
    agreement["status"] = "WITHDRAWN"
    touch(agreement)
    return object_response(public(agreement))


@bp.post("/<agreement_id>/terminate")
@roles("Agronomist", "Farmer")
def terminate(agreement_id):
    agreement = get_agreement(agreement_id)
    body = get_body()
    reason = vstr(body, "termination_reason", required=True, min_len=1)
    if g.role == "Farmer":
        require_party(agreement)
    if agreement["status"] != "ACTIVE":
        fail("ERR_AGREEMENT_INVALID_STATE",
             "Only an ACTIVE agreement may be terminated.")
    agreement["status"] = "TERMINATED"
    agreement["terminated_at"] = now_iso()
    agreement["termination_reason"] = reason
    touch(agreement)
    defer_events_of_agreement(agreement["id"], "AGREEMENT_TERMINATED")
    return object_response(public(agreement))
