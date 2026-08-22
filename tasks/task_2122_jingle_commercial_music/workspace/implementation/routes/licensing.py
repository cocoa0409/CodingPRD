"""Licence drafting, negotiation, issuance, re-use and renewal (PRD 3.6, 3.7)."""

from flask import Blueprint, g, request

import clock
import cue
import db
import licensing
import response
import validators as v
from auth import ALL_ROLES, endpoint, require_project_owner
from errors import ApiError

bp = Blueprint("licensing", __name__)


def _check_term_coherence(structure, term_months_present):
    if structure == "TERM" and not term_months_present:
        raise ApiError("ERR_TERM_MONTHS_REQUIRED", "term_months is required for a TERM grant.")
    if structure == "BUYOUT" and term_months_present:
        raise ApiError("ERR_TERM_MONTHS_REQUIRED", "term_months is forbidden on a BUYOUT grant.")


@bp.post("/license-deals")
@endpoint(["RightsAdmin"])
def create_license_deal():
    body = v.get_body()
    project = None
    demo = None
    if v.present(body, "project_id"):
        project = v.body_lookup(db.projects, body["project_id"], "ERR_PROJECT_NOT_FOUND")
    if v.present(body, "demo_id"):
        demo = v.body_lookup(db.demos, body["demo_id"], "ERR_DEMO_NOT_FOUND")

    v.v_string(body, "project_id")
    v.v_string(body, "demo_id")
    structure = v.v_enum(body, "license_structure", ("BUYOUT", "TERM"))
    term_months = v.v_int(body, "term_months", required=False, default=None,
                          choices=licensing.TERM_MONTHS_ALLOWED)
    market_codes = v.v_array(body, "market_codes", item="string")
    creative_fee_cents = v.v_int(body, "creative_fee_cents", minimum=1)
    expected_project_version = v.v_int(body, "expected_project_version")

    licensing.check_market_codes(market_codes)
    _check_term_coherence(structure, v.present(body, "term_months"))

    if project["status"] != "IN_PRODUCTION":
        raise ApiError("ERR_PROJECT_NOT_IN_PRODUCTION")

    if expected_project_version != project["version"]:
        raise ApiError("ERR_STALE_PROJECT_VERSION")

    if demo["status"] != "SELECTED" or demo["project_id"] != project["id"]:
        raise ApiError("ERR_DEMO_NOT_SELECTED")

    for superseded in db.by_created([d for d in db.license_deals.values()
                                     if d["project_id"] == project["id"]
                                     and d["status"] in ("DRAFT", "PROPOSED")]):
        superseded["status"] = "SUPERSEDED"
        db.touch(superseded)

    record = db.create(db.license_deals, {
        "project_id": project["id"],
        "demo_id": demo["id"],
        "license_structure": structure,
        "term_months": term_months,
        "market_codes": market_codes,
        "creative_fee_cents": creative_fee_cents,
        "license_fee_quoted_cents": 0,
        "license_fee_invoiced_cents": 0,
        "renewal_count": 0,
        "renewal_fee_cents": 0,
        "counter_round_count": 0,
        "effective_start_utc": None,
        "effective_end_utc": None,
        "drafted_by_user_id": g.user_id,
        "activated_by_user_id": None,
        "status": "DRAFT",
        "_effective_start_dt": None,
        "_effective_end_dt": None,
    })
    record["license_fee_quoted_cents"] = licensing.quoted_fee(record)

    # A successful draft increments the engagement's version by 1 (PRD 2.8).
    db.touch(project)

    return response.created(db.serialize(record))


@bp.get("/license-deals/<deal_id>")
@endpoint(ALL_ROLES)
def get_license_deal(deal_id):
    deal = v.path_lookup(db.license_deals, deal_id, "ERR_LICENSE_DEAL_NOT_FOUND")
    return response.ok(db.serialize(deal))


@bp.get("/license-deals")
@endpoint(ALL_ROLES)
def list_license_deals():
    rows = list(db.license_deals.values())
    project_id = request.args.get("project_id")
    demo_id = request.args.get("demo_id")
    status = request.args.get("status")
    if project_id:
        rows = [r for r in rows if r["project_id"] == project_id]
    if demo_id:
        rows = [r for r in rows if r["demo_id"] == demo_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    items, meta = v.paginate(db.by_created(rows))
    return response.ok_list(items, meta)


@bp.post("/license-deals/<deal_id>/propose")
@endpoint(["RightsAdmin"])
def propose_license_deal(deal_id):
    deal = v.path_lookup(db.license_deals, deal_id, "ERR_LICENSE_DEAL_NOT_FOUND")
    if deal["status"] != "DRAFT":
        raise ApiError("ERR_LICENSE_DEAL_INVALID_STATE")
    deal["status"] = "PROPOSED"
    deal["license_fee_quoted_cents"] = licensing.quoted_fee(deal)
    db.touch(deal)
    return response.ok(db.serialize(deal))


@bp.post("/license-deals/<deal_id>/counter")
@endpoint(["ClientRep"])
def counter_license_deal(deal_id):
    deal = v.path_lookup(db.license_deals, deal_id, "ERR_LICENSE_DEAL_NOT_FOUND")
    project = db.projects[deal["project_id"]]
    require_project_owner(project)

    body = v.get_body()
    v.v_string(body, "counter_note")
    market_codes = v.v_array(body, "market_codes", item="string")
    term_months = v.v_int(body, "term_months", required=False, default=None,
                          choices=licensing.TERM_MONTHS_ALLOWED)

    licensing.check_market_codes(market_codes)
    _check_term_coherence(deal["license_structure"], v.present(body, "term_months"))

    if deal["status"] != "PROPOSED":
        raise ApiError("ERR_LICENSE_DEAL_INVALID_STATE")
    if deal["counter_round_count"] >= licensing.MAX_COUNTER_ROUNDS:
        raise ApiError("ERR_COUNTER_LIMIT_REACHED")

    deal["status"] = "DRAFT"
    deal["counter_round_count"] += 1
    deal["term_months"] = term_months
    deal["market_codes"] = market_codes
    deal["license_fee_quoted_cents"] = licensing.quoted_fee(deal)
    db.touch(deal)
    return response.ok(db.serialize(deal))


@bp.post("/license-deals/<deal_id>/accept")
@endpoint(["ClientRep"])
def accept_license_deal(deal_id):
    deal = v.path_lookup(db.license_deals, deal_id, "ERR_LICENSE_DEAL_NOT_FOUND")
    project = db.projects[deal["project_id"]]
    require_project_owner(project)
    if deal["status"] != "PROPOSED":
        raise ApiError("ERR_LICENSE_DEAL_INVALID_STATE")
    deal["status"] = "ACCEPTED"
    db.touch(deal)
    return response.ok(db.serialize(deal))


@bp.post("/license-deals/<deal_id>/activate")
@endpoint(["RightsAdmin"])
def activate_license_deal(deal_id):
    deal = v.path_lookup(db.license_deals, deal_id, "ERR_LICENSE_DEAL_NOT_FOUND")

    # Segregation of duties is judged before target state (PRD 2.5 step 6).
    if g.user_id == deal["drafted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if deal["status"] != "ACCEPTED":
        raise ApiError("ERR_LICENSE_DEAL_INVALID_STATE")

    deal["status"] = "ACTIVE"
    deal["activated_by_user_id"] = g.user_id
    licensing.stamp_effective_window(deal, clock.now())
    deal["license_fee_invoiced_cents"] = licensing.invoiced_fee(deal)
    db.touch(deal)
    return response.ok(db.serialize(deal))


@bp.post("/license-deals/<deal_id>/renew")
@endpoint(["RightsAdmin"])
def renew_license_deal(deal_id):
    deal = v.path_lookup(db.license_deals, deal_id, "ERR_LICENSE_DEAL_NOT_FOUND")
    if deal["status"] != "RENEWAL_DUE" or deal["license_structure"] != "TERM":
        raise ApiError("ERR_LICENSE_NOT_RENEWABLE")

    deal["renewal_fee_cents"] = licensing.renewal_fee(deal)
    deal["renewal_count"] += 1
    deal["status"] = "ACTIVE"
    licensing.stamp_effective_window(deal, clock.now())
    deal["license_fee_invoiced_cents"] = licensing.invoiced_fee(deal)
    db.touch(deal)
    return response.ok(db.serialize(deal))


@bp.post("/license-deals/<deal_id>/reuse-extensions")
@endpoint(["RightsAdmin"])
def create_reuse_extension(deal_id):
    deal = v.path_lookup(db.license_deals, deal_id, "ERR_LICENSE_DEAL_NOT_FOUND")
    body = v.get_body()
    market_code = v.v_string(body, "market_code")
    expected_version = v.v_int(body, "expected_license_deal_version")

    licensing.check_market_codes([market_code])

    if deal["status"] != "ACTIVE":
        raise ApiError("ERR_LICENSE_NOT_ACTIVE")

    if expected_version != deal["version"]:
        raise ApiError("ERR_STALE_LICENSE_DEAL_VERSION")

    if market_code in deal["market_codes"]:
        raise ApiError("ERR_MARKET_ALREADY_LICENSED")

    fee = licensing.reuse_fee(market_code)
    record = db.create(db.reuse_extensions, {
        "license_deal_id": deal["id"],
        "market_code": market_code,
        "market_tier": fee["market_tier"],
        "reuse_base_cents": fee["reuse_base_cents"],
        "admin_pct": fee["admin_pct"],
        "admin_fee_cents": fee["admin_fee_cents"],
        "reuse_total_cents": fee["reuse_total_cents"],
        "status": "ACTIVE",
    })

    deal["market_codes"] = list(deal["market_codes"]) + [market_code]
    deal["license_fee_invoiced_cents"] = licensing.invoiced_fee(deal)
    db.touch(deal)

    return response.created(db.serialize(record))


@bp.get("/license-deals/<deal_id>/reuse-extensions")
@endpoint(ALL_ROLES)
def list_reuse_extensions(deal_id):
    deal = v.path_lookup(db.license_deals, deal_id, "ERR_LICENSE_DEAL_NOT_FOUND")
    rows = [r for r in db.reuse_extensions.values() if r["license_deal_id"] == deal["id"]]
    items, meta = v.paginate(db.by_created(rows))
    return response.ok_list(items, meta)


@bp.post("/license-deals/<deal_id>/deliverables")
@endpoint(["MusicHouseProducer"])
def create_deliverable(deal_id):
    deal = v.path_lookup(db.license_deals, deal_id, "ERR_LICENSE_DEAL_NOT_FOUND")

    if deal["status"] not in ("ACCEPTED", "ACTIVE", "RENEWAL_DUE"):
        raise ApiError("ERR_LICENSE_DEAL_INVALID_STATE")

    for existing in db.deliverables.values():
        if existing["license_deal_id"] == deal["id"]:
            raise ApiError("ERR_DELIVERABLE_ALREADY_EXISTS")

    record = db.create(db.deliverables, {
        "license_deal_id": deal["id"],
        "master_status": "PENDING",
        "cuesheet_status": "NOT_FILED",
        "delivered_lengths": [],
        "stem_manifest": [],
        "unallocated_bps": cue.CUE_TOTAL_BPS,
        "registered_at": None,
    })
    return response.created(db.serialize(record))


@bp.get("/license-deals/<deal_id>/deliverables")
@endpoint(ALL_ROLES)
def list_deliverables(deal_id):
    deal = v.path_lookup(db.license_deals, deal_id, "ERR_LICENSE_DEAL_NOT_FOUND")
    rows = [r for r in db.deliverables.values() if r["license_deal_id"] == deal["id"]]
    items, meta = v.paginate(db.by_created(rows))
    return response.ok_list(items, meta)
