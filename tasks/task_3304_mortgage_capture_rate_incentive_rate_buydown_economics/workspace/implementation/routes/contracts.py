"""HomeSaleContract endpoints and the lock/approve/close/cancel/reinstate paths."""

from flask import Blueprint, request

from db import db
from errors import fail
from response import ok, ok_list, paginate
from checks import (
    authenticate, body, require_fields, int_field, enum_field, get_community,
    get_home_site, get_buyer, get_contract, get_application, get_rate_lock,
    require_state, check_buyer_ownership, contract_owner_id,
)
from services import common, calc, selectors, cascades
from services import contract_flows, lock_flows

bp = Blueprint("contracts", __name__)

READ_ROLES = [
    "PlatformAdmin",
    "SalesCounselor",
    "MortgageBanker",
    "ClosingOfficer",
    "ComplianceOfficer",
    "Buyer",
]
CANCEL_REASONS = ["BUYER_DEFAULT", "CONSTRUCTION_DELAY", "FINANCING_DENIED", "RATE_SHOCK"]


@bp.post("/housing/home-sites/<home_site_id>/contracts")
def create_contract(home_site_id):
    authenticate(["SalesCounselor"])
    home_site = get_home_site(home_site_id)
    payload = body()
    require_fields(payload, ["buyer_id", "purchase_price_cents", "earnest_money_cents"])
    buyer = get_buyer(payload["buyer_id"])
    purchase_price = int_field(payload, "purchase_price_cents", minimum=1)
    earnest_money = int_field(payload, "earnest_money_cents", minimum=1)

    community = get_community(home_site.get("community_id"))
    # Priority 5 before priority 10.
    if home_site.get("home_site_status") != "AVAILABLE":
        fail("ERR_HOME_SITE_NOT_AVAILABLE", "the home site is not AVAILABLE")
    if community.get("program_status") == "SUSPENDED":
        fail("ERR_COMMUNITY_SUSPENDED", "the community is suspended")

    row = {
        "id": db.new_id(),
        "home_site_id": home_site_id,
        "buyer_id": buyer["id"],
        "purchase_price_cents": purchase_price,
        "earnest_money_cents": earnest_money,
        "deposit_held_cents": 0,
        "incentive_budget_cents": 0,
        "incentive_allocated_cents": 0,
        "contract_status": "PENDING",
        "cancellation_reason": None,
    }
    common.stamp_new(row)
    db.contracts[row["id"]] = row
    common.recompute_incentive_budget(row)
    common.touch(row)

    home_site["home_site_status"] = "UNDER_CONTRACT"
    common.touch(home_site)
    calc.capture_rate_realization(community)
    common.touch(community)
    return ok(common.dump(row), 201)


@bp.get("/housing/contracts/<contract_id>")
def get_contract_detail(contract_id):
    authenticate(READ_ROLES)
    contract = get_contract(contract_id)
    check_buyer_ownership(contract, "buyer_id")
    return ok(common.dump(contract), 200)


@bp.post("/housing/contracts/<contract_id>/lock")
def lock_contract(contract_id):
    authenticate(["MortgageBanker"])
    contract = get_contract(contract_id)
    if contract.get("contract_status") != "PENDING":
        fail("ERR_INVALID_STATE", "only a PENDING contract may be locked")
    application = selectors.rate_lock_application_selector(contract)
    if application.get("application_status") != "QUALIFIED":
        fail("ERR_INVALID_STATE", "the contract has no application in QUALIFIED status")
    active = [
        l for l in lock_flows.locks_of_application(application["id"]) if l.get("lock_status") == "ACTIVE"
    ]
    if not active:
        fail("ERR_INVALID_STATE", "the contract has no ACTIVE rate lock")
    commitment = db.forward_commitments.get(active[0].get("commitment_id"))
    if commitment is None or commitment.get("commitment_status") != "OPEN":
        fail("ERR_INVALID_STATE", "the selected lock was not created against an OPEN commitment")
    contract_flows.contract_lock(contract)
    return ok(common.dump(contract), 200)


@bp.post("/housing/contracts/<contract_id>/approve")
def approve_contract(contract_id):
    authenticate(["ComplianceOfficer"])
    contract = get_contract(contract_id)
    if contract.get("contract_status") != "LOCKED":
        fail("ERR_INVALID_STATE", "only a LOCKED contract may be approved")
    for alloc in common.allocations_of_contract(contract_id):
        if alloc.get("allocation_status") not in ("RESERVED", "APPLIED"):
            fail(
                "ERR_INVALID_STATE",
                "every incentive allocation must be RESERVED or APPLIED before approval",
            )
    # Priority 6: rate-buydown obligation requires an acknowledged ABA disclosure.
    has_rate_buydown = any(
        a.get("bucket") == "RATE_BUYDOWN" and a.get("allocation_status") in ("RESERVED", "APPLIED")
        for a in common.allocations_of_contract(contract_id)
    )
    if has_rate_buydown and not common.has_acknowledged_disclosure(
        contract_id, "AFFILIATED_BUSINESS_ARRANGEMENT"
    ):
        fail(
            "ERR_ABA_DISCLOSURE_MISSING",
            "a rate-buydown allocation requires an ACKNOWLEDGED affiliated-business disclosure",
        )
    if common.buyer_has_rate_buydown_bearing_contract(
        contract.get("buyer_id"), exclude_contract_id=contract_id
    ) and not common.has_acknowledged_disclosure(
        contract_id, "AFFILIATED_BUSINESS_ARRANGEMENT"
    ):
        fail(
            "ERR_ABA_DISCLOSURE_MISSING",
            "every rate-buydown-bearing contract needs an ACKNOWLEDGED ABA disclosure",
        )
    contract_flows.contract_approve(contract)
    return ok(common.dump(contract), 200)


@bp.post("/housing/contracts/<contract_id>/close")
def close_contract(contract_id):
    authenticate(["ClosingOfficer"])
    contract = get_contract(contract_id)
    if contract.get("contract_status") != "APPROVED":
        fail("ERR_INVALID_STATE", "only an APPROVED contract may be closed")
    home_site = db.home_sites.get(contract.get("home_site_id"))
    if home_site is None or home_site.get("home_site_status") != "UNDER_CONTRACT":
        fail("ERR_INVALID_STATE", "the home site is not UNDER_CONTRACT")
    contract_flows.contract_close(contract)
    return ok(common.dump(contract), 200)


@bp.post("/housing/contracts/<contract_id>/cancel")
def cancel_contract(contract_id):
    authenticate(["SalesCounselor"])
    contract = get_contract(contract_id)
    if contract.get("contract_status") not in ("PENDING", "LOCKED", "APPROVED"):
        fail("ERR_INVALID_STATE", "only a PENDING, LOCKED or APPROVED contract may be cancelled")
    payload = body()
    require_fields(payload, ["cancellation_reason"])
    reason = enum_field(payload, "cancellation_reason", CANCEL_REASONS)
    contract["cancellation_reason"] = reason
    statute_class = selectors.deposit_statute_class_selector(contract)
    contract_flows.contract_cancel(contract, reason, statute_class)
    return ok(common.dump(contract), 200)


@bp.post("/housing/contracts/<contract_id>/reinstate")
def reinstate_contract(contract_id):
    authenticate(["SalesCounselor"])
    contract = get_contract(contract_id)
    if contract.get("contract_status") != "CANCELLED":
        fail("ERR_INVALID_STATE", "only a CANCELLED contract may be reinstated")
    home_site = db.home_sites.get(contract.get("home_site_id"))
    if home_site is None or home_site.get("home_site_status") != "AVAILABLE":
        fail("ERR_INVALID_STATE", "the home site has not returned to AVAILABLE")
    for row in common.forfeitures_of_contract(contract_id):
        if row.get("forfeiture_status") == "FINALIZED":
            fail("ERR_INVALID_STATE", "a finalized forfeiture blocks reinstatement")
        if row.get("forfeiture_status") != "PROPOSED":
            fail("ERR_INVALID_STATE", "every settlement must still be PROPOSED")
    contract_flows.contract_reinstate(contract)
    return ok(common.dump(contract), 200)


# ---------------------------------------------------------------------------
# Nested reads
# ---------------------------------------------------------------------------
@bp.get("/housing/contracts/<contract_id>/loan-applications")
def list_contract_applications(contract_id):
    authenticate(READ_ROLES)
    contract = get_contract(contract_id)
    check_buyer_ownership(contract, "buyer_id")
    window, pagination = paginate(
        common.sort_rows(common.applications_of_contract(contract_id)),
        request.args.get("limit"), request.args.get("offset"),
    )
    return ok_list(common.dump_all(window), 200, pagination)


@bp.get("/housing/contracts/<contract_id>/incentive-allocations")
def list_contract_allocations(contract_id):
    authenticate(READ_ROLES)
    contract = get_contract(contract_id)
    check_buyer_ownership(contract, "buyer_id")
    window, pagination = paginate(
        common.sort_rows(common.allocations_of_contract(contract_id)),
        request.args.get("limit"), request.args.get("offset"),
    )
    return ok_list(common.dump_all(window), 200, pagination)


@bp.get("/housing/contracts/<contract_id>/buydown-records")
def list_contract_buydowns(contract_id):
    authenticate(["PlatformAdmin", "SalesCounselor", "ClosingOfficer", "ComplianceOfficer"])
    get_contract(contract_id)
    window, pagination = paginate(
        common.sort_rows(common.buydowns_of_contract(contract_id)),
        request.args.get("limit"), request.args.get("offset"),
    )
    return ok_list(common.dump_all(window), 200, pagination)


@bp.get("/housing/contracts/<contract_id>/disclosures")
def list_contract_disclosures(contract_id):
    authenticate(READ_ROLES)
    contract = get_contract(contract_id)
    check_buyer_ownership(contract, "buyer_id")
    rows = common.disclosures_of_contract(contract_id)
    window, pagination = paginate(
        common.sort_rows(rows), request.args.get("limit"), request.args.get("offset")
    )
    return ok_list(common.dump_all(window), 200, pagination)


@bp.get("/housing/contracts/<contract_id>/deposit-forfeitures")
def list_contract_forfeitures(contract_id):
    authenticate(["PlatformAdmin", "ClosingOfficer", "ComplianceOfficer"])
    get_contract(contract_id)
    window, pagination = paginate(
        common.sort_rows(common.forfeitures_of_contract(contract_id)),
        request.args.get("limit"), request.args.get("offset"),
    )
    return ok_list(common.dump_all(window), 200, pagination)