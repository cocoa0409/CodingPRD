"""Pre-sale contracts, payment milestones and deliverable packages."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import calc
from envelope import created, ok, ok_list
from errors import ApiError
from serializers import contract_out, milestone_out, package_out
from store import (
    base_row,
    contracts_of_buyer,
    contracts_of_film,
    db,
    get_buyer,
    get_contract,
    get_film,
    get_package,
    get_territory,
    milestones_of_contract,
    now,
    packages_of_contract,
    touch,
)
from util import ONE, ZERO2, ZERO4, add_days, add_months, q2, q4
from validation import actor, body, page, raw_id, require_roles

bp = Blueprint("contracts", __name__)

MILESTONE_LABELS = ("ON_SIGNATURE", "ON_DELIVERY", "ON_RELEASE", "ON_TERM_END")
REJECTION_REASONS = (
    "TECHNICAL_INCOMPLETE",
    "LEGAL_INCOMPLETE",
    "QC_FAIL",
    "LATE_DELIVERY",
)
QC_RESULTS = ("PASS", "FAIL")

CONTRACT_READ_ROLES = (
    "SalesAgent",
    "HeadOfSales",
    "DeliveryManager",
    "CollectionAgent",
    "Lender",
    "PlatformAdmin",
    "Buyer",
)
MILESTONE_READ_ROLES = (
    "SalesAgent",
    "HeadOfSales",
    "CollectionAgent",
    "Lender",
    "PlatformAdmin",
    "Buyer",
)
PACKAGE_READ_ROLES = (
    "SalesAgent",
    "HeadOfSales",
    "DeliveryManager",
    "PlatformAdmin",
    "Buyer",
)

OFFER_WINDOW = ("IN_MARKET", "SOLD_OUT")


def require_contract_buyer(contract):
    """Fifth rung of the ladder — entity-backed ownership."""
    if actor() != contract["buyer_id"]:
        raise ApiError("ERR_NOT_CONTRACT_BUYER")


def refresh_milestone_amounts(contract):
    """Every milestone amount tracks the contract MG until execution."""
    for milestone in milestones_of_contract(contract["id"]):
        amount = q2(milestone["pct_of_mg"] * contract["minimum_guarantee_usd"])
        if milestone["amount_usd"] != amount:
            milestone["amount_usd"] = amount
            touch(milestone)


def licensed_to_published(contract):
    valuation = calc.licensed_valuation(contract["film_id"], contract["territory_id"])
    if valuation is not None:
        valuation["status"] = "PUBLISHED"
        touch(valuation)
        return True
    return False


# ------------------------------------------------------------------- creation


@bp.post("/pre-sale-contracts")
@require_roles("SalesAgent", "HeadOfSales")
def create_contract():
    film_ref = raw_id("film_id")
    film = get_film(film_ref) if film_ref is not None else None
    territory_ref = raw_id("territory_id")
    territory = get_territory(territory_ref) if territory_ref is not None else None
    buyer_ref = raw_id("buyer_id")
    buyer = get_buyer(buyer_ref) if buyer_ref is not None else None

    payload = body()
    payload.req_id("film_id")
    payload.req_id("buyer_id")
    payload.req_id("territory_id")
    minimum_guarantee = q2(payload.req_number("minimum_guarantee_usd"))
    license_term_months = payload.req_int("license_term_months", minimum=12)
    holdback_days = payload.req_int("holdback_days", minimum=0, maximum=720)
    expected_buyer_version = payload.req_int("expected_buyer_version")

    if expected_buyer_version != buyer["version"]:
        raise ApiError("ERR_STALE_BUYER_VERSION")
    if film["sales_status"] not in OFFER_WINDOW:
        raise ApiError("ERR_FILM_NOT_IN_MARKET")
    if buyer["status"] == "BLOCKED":
        raise ApiError("ERR_BUYER_BLOCKED")
    if calc.agreement_in_force(film["id"]) is None:
        raise ApiError("ERR_AGENCY_AGREEMENT_NOT_IN_FORCE")

    superseded = []
    for existing in contracts_of_film(film["id"]):
        if existing["territory_id"] != territory["id"]:
            continue
        status = existing["negotiation_status"]
        if status in ("ACCEPTED", "EXECUTED"):
            raise ApiError("ERR_DUPLICATE_TERRITORY_OFFER")
        if status in ("OFFERED", "COUNTERED"):
            if existing["buyer_id"] != buyer["id"]:
                raise ApiError("ERR_DUPLICATE_TERRITORY_OFFER")
            superseded.append(existing)

    exposure = calc.buyer_gross_exposure(buyer["id"])
    if q2(exposure + minimum_guarantee) > q2(buyer["exposure_limit_usd"]):
        raise ApiError("ERR_BUYER_EXPOSURE_EXCEEDED")

    for existing in superseded:
        existing["negotiation_status"] = "LAPSED"
        touch(existing)

    row = base_row()
    row.update(
        {
            "film_id": film["id"],
            "buyer_id": buyer["id"],
            "territory_id": territory["id"],
            "minimum_guarantee_usd": minimum_guarantee,
            "license_term_months": license_term_months,
            "holdback_days": holdback_days,
            "negotiation_round": 1,
            "negotiation_status": "OFFERED",
            "delivery_status": "PENDING",
            "collection_status": "UNPAID",
            "counter_minimum_guarantee_usd": None,
            "license_start_date": None,
            "license_end_date": None,
            "holdback_release_date": None,
            "offered_by_user_id": actor(),
            "executed_by_user_id": None,
        }
    )
    db.contracts[row["id"]] = row
    touch(buyer)
    return created(contract_out(row))


@bp.get("/pre-sale-contracts")
@require_roles(*CONTRACT_READ_ROLES)
def list_contracts():
    from store import by_creation

    rows = by_creation(list(db.contracts.values()))
    for key in (
        "film_id",
        "buyer_id",
        "territory_id",
        "negotiation_status",
        "delivery_status",
        "collection_status",
    ):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    items, meta = page(rows, contract_out)
    return ok_list(items, meta)


@bp.get("/pre-sale-contracts/<contract_id>")
@require_roles(*CONTRACT_READ_ROLES)
def read_contract(contract_id):
    return ok(contract_out(get_contract(contract_id)))


# ---------------------------------------------------------------- negotiation


@bp.post("/pre-sale-contracts/<contract_id>/counter")
@require_roles("Buyer")
def counter_contract(contract_id):
    contract = get_contract(contract_id)
    payload = body()
    counter_mg = q2(payload.req_number("counter_minimum_guarantee_usd"))
    counter_term = payload.opt_int("counter_license_term_months", minimum=12)
    counter_holdback = payload.opt_int("counter_holdback_days", minimum=0, maximum=720)
    require_contract_buyer(contract)
    if contract["negotiation_status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE")
    if contract["negotiation_round"] >= calc.MAX_NEGOTIATION_ROUNDS:
        raise ApiError("ERR_NEGOTIATION_ROUND_LIMIT")

    contract["counter_minimum_guarantee_usd"] = counter_mg
    if counter_term is not None:
        contract["counter_license_term_months"] = counter_term
    if counter_holdback is not None:
        contract["counter_holdback_days"] = counter_holdback
    contract["negotiation_status"] = "COUNTERED"
    contract["negotiation_round"] = contract["negotiation_round"] + 1
    touch(contract)
    return ok(contract_out(contract))


@bp.post("/pre-sale-contracts/<contract_id>/revise-offer")
@require_roles("SalesAgent", "HeadOfSales")
def revise_offer(contract_id):
    contract = get_contract(contract_id)
    payload = body()
    minimum_guarantee = q2(payload.req_number("minimum_guarantee_usd"))
    license_term_months = payload.opt_int("license_term_months", minimum=12)
    holdback_days = payload.opt_int("holdback_days", minimum=0, maximum=720)
    if contract["negotiation_status"] != "COUNTERED":
        raise ApiError("ERR_INVALID_STATE")
    if contract["negotiation_round"] >= calc.MAX_NEGOTIATION_ROUNDS:
        raise ApiError("ERR_NEGOTIATION_ROUND_LIMIT")
    buyer = get_buyer(contract["buyer_id"])
    exposure = calc.buyer_gross_exposure(buyer["id"])
    if q2(exposure + minimum_guarantee) > q2(buyer["exposure_limit_usd"]):
        raise ApiError("ERR_BUYER_EXPOSURE_EXCEEDED")

    contract["minimum_guarantee_usd"] = minimum_guarantee
    if license_term_months is not None:
        contract["license_term_months"] = license_term_months
    if holdback_days is not None:
        contract["holdback_days"] = holdback_days
    contract["counter_minimum_guarantee_usd"] = None
    contract["negotiation_status"] = "OFFERED"
    contract["negotiation_round"] = contract["negotiation_round"] + 1
    refresh_milestone_amounts(contract)
    touch(contract)
    touch(buyer)
    return ok(contract_out(contract))


@bp.post("/pre-sale-contracts/<contract_id>/accept")
@require_roles("Buyer")
def accept_contract(contract_id):
    contract = get_contract(contract_id)
    require_contract_buyer(contract)
    if contract["negotiation_status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE")
    buyer = get_buyer(contract["buyer_id"])
    if buyer["status"] not in ("ACTIVE", "WATCHLIST"):
        raise ApiError("ERR_BUYER_BLOCKED")

    contract["negotiation_status"] = "ACCEPTED"
    touch(contract)
    film = get_film(contract["film_id"])
    touch(film)
    touch(buyer)
    return ok(contract_out(contract))


@bp.post("/pre-sale-contracts/<contract_id>/execute")
@require_roles("HeadOfSales")
def execute_contract(contract_id):
    contract = get_contract(contract_id)
    if contract["negotiation_status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE")
    film = get_film(contract["film_id"])
    buyer = get_buyer(contract["buyer_id"])
    valuation = calc.published_valuation(film["id"], contract["territory_id"])
    if valuation is not None and valuation["published_by_user_id"] == actor():
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if calc.agreement_in_force(film["id"]) is None:
        raise ApiError("ERR_AGENCY_AGREEMENT_NOT_IN_FORCE")
    if valuation is None:
        raise ApiError("ERR_NO_PUBLISHED_VALUATION")
    if calc.contract_pct_total(contract["id"]) != q4(ONE):
        raise ApiError("ERR_MILESTONE_SCHEDULE_INVALID")
    net_unpaid = calc.buyer_net_unpaid_exposure(buyer["id"])
    contract_unpaid = calc.contract_unpaid(contract["id"])
    headroom = q2(buyer["exposure_limit_usd"] * calc.NET_EXECUTION_HEADROOM)
    if q2(net_unpaid + contract_unpaid) > headroom:
        raise ApiError("ERR_BUYER_NET_EXPOSURE_EXCEEDED")
    if contract["minimum_guarantee_usd"] < valuation["floor_price_usd"]:
        raise ApiError("ERR_MG_BELOW_FLOOR")

    instant = now()
    contract["negotiation_status"] = "EXECUTED"
    contract["executed_by_user_id"] = actor()
    contract["license_start_date"] = instant
    contract["license_end_date"] = add_months(instant, contract["license_term_months"])
    contract["holdback_release_date"] = add_days(
        film["theatrical_release_date"], contract["holdback_days"]
    )
    touch(contract)

    signature = calc.milestone_by_label(contract["id"], "ON_SIGNATURE")
    if signature is not None and signature["status"] == "SCHEDULED":
        signature["status"] = "INVOICED"
        touch(signature)

    valuation["status"] = "LICENSED"
    touch(valuation)
    touch(film)
    calc.evaluate_sold_out(film)
    touch(buyer)
    calc.refresh_facilities(film["id"], allow_cure=True)
    return ok(contract_out(contract))


@bp.post("/pre-sale-contracts/<contract_id>/lapse")
@require_roles("HeadOfSales")
def lapse_contract(contract_id):
    contract = get_contract(contract_id)
    payload = body()
    payload.req_string("reason")
    previous = contract["negotiation_status"]
    if previous not in ("OFFERED", "COUNTERED", "ACCEPTED"):
        raise ApiError("ERR_INVALID_STATE")

    contract["negotiation_status"] = "LAPSED"
    touch(contract)
    buyer = get_buyer(contract["buyer_id"])
    touch(buyer)
    film = get_film(contract["film_id"])
    if previous == "ACCEPTED":
        touch(film)
    calc.refresh_facilities(film["id"], allow_margin_call=True)
    return ok(contract_out(contract))


@bp.post("/pre-sale-contracts/<contract_id>/revert")
@require_roles("HeadOfSales")
def revert_contract(contract_id):
    contract = get_contract(contract_id)
    if contract["negotiation_status"] != "EXECUTED":
        raise ApiError("ERR_INVALID_STATE")
    end = contract["license_end_date"]
    if end is None or now() < end:
        raise ApiError("ERR_LICENSE_TERM_NOT_EXPIRED")
    if contract["collection_status"] != "PAID":
        raise ApiError("ERR_INVALID_STATE")

    contract["negotiation_status"] = "REVERTED"
    touch(contract)
    licensed_to_published(contract)
    film = get_film(contract["film_id"])
    touch(film)
    calc.evaluate_back_in_market(film)
    calc.refresh_facilities(film["id"], allow_margin_call=True)
    return ok(contract_out(contract))


# ----------------------------------------------------------- payment schedule


@bp.post("/pre-sale-contracts/<contract_id>/payment-milestones")
@require_roles("SalesAgent", "HeadOfSales")
def create_milestone(contract_id):
    contract = get_contract(contract_id)
    payload = body()
    label = payload.req_enum("label", MILESTONE_LABELS)
    pct_of_mg = q4(
        payload.req_number(
            "pct_of_mg",
            minimum=Decimal("0"),
            maximum=Decimal("1"),
            exclusive_min=True,
        )
    )
    due_date = payload.req_instant("due_date")

    if q4(calc.contract_pct_total(contract["id"]) + pct_of_mg) > q4(ONE):
        raise ApiError("ERR_MILESTONE_SCHEDULE_INVALID")
    if calc.milestone_by_label(contract["id"], label) is not None:
        raise ApiError("ERR_MILESTONE_SCHEDULE_INVALID")

    row = base_row()
    row.update(
        {
            "contract_id": contract["id"],
            "label": label,
            "pct_of_mg": pct_of_mg,
            "amount_usd": q2(pct_of_mg * contract["minimum_guarantee_usd"]),
            "due_date": due_date,
            "status": "SCHEDULED",
            "received_at": None,
            "received_amount_usd": ZERO2,
            "received_by_user_id": None,
            "accrued_commission_usd": ZERO2,
        }
    )
    db.milestones[row["id"]] = row
    touch(contract)
    return created(milestone_out(row))


@bp.get("/pre-sale-contracts/<contract_id>/payment-milestones")
@require_roles(*MILESTONE_READ_ROLES)
def list_milestones(contract_id):
    contract = get_contract(contract_id)
    rows = sorted(
        milestones_of_contract(contract["id"]),
        key=lambda row: (row["due_date"], row["created_at"], row["_seq"]),
    )
    items, meta = page(rows, milestone_out)
    return ok_list(items, meta)


# ------------------------------------------------------------------- delivery


@bp.post("/pre-sale-contracts/<contract_id>/deliverable-packages")
@require_roles("DeliveryManager")
def create_package(contract_id):
    contract = get_contract(contract_id)
    payload = body()
    technical = payload.req_int("technical_items_count", minimum=0)
    legal = payload.req_int("legal_items_count", minimum=0)

    if contract["negotiation_status"] != "EXECUTED":
        raise ApiError("ERR_INVALID_STATE")
    existing = packages_of_contract(contract["id"])
    latest = existing[-1] if existing else None
    if latest is not None and latest["status"] != "REJECTED":
        raise ApiError("ERR_INVALID_STATE")

    instant = now()
    release = contract["holdback_release_date"]
    if release is None or instant < release:
        raise ApiError("ERR_HOLDBACK_NOT_ELAPSED")
    if latest is not None:
        deadline = latest["cure_deadline"]
        if deadline is not None and instant > deadline:
            raise ApiError("ERR_CURE_WINDOW_ELAPSED")
    if technical < calc.REQUIRED_TECHNICAL_ITEMS or legal < calc.REQUIRED_LEGAL_ITEMS:
        raise ApiError("ERR_DELIVERABLES_INCOMPLETE")

    row = base_row()
    row.update(
        {
            "contract_id": contract["id"],
            "technical_items_count": technical,
            "legal_items_count": legal,
            "revision_round": 1 if latest is None else latest["revision_round"] + 1,
            "submitted_at": instant,
            "status": "SUBMITTED",
            "qc_result": "PENDING",
            "rejection_reason": None,
            "cure_deadline": None,
            "submitted_by_user_id": actor(),
        }
    )
    db.packages[row["id"]] = row
    contract["delivery_status"] = "SUBMITTED"
    touch(contract)
    return created(package_out(row))


@bp.get("/pre-sale-contracts/<contract_id>/deliverable-packages")
@require_roles(*PACKAGE_READ_ROLES)
def list_packages(contract_id):
    contract = get_contract(contract_id)
    rows = sorted(
        packages_of_contract(contract["id"]),
        key=lambda row: (row["revision_round"], row["created_at"], row["_seq"]),
    )
    items, meta = page(rows, package_out)
    return ok_list(items, meta)


def final_rejection_cascade(contract):
    """package -> contract -> milestones -> facility -> picture (PRD 3.6)."""
    contract["delivery_status"] = "REJECTED"
    contract["negotiation_status"] = "LAPSED"
    for milestone in milestones_of_contract(contract["id"]):
        if milestone["status"] in ("SCHEDULED", "INVOICED"):
            milestone["status"] = "WRITTEN_OFF"
            touch(milestone)
    contract["collection_status"] = "WRITTEN_OFF"
    touch(contract)
    licensed_to_published(contract)
    film = get_film(contract["film_id"])
    calc.refresh_facilities(film["id"], allow_margin_call=True)
    touch(film)
    calc.evaluate_back_in_market(film)


@bp.post("/deliverable-packages/<package_id>/qc-result")
@require_roles("Buyer")
def record_qc_result(package_id):
    package = get_package(package_id)
    payload = body()
    result = payload.req_enum("result", QC_RESULTS)
    reason = None
    if result == "FAIL":
        reason = payload.req_enum("rejection_reason", REJECTION_REASONS)
    contract = get_contract(package["contract_id"])
    require_contract_buyer(contract)
    if package["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE")

    if result == "PASS":
        package["qc_result"] = "PASS"
        package["status"] = "ACCEPTED"
        touch(package)
        cured = package["revision_round"] >= 2
        contract["delivery_status"] = "CURED" if cured else "ACCEPTED"
        touch(contract)
        delivery = calc.milestone_by_label(contract["id"], "ON_DELIVERY")
        if delivery is not None and delivery["status"] == "SCHEDULED":
            delivery["status"] = "INVOICED"
            touch(delivery)
        if cured:
            release = calc.milestone_by_label(contract["id"], "ON_RELEASE")
            if release is not None:
                release["due_date"] = add_days(
                    release["due_date"], calc.CURE_WINDOW_DAYS
                )
                touch(release)
        return ok(package_out(package))

    package["qc_result"] = "FAIL"
    package["rejection_reason"] = reason
    package["cure_deadline"] = add_days(package["submitted_at"], calc.CURE_WINDOW_DAYS)
    if package["revision_round"] >= calc.MAX_REVISION_ROUNDS:
        package["status"] = "REJECTED_FINAL"
        touch(package)
        final_rejection_cascade(contract)
    else:
        package["status"] = "REJECTED"
        touch(package)
        contract["delivery_status"] = "REJECTED"
        touch(contract)
    return ok(package_out(package))
