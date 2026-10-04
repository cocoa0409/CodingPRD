"""Community endpoints."""

from flask import Blueprint, request

from db import db, CAPTURE_RATE_TARGET_DEFAULT_BPS
from errors import fail
from response import ok, ok_list, paginate
from checks import (
    authenticate, gate_listing, body, require_fields, int_field, string_field,
    enum_field, state_code_field, get_community,
)
from services import common, calc
from services import contract_flows

bp = Blueprint("communities", __name__)

READ_ROLES = [
    "Anonymous",
    "PlatformAdmin",
    "SalesCounselor",
    "MortgageBanker",
    "ClosingOfficer",
    "ComplianceOfficer",
]
DETAIL_ROLES = [
    "PlatformAdmin",
    "SalesCounselor",
    "MortgageBanker",
    "ClosingOfficer",
    "ComplianceOfficer",
]
WRITE_ROLES = ["PlatformAdmin", "ComplianceOfficer"]


@bp.get("/housing/communities")
def list_communities():
    gate_listing(READ_ROLES)
    rows = common.sort_rows(list(db.communities.values()))
    window, pagination = paginate(
        rows, request.args.get("limit"), request.args.get("offset")
    )
    return ok_list(common.dump_all(window), 200, pagination)


@bp.post("/housing/communities")
def create_community():
    authenticate(WRITE_ROLES)
    payload = body()
    require_fields(
        payload,
        [
            "name",
            "state_code",
            "incentive_policy_code",
            "price_reduction_cap_cents",
            "closing_cost_cap_cents",
            "rate_buydown_cap_cents",
        ],
    )
    name = string_field(payload, "name", 120)
    state_code = state_code_field(payload, "state_code")
    policy = enum_field(payload, "incentive_policy_code", ["STANDARD", "PREMIUM", "CLEARANCE"])
    price_cap = int_field(payload, "price_reduction_cap_cents", minimum=0)
    closing_cap = int_field(payload, "closing_cost_cap_cents", minimum=0)
    buydown_cap = int_field(payload, "rate_buydown_cap_cents", minimum=0)
    if "capture_rate_target_bps" in payload and payload["capture_rate_target_bps"] is not None:
        target = int_field(payload, "capture_rate_target_bps", minimum=0, maximum=10000)
    else:
        target = CAPTURE_RATE_TARGET_DEFAULT_BPS

    row = {
        "id": db.new_id(),
        "name": name,
        "state_code": state_code,
        "incentive_policy_code": policy,
        "capture_rate_target_bps": target,
        "price_reduction_cap_cents": price_cap,
        "closing_cost_cap_cents": closing_cap,
        "rate_buydown_cap_cents": buydown_cap,
        "affiliated_units": 0,
        "funded_units": 0,
        "capture_rate_bps": 0,
        "incentive_spend_cents": 0,
        "forward_units_committed": 0,
        "program_status": "ACTIVE",
    }
    common.stamp_new(row)
    db.communities[row["id"]] = row
    return ok(common.dump(row), 201)


@bp.get("/housing/communities/<community_id>")
def get_community_detail(community_id):
    gate_listing(DETAIL_ROLES)
    community = get_community(community_id)
    # capture_rate_realization runs whenever a community is read (PRD 2.6).
    calc.capture_rate_realization(community)
    return ok(common.dump(community), 200)


@bp.post("/housing/communities/<community_id>/posture")
def set_posture(community_id):
    authenticate(["ComplianceOfficer"])
    community = get_community(community_id)
    payload = body()
    require_fields(payload, ["target_status"])
    target = enum_field(payload, "target_status", ["ACTIVE", "RESTRICTED", "SUSPENDED"])
    current = community.get("program_status")

    if target == "RESTRICTED":
        if current != "ACTIVE":
            fail("ERR_INVALID_STATE", "only an ACTIVE community may be restricted")
        calc.capture_rate_realization(community)
        if not community["capture_rate_bps"] < community["capture_rate_target_bps"]:
            fail("ERR_INVALID_STATE", "the realized capture rate has reached its target")
        community["program_status"] = "RESTRICTED"
        common.touch(community)
    elif target == "ACTIVE":
        if current != "RESTRICTED":
            fail("ERR_INVALID_STATE", "only a RESTRICTED community may be reactivated")
        calc.capture_rate_realization(community)
        if not community["capture_rate_bps"] >= community["capture_rate_target_bps"]:
            fail("ERR_INVALID_STATE", "the realized capture rate is still below its target")
        community["program_status"] = "ACTIVE"
        common.touch(community)
    else:
        if current not in ("ACTIVE", "RESTRICTED"):
            fail("ERR_INVALID_STATE", "the community is already suspended")
        if not _has_curing_disclosure(community_id):
            fail(
                "ERR_INVALID_STATE",
                "suspension requires at least one disclosure in CURING status",
            )
        contract_flows.suspend_community(community)

    calc.capture_rate_realization(community)
    common.touch(community)
    return ok(common.dump(community), 200)


def _has_curing_disclosure(community_id):
    for disclosure in db.disclosures.values():
        if disclosure.get("disclosure_status") != "CURING":
            continue
        contract = db.contracts.get(disclosure.get("contract_id"))
        if contract is None:
            continue
        home = db.home_sites.get(contract.get("home_site_id"))
        if home is not None and home.get("community_id") == community_id:
            return True
    return False


@bp.get("/housing/communities/<community_id>/forward-commitments")
def list_community_commitments(community_id):
    authenticate(["PlatformAdmin", "MortgageBanker", "ComplianceOfficer"])
    get_community(community_id)
    rows = [
        c for c in db.forward_commitments.values() if c.get("community_id") == community_id
    ]
    window, pagination = paginate(
        common.sort_rows(rows), request.args.get("limit"), request.args.get("offset")
    )
    return ok_list(common.dump_all(window), 200, pagination)


@bp.get("/housing/communities/<community_id>/home-sites")
def list_community_home_sites(community_id):
    authenticate(["PlatformAdmin", "SalesCounselor", "MortgageBanker", "ComplianceOfficer"])
    get_community(community_id)
    rows = [h for h in db.home_sites.values() if h.get("community_id") == community_id]
    window, pagination = paginate(
        common.sort_rows(rows), request.args.get("limit"), request.args.get("offset")
    )
    return ok_list(common.dump_all(window), 200, pagination)