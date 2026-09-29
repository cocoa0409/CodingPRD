"""Purchase agreements, the escrow ledger, execution and settlement (PRD 3.4-3.8)."""

from flask import Blueprint

import calc
import domain
from authz import (ALL_ROLES, BROKER, BUYER, ESCROW_OFFICER, PLATFORM_ADMIN, REGULATOR,
                   SELLER, agreement_or_404, authenticate, buyer_or_404, county_or_404,
                   entry_or_404, license_or_404, listing_or_404, premises_or_404,
                   require_brokerage, require_buyer)
from envelope import apply_filters, created, ok, ok_list, pagination_args, paginate
from errors import ApiError
from store import (add_days, bump, db, make_record, now, public, public_list,
                   sorted_by_created, sorted_ledger)
from validation import F, json_body, validate

bp = Blueprint("agreements", __name__)

AGREEMENT_TERMINAL = ("CLOSED", "TERMINATED")
ESCROW_SETTLED = ("RELEASED", "REFUNDED", "FORFEITED")
DISPOSITIONS = ("RELEASE", "REFUND", "FORFEIT")
ENTRY_TYPES = ("DEPOSIT", "RELEASE_COUNTY_FEE", "RELEASE_COMMISSION", "RELEASE_SELLER",
               "REFUND_BUYER", "FORFEIT_SELLER")
IN_FLIGHT_APPLICATION = ("SUBMITTED", "UNDER_REVIEW", "DEFICIENT", "POSTED", "PROTESTED")


def escrow_guard_not_settled(agreement):
    """The money dimension must not have been settled yet (PRD 3.4 / 3.8)."""
    if agreement["escrow_status"] in ESCROW_SETTLED:
        raise ApiError("ERR_ESCROW_ALREADY_SETTLED", "The escrow has already been settled.")


# --- drafting -------------------------------------------------------------
@bp.route("/purchase-agreements", methods=["POST"])
def create_agreement():
    user_id, role = authenticate((BROKER,))
    data = validate(json_body(), [
        F("listing_id", "string"),
        F("buyer_id", "string"),
        F("premises_id", "string"),
        F("purchase_price_cents", "integer", minimum=100000),
        F("deposit_pct_bps", "integer", minimum=500, maximum=3500),
        F("closing_window_start", "datetime"),
        F("expected_listing_version", "integer"),
        F("contingency_days", "integer", required=False, default=120, minimum=30, maximum=365),
    ])
    listing = listing_or_404(data["listing_id"])
    buyer = buyer_or_404(data["buyer_id"])
    premises = premises_or_404(data["premises_id"])
    require_brokerage(user_id, role, listing["brokerage_id"])
    if listing["version"] != data["expected_listing_version"]:
        raise ApiError("ERR_STALE_LISTING_VERSION",
                       "The listing has moved since it was last observed.")
    if listing["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_LISTING_STATE",
                       "An agreement may only be drafted against an ACTIVE listing.")
    lic = license_or_404(listing["license_id"])
    start = data["closing_window_start"]
    deadline = add_days(start, data["contingency_days"])
    for other in db.agreements.values():
        if other["license_id"] != lic["id"]:
            continue
        if other["agreement_status"] not in ("DRAFT", "EXECUTED"):
            continue
        if start < other["contingency_deadline_at"] and other["closing_window_start"] < deadline:
            raise ApiError("ERR_LICENSE_CONTRACT_OVERLAP",
                           "Another agreement already reserves that window on this license.")
    required = calc.escrow_deposit_requirement(
        data["purchase_price_cents"], data["deposit_pct_bps"], lic["license_class"],
        listing["scarcity_bps_at_activation"])
    agreement = make_record({
        "listing_id": listing["id"],
        "buyer_id": buyer["id"],
        "premises_id": premises["id"],
        "brokerage_id": listing["brokerage_id"],
        "license_id": lic["id"],
        "seller_id": lic["owner_seller_id"],
        "purchase_price_cents": data["purchase_price_cents"],
        "deposit_pct_bps": data["deposit_pct_bps"],
        "required_deposit_cents": required,
        "closing_window_start": start,
        "contingency_days": data["contingency_days"],
        "contingency_deadline_at": deadline,
        "agreement_status": "DRAFT",
        "escrow_status": "AWAITING_DEPOSIT",
        "escrow_balance_cents": 0,
        "commission_mode": None,
        "commission_total_cents": None,
        "county_transfer_fee_cents": None,
        "seller_net_cents": None,
        "executed_at": None,
        "settled_at": None,
        "termination_reason": None,
    })
    db.agreements[agreement["id"]] = agreement
    listing["open_offer_count"] = listing["open_offer_count"] + 1
    bump(listing)
    return created(public(agreement))


@bp.route("/purchase-agreements/<agreement_id>", methods=["GET"])
def get_agreement(agreement_id):
    authenticate(ALL_ROLES)
    return ok(public(agreement_or_404(agreement_id)))


@bp.route("/purchase-agreements", methods=["GET"])
def list_agreements():
    authenticate(ALL_ROLES)
    limit, offset = pagination_args()
    rows = apply_filters(db.agreements.values(), {
        "listing_id": "listing_id",
        "buyer_id": "buyer_id",
        "premises_id": "premises_id",
        "brokerage_id": "brokerage_id",
        "license_id": "license_id",
        "seller_id": "seller_id",
        "agreement_status": "agreement_status",
        "escrow_status": "escrow_status",
    })
    rows = sorted_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


# --- ledger reads ---------------------------------------------------------
@bp.route("/purchase-agreements/<agreement_id>/escrow-ledger", methods=["GET"])
def agreement_ledger(agreement_id):
    authenticate(ALL_ROLES)
    agreement = agreement_or_404(agreement_id)
    limit, offset = pagination_args()
    rows = [r for r in db.ledger.values() if r["agreement_id"] == agreement["id"]]
    rows = apply_filters(rows, {"entry_type": "entry_type"})
    rows = sorted_ledger(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@bp.route("/escrow-ledger-entries/<entry_id>", methods=["GET"])
def get_ledger_entry(entry_id):
    authenticate(ALL_ROLES)
    return ok(public(entry_or_404(entry_id)))


@bp.route("/escrow-ledger-entries", methods=["GET"])
def list_ledger_entries():
    authenticate(ALL_ROLES)
    limit, offset = pagination_args()
    rows = apply_filters(db.ledger.values(), {
        "agreement_id": "agreement_id",
        "entry_type": "entry_type",
    })
    rows = sorted_ledger(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@bp.route("/purchase-agreements/<agreement_id>/dual-agency-disclosures", methods=["GET"])
def agreement_disclosures(agreement_id):
    authenticate((PLATFORM_ADMIN, BROKER, BUYER, SELLER, REGULATOR))
    agreement = agreement_or_404(agreement_id)
    limit, offset = pagination_args()
    rows = domain.disclosures_of(agreement["id"])
    rows = apply_filters(rows, {"status": "status"})
    rows = sorted_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


# --- funding the escrow (PRD 3.4) ----------------------------------------
@bp.route("/purchase-agreements/<agreement_id>/escrow-deposit", methods=["POST"])
def escrow_deposit(agreement_id):
    user_id, role = authenticate((BUYER, ESCROW_OFFICER))
    data = validate(json_body(), [
        F("amount_cents", "integer"),
        F("deposit_reference", "string", required=False, default=None),
    ])
    agreement = agreement_or_404(agreement_id)
    require_buyer(user_id, role, agreement["buyer_id"])
    if agreement["escrow_status"] == "HELD":
        raise ApiError("ERR_ESCROW_MUST_BE_SETTLED_FIRST",
                       "Funds are already held on this agreement.")
    escrow_guard_not_settled(agreement)
    if agreement["agreement_status"] != "DRAFT" and agreement["agreement_status"] not in AGREEMENT_TERMINAL:
        raise ApiError("ERR_INVALID_AGREEMENT_STATE",
                       "The escrow may only be funded while the agreement is a DRAFT.")
    if agreement["agreement_status"] in AGREEMENT_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", "The agreement is already in a terminal state.")
    if data["amount_cents"] != agreement["required_deposit_cents"]:
        raise ApiError("ERR_DEPOSIT_AMOUNT_MISMATCH",
                       "The deposit must equal the required deposit exactly.")
    agreement["escrow_status"] = "HELD"
    domain.append_entry(agreement, "DEPOSIT", data["amount_cents"], data["deposit_reference"])
    bump(agreement)
    return ok(public(agreement))


# --- execution (PRD 3.5) -------------------------------------------------
@bp.route("/purchase-agreements/<agreement_id>/execute", methods=["POST"])
def execute_agreement(agreement_id):
    user_id, role = authenticate((BROKER,))
    agreement = agreement_or_404(agreement_id)
    require_brokerage(user_id, role, agreement["brokerage_id"])
    if agreement["agreement_status"] != "DRAFT" and agreement["agreement_status"] not in AGREEMENT_TERMINAL:
        raise ApiError("ERR_INVALID_AGREEMENT_STATE", "Only a DRAFT agreement can be executed.")
    if agreement["agreement_status"] in AGREEMENT_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", "The agreement is already in a terminal state.")
    if agreement["escrow_status"] == "AWAITING_DEPOSIT":
        raise ApiError("ERR_ESCROW_NOT_HELD", "The escrow deposit must be held before execution.")
    escrow_guard_not_settled(agreement)
    listing = listing_or_404(agreement["listing_id"])
    lic = license_or_404(agreement["license_id"])
    premises = premises_or_404(agreement["premises_id"])
    buyer = buyer_or_404(agreement["buyer_id"])
    if listing["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_LISTING_STATE", "The listing is no longer ACTIVE.")
    if lic["status"] not in ("ACTIVE", "SAFEKEEPING"):
        raise ApiError("ERR_INVALID_LICENSE_STATE",
                       "The license must be ACTIVE or SAFEKEEPING to enter escrow.")
    if lic["status"] == "SAFEKEEPING" and domain.pending_filing_on(lic["id"]) is not None:
        raise ApiError("ERR_INVALID_LICENSE_STATE",
                       "A safekeeping filing on this license is awaiting decision.")
    if premises["suitability_status"] == "UNSUITABLE":
        raise ApiError("ERR_PREMISES_UNSUITABLE", "The premises is UNSUITABLE.")
    if not calc.buyer_is_qualified(buyer):
        raise ApiError("ERR_BUYER_NOT_QUALIFIED",
                       "The buyer has no qualifying FINAL_REVIEW qualification on file.")
    disclosure = domain.fully_acked_disclosure(agreement["id"])
    if disclosure is None:
        raise ApiError("ERR_DUAL_AGENCY_DISCLOSURE_REQUIRED",
                       "A FULLY_ACKED agency disclosure is required before execution.")
    if not now() < agreement["contingency_deadline_at"]:
        raise ApiError("ERR_CONTINGENCY_DEADLINE_PASSED",
                       "The contingency deadline has passed.")
    domain.execute_cascade(agreement, listing, lic, disclosure)
    return ok(public(agreement))


# --- termination of a draft (PRD 3.4) -----------------------------------
@bp.route("/purchase-agreements/<agreement_id>/terminate", methods=["POST"])
def terminate_agreement(agreement_id):
    user_id, role = authenticate((BROKER,))
    data = validate(json_body(), [F("reason", "string")])
    agreement = agreement_or_404(agreement_id)
    require_brokerage(user_id, role, agreement["brokerage_id"])
    if agreement["agreement_status"] != "DRAFT" and agreement["agreement_status"] not in AGREEMENT_TERMINAL:
        raise ApiError("ERR_INVALID_AGREEMENT_STATE",
                       "Only a DRAFT agreement can be terminated by the broker.")
    if agreement["agreement_status"] in AGREEMENT_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", "The agreement is already in a terminal state.")
    if agreement["escrow_status"] == "HELD":
        raise ApiError("ERR_ESCROW_MUST_BE_SETTLED_FIRST",
                       "Funds are still held; the escrow must be settled first.")
    escrow_guard_not_settled(agreement)
    agreement["agreement_status"] = "TERMINATED"
    agreement["termination_reason"] = data["reason"]
    bump(agreement)
    domain.void_disclosures(agreement["id"])
    listing = db.listings.get(agreement["listing_id"])
    if listing is not None:
        domain.recompute_open_offers(listing)
        bump(listing)
    return ok(public(agreement))


# --- settlement (PRD 3.8) ------------------------------------------------
@bp.route("/purchase-agreements/<agreement_id>/escrow-settlement", methods=["POST"])
def escrow_settlement(agreement_id):
    authenticate((ESCROW_OFFICER,))
    data = validate(json_body(), [
        F("disposition", "enum", values=DISPOSITIONS),
        F("memo", "string", required=False, default=None),
    ])
    agreement = agreement_or_404(agreement_id)
    disposition = data["disposition"]
    memo = data["memo"]
    if agreement["escrow_status"] == "AWAITING_DEPOSIT":
        raise ApiError("ERR_ESCROW_NOT_HELD", "No funds are held on this agreement.")
    escrow_guard_not_settled(agreement)
    if disposition == "RELEASE" and agreement["agreement_status"] != "CLOSED":
        raise ApiError("ERR_INVALID_AGREEMENT_STATE",
                       "A release requires the agreement to be CLOSED.")
    application = domain.application_of(agreement["id"])
    app_status = application["status"] if application is not None else None
    if disposition == "RELEASE" and app_status != "APPROVED":
        raise ApiError("ERR_TRANSFER_NOT_APPROVED", "The transfer application is not APPROVED.")
    if disposition == "REFUND" and app_status != "DENIED":
        raise ApiError("ERR_TRANSFER_NOT_APPROVED", "The transfer application is not DENIED.")
    if disposition == "FORFEIT" and app_status not in IN_FLIGHT_APPLICATION:
        raise ApiError("ERR_TRANSFER_NOT_APPROVED",
                       "A forfeiture requires the transfer application to still be in flight.")
    if disposition == "FORFEIT" and not now() > agreement["contingency_deadline_at"]:
        raise ApiError("ERR_CONTINGENCY_STILL_OPEN", "The contingency window is still open.")
    balance = agreement["escrow_balance_cents"]
    if disposition == "RELEASE":
        listing = db.listings.get(agreement["listing_id"])
        brokerage = db.brokerages.get(agreement["brokerage_id"])
        lic = db.licenses.get(agreement["license_id"])
        county = db.counties.get(lic["county_id"]) if lic is not None else None
        buckets = calc.commission_disbursement(
            agreement["purchase_price_cents"],
            brokerage["commission_rate_bps"] if brokerage is not None else 0,
            agreement["commission_mode"],
            county["transfer_fee_bps"] if county is not None else 0,
            balance)
        if buckets["seller_net_cents"] < 0:
            raise ApiError("ERR_ESCROW_INSUFFICIENT_FOR_DISBURSEMENT",
                           "The held balance cannot cover the county fee and the commission.")
        agreement["escrow_status"] = "RELEASED"
        agreement["county_transfer_fee_cents"] = buckets["county_transfer_fee_cents"]
        agreement["commission_total_cents"] = buckets["commission_total_cents"]
        agreement["seller_net_cents"] = buckets["seller_net_cents"]
        domain.append_entry(agreement, "RELEASE_COUNTY_FEE",
                            -buckets["county_transfer_fee_cents"], memo)
        domain.append_entry(agreement, "RELEASE_COMMISSION",
                            -buckets["commission_total_cents"], memo)
        domain.append_entry(agreement, "RELEASE_SELLER", -buckets["seller_net_cents"], memo)
        agreement["settled_at"] = now()
        bump(agreement)
        return ok(public(agreement))
    if disposition == "REFUND":
        agreement["escrow_status"] = "REFUNDED"
        domain.append_entry(agreement, "REFUND_BUYER", -balance, memo)
        agreement["settled_at"] = now()
        bump(agreement)
        domain.compensating_cascade(agreement, "ESCROW_REFUNDED")
        return ok(public(agreement))
    agreement["escrow_status"] = "FORFEITED"
    domain.append_entry(agreement, "FORFEIT_SELLER", -balance, memo)
    agreement["settled_at"] = now()
    bump(agreement)
    domain.compensating_cascade(agreement, "ESCROW_FORFEITED")
    return ok(public(agreement))
