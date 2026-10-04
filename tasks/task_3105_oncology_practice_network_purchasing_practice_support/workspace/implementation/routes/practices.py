"""Practice onboarding, the two state axes, and the affiliation lifecycle."""

import math
from decimal import Decimal

import db
from errors import ApiError
from registry import route
from routes._shared import filtered, paginate, serial
from services import helpers
from services import shortage as shortage_service
from services.helpers import as_int, as_num, as_str
from utils import parse_iso, utc_now_dt

P = "/networks/practices"
READ_ROLES = [
    "NetworkAdmin",
    "PracticeAdmin",
    "RevenueCycleManager",
    "PayerAdjudicator",
    "NetworkAnalyst",
    "PlatformAdmin",
]

AFFILIATION_STATES = ("PROSPECTIVE", "AFFILIATED", "DEPARTING", "DEPARTED", "SUSPENDED")
PATHWAY_STATES = ("NOT_ADOPTED", "ACTIVE", "SUSPENDED")


# ---------------------------------------------------------------------------
# Creation and reads


@route("POST", "/networks/{networkId}/practices", roles=["NetworkAdmin"], status=201, write=True)
def create_practice(ctx):
    network = helpers.network_or_404(ctx.path_id("networkId"))
    data = ctx.body
    practice = db.create(
        "practices",
        {
            "network_id": network["id"],
            "practice_name": as_str(data, "practice_name"),
            "practice_npi": as_str(data, "practice_npi"),
            "state_code": as_str(data, "state_code"),
            "drug_shortage_baseline_units": as_int(
                data, "drug_shortage_baseline_units", default=0
            ),
            "denial_ratio_threshold_pct": float(
                as_num(data, "denial_ratio_threshold_pct", default=Decimal("0.20"))
            ),
            "denied_claim_count": 0,
            "settled_claim_count": 0,
            "pathway_steering_target_pct": float(
                as_num(data, "pathway_steering_target_pct", default=Decimal("0.75"))
            ),
            "affiliation_status": "PROSPECTIVE",
            "pathway_steering_status": "NOT_ADOPTED",
            "tier_level": "TIER_1",
            "trailing_12m_network_purchases_cents": 0,
            "pathway_adherence_pct": 0.0,
            "unsettled_balance_cents": 0,
            "is_rebate_qualified": False,
            "departure_effective_epoch_index": None,
        },
    )
    return serial(practice), 201


@route("GET", "/networks/practices", roles=READ_ROLES)
def list_practices(ctx):
    rows = filtered(
        db.all_records("practices"),
        ctx,
        {
            "network_id": "network_id",
            "practice_npi": "practice_npi",
            "affiliation_status": "affiliation_status",
            "state_code": "state_code",
            "tier_level": "tier_level",
        },
    )
    return paginate(ctx, rows)


@route("GET", "/networks/practices/{practiceId}", roles=READ_ROLES)
def get_practice(ctx):
    return serial(helpers.practice_or_404(ctx.path_id("practiceId")))


# ---------------------------------------------------------------------------
# Affiliation axis


@route("POST", "/networks/practices/{practiceId}/affiliate", roles=["NetworkAdmin"], write=True)
def affiliate(ctx):
    practice = helpers.practice_or_404(ctx.path_id("practiceId"))
    network = helpers.network_or_404(practice["network_id"])
    if practice["affiliation_status"] != "PROSPECTIVE":
        raise ApiError("ERR_PRACTICE_NOT_PROSPECTIVE")

    agreements = [
        a for a in helpers.agreements_of(practice["id"]) if a["status"] in ("DRAFT", "ACTIVE")
    ]
    if not agreements:
        raise ApiError("ERR_NO_PRICING_AGREEMENT")

    duplicate = any(
        p["id"] != practice["id"] and p.get("practice_npi") == practice.get("practice_npi")
        for p in db.where("practices", network_id=network["id"])
    )
    if duplicate:
        raise ApiError("ERR_DUPLICATE_PRACTICE_NPI")

    practice["affiliation_status"] = "AFFILIATED"
    # The tier consumed is the tier the practice was sold, not a recomputation.
    sold_tier = helpers.tier_from_latest_agreement(practice)
    if sold_tier:
        practice["tier_level"] = sold_tier
    else:
        helpers.recompute_tier(practice)
    helpers.recompute_freeze(network)
    db.touch(practice)
    db.touch(network)
    return serial(practice)


@route("POST", "/networks/practices/{practiceId}/suspend", roles=["NetworkAdmin"], write=True)
def suspend_practice(ctx):
    practice = helpers.practice_or_404(ctx.path_id("practiceId"))
    if practice["affiliation_status"] != "AFFILIATED":
        raise ApiError("ERR_PRACTICE_NOT_AFFILIATED")
    practice["affiliation_status"] = "SUSPENDED"
    if practice["pathway_steering_status"] == "ACTIVE":
        practice["pathway_steering_status"] = "SUSPENDED"
    db.touch(practice)
    return serial(practice)


@route("POST", "/networks/practices/{practiceId}/reinstate", roles=["NetworkAdmin"], write=True)
def reinstate_practice(ctx):
    practice = helpers.practice_or_404(ctx.path_id("practiceId"))
    if practice["affiliation_status"] != "SUSPENDED":
        raise ApiError("ERR_PRACTICE_NOT_SUSPENDED")
    suspended = [
        a
        for a in db.where("management_agreements", practice_id=practice["id"])
        if a["status"] == "SUSPENDED"
    ]
    if suspended:
        raise ApiError("ERR_OPEN_MANAGEMENT_SUSPENSION")
    practice["affiliation_status"] = "AFFILIATED"
    # The pathway axis is deliberately not auto-restored.
    db.touch(practice)
    return serial(practice)


@route(
    "POST",
    "/networks/practices/{practiceId}/departure-notice",
    roles=["NetworkAdmin", "PracticeAdmin"],
    write=True,
)
def departure_notice(ctx):
    practice = helpers.practice_or_404(ctx.path_id("practiceId"))
    helpers.may_edit_practice(ctx.principal, practice["id"])
    network = helpers.network_or_404(practice["network_id"])
    status = practice["affiliation_status"]

    if status == "AFFILIATED":
        contract = helpers.active_contract(practice["id"])
        if contract is None:
            raise ApiError("ERR_NO_ACTIVE_AFFILIATION_CONTRACT")
    elif status == "SUSPENDED":
        if ctx.principal.role != "NetworkAdmin":
            raise ApiError("ERR_INSUFFICIENT_PERMISSIONS")
        # Open management agreements are checked BEFORE the contract condition.
        live = [
            a
            for a in db.where("management_agreements", practice_id=practice["id"])
            if a["status"] != "TERMINATED"
        ]
        if live:
            raise ApiError("ERR_OPEN_MANAGEMENT_AGREEMENT")
        contract = helpers.active_contract(practice["id"])
        if contract is None:
            raise ApiError("ERR_NO_ACTIVE_AFFILIATION_CONTRACT")
    else:
        raise ApiError("ERR_PRACTICE_NOT_AFFILIATED")

    notice_days = int(contract.get("notice_period_days") or 0)
    epoch_index = int(network.get("allocation_epoch_index") or 0)
    practice["affiliation_status"] = "DEPARTING"
    practice["departure_effective_epoch_index"] = epoch_index + int(
        math.ceil(Decimal(notice_days) / Decimal(30))
    )

    # The contract's status change recomputes its holdback, and that holdback
    # flags each of the practice's pending/qualified qualifications in turn.
    contract["status"] = "DEPARTURE_NOTICE"
    holdback = 0
    for qualification in db.where("rebate_qualifications", practice_id=practice["id"]):
        if qualification["status"] not in ("PENDING", "QUALIFIED"):
            continue
        amount = int(qualification.get("rebate_amount_cents") or 0)
        if qualification.get("compliance_report_verified"):
            qualification["holdback_cents"] = 0
            continue
        qualification["holdback_cents"] = amount
        holdback += amount
        qualification["status"] = "RECLAIMED"
        qualification["is_qualified"] = False
        db.touch(qualification)
        if amount:
            practice["unsettled_balance_cents"] = (
                int(practice.get("unsettled_balance_cents") or 0) + amount
            )
    contract["rebate_holdback_cents"] = holdback
    db.touch(contract)

    for grant in db.where("shortage_allocations", practice_id=practice["id"]):
        if grant["status"] in ("GRANTED", "PARTIALLY_COMMITTED"):
            shortage_service.revoke(grant)

    practice["is_rebate_qualified"] = False
    helpers.recompute_freeze(network)
    db.touch(practice)
    db.touch(network)
    return serial(practice)


@route(
    "POST",
    "/networks/practices/{practiceId}/withdraw-departure",
    roles=["NetworkAdmin", "PracticeAdmin"],
    write=True,
)
def withdraw_departure(ctx):
    practice = helpers.practice_or_404(ctx.path_id("practiceId"))
    helpers.may_edit_practice(ctx.principal, practice["id"])
    network = helpers.network_or_404(practice["network_id"])
    if practice["affiliation_status"] != "DEPARTING":
        raise ApiError("ERR_PRACTICE_NOT_DEPARTING")
    epoch_index = int(network.get("allocation_epoch_index") or 0)
    effective = practice.get("departure_effective_epoch_index")
    if effective is None or int(effective) <= epoch_index:
        raise ApiError("ERR_DEPARTURE_ALREADY_EFFECTIVE")

    practice["affiliation_status"] = "AFFILIATED"
    practice["departure_effective_epoch_index"] = None

    for contract in db.where("affiliation_contracts", practice_id=practice["id"]):
        if contract["status"] == "DEPARTURE_NOTICE":
            contract["status"] = "ACTIVE"
            contract["rebate_holdback_cents"] = 0
            db.touch(contract)

    for qualification in db.where("rebate_qualifications", practice_id=practice["id"]):
        if qualification["status"] != "RECLAIMED":
            continue
        restored = int(qualification.get("holdback_cents") or 0)
        qualification["holdback_cents"] = 0
        qualification["is_qualified"] = True
        qualification["status"] = "QUALIFIED"
        db.touch(qualification)
        practice["unsettled_balance_cents"] = (
            int(practice.get("unsettled_balance_cents") or 0) - restored
        )

    for agreement in db.where("pricing_agreements", practice_id=practice["id"]):
        if (
            agreement["status"] == "SUPERSEDED"
            and agreement.get("superseded_by_agreement_id") is None
            and agreement.get("status_changed_by") == "DEPARTURE_UNWIND"
        ):
            agreement["status"] = "ACTIVE"
            agreement["status_changed_by"] = "DEPARTURE_WITHDRAWAL"
            db.touch(agreement)

    for grant in db.where("shortage_allocations", practice_id=practice["id"]):
        if grant["status"] == "REVOKED":
            shortage_service.restore(grant)

    helpers.recompute_freeze(network)
    db.touch(practice)
    db.touch(network)
    return serial(practice)


@route(
    "POST",
    "/networks/practices/{practiceId}/withdraw-affiliation",
    roles=["NetworkAdmin"],
    write=True,
)
def withdraw_affiliation(ctx):
    practice = helpers.practice_or_404(ctx.path_id("practiceId"))
    network = helpers.network_or_404(practice["network_id"])
    if practice["affiliation_status"] != "PROSPECTIVE":
        raise ApiError("ERR_PRACTICE_DEPARTURE_NOT_ALLOWED")
    contract = helpers.active_contract(practice["id"])
    if contract is None:
        raise ApiError("ERR_NO_ACTIVE_AFFILIATION_CONTRACT")

    practice["affiliation_status"] = "DEPARTED"
    contract["status"] = "TERMINATED"
    contract["rebate_holdback_cents"] = 0
    contract["open_orders_closed"] = True
    db.touch(contract)

    for order in db.where("purchase_orders", practice_id=practice["id"]):
        if order["status"] in ("SUBMITTED", "CONFIRMED", "BACKORDERED"):
            if order.get("shortage_allocation_id"):
                allocation = db.get("shortage_allocations", order["shortage_allocation_id"])
                if allocation is not None:
                    shortage_service.release(allocation, order)
            order["status"] = "CANCELLED"
            db.touch(order)

    helpers.recompute_freeze(network)
    db.touch(practice)
    db.touch(network)
    return serial(practice)


# ---------------------------------------------------------------------------
# Pathway axis


@route(
    "POST",
    "/networks/practices/{practiceId}/pathways/adopt",
    roles=["PracticeAdmin", "NetworkAdmin"],
    write=True,
)
def pathway_adopt(ctx):
    practice = helpers.practice_or_404(ctx.path_id("practiceId"))
    helpers.may_edit_practice(ctx.principal, practice["id"])
    network = helpers.network_or_404(practice["network_id"])
    if practice["pathway_steering_status"] == "ACTIVE":
        raise ApiError("ERR_PATHWAY_ALREADY_ADOPTED")
    published = [
        p for p in db.where("pathway_protocols", network_id=network["id"]) if p["status"] == "PUBLISHED"
    ]
    if not published:
        raise ApiError("ERR_NO_PUBLISHED_PROTOCOL")

    practice["pathway_steering_status"] = "ACTIVE"
    # Every scheduled treatment is re-evaluated against the protocol in force at
    # its own administered_at.
    from services import administer

    for treatment in db.where("treatments", practice_id=practice["id"]):
        if treatment["status"] != "SCHEDULED":
            continue
        product = db.get("drug_products", treatment["drug_product_id"])
        instant = parse_iso(treatment.get("administered_at")) or utc_now_dt()
        treatment["is_pathway_concordant"] = administer.concordant(treatment, product, instant)
        db.touch(treatment)
    helpers.recompute_adherence(practice)
    db.touch(practice)
    return serial(practice)


@route(
    "POST",
    "/networks/practices/{practiceId}/pathways/suspend",
    roles=["NetworkAdmin"],
    write=True,
)
def pathway_suspend(ctx):
    practice = helpers.practice_or_404(ctx.path_id("practiceId"))
    if practice["pathway_steering_status"] != "ACTIVE":
        raise ApiError("ERR_PATHWAY_NOT_ACTIVE")
    practice["pathway_steering_status"] = "SUSPENDED"
    # Adherence is preserved, not zeroed, while suspended.
    db.touch(practice)
    return serial(practice)


@route(
    "POST",
    "/networks/practices/{practiceId}/pathways/withdraw",
    roles=["PracticeAdmin", "NetworkAdmin"],
    write=True,
)
def pathway_withdraw(ctx):
    practice = helpers.practice_or_404(ctx.path_id("practiceId"))
    helpers.may_edit_practice(ctx.principal, practice["id"])
    if practice["pathway_steering_status"] != "ACTIVE":
        raise ApiError("ERR_PATHWAY_NOT_ACTIVE")
    practice["pathway_steering_status"] = "NOT_ADOPTED"
    practice["pathway_adherence_pct"] = 0.0
    db.touch(practice)
    return serial(practice)


# ---------------------------------------------------------------------------
# Stock report


@route(
    "GET",
    f"{P}/{{practiceId}}/stock-report",
    roles=[
        "NetworkAdmin",
        "PracticeAdmin",
        "RevenueCycleManager",
        "NetworkAnalyst",
        "PlatformAdmin",
    ],
)
def stock_report(ctx):
    practice = helpers.practice_or_404(ctx.path_id("practiceId"))
    product_id = ctx.q("drug_product_id")
    as_of = ctx.q_dt("as_of") or utc_now_dt()

    from services import administer

    expiring = administer.expiring_units(practice["id"], product_id) if product_id else 0
    usable = administer.usable_units(practice["id"], product_id, as_of) if product_id else 0

    requested_doses = ctx.q_int("dose_count", 1) or 1
    administered_units = ctx.q_int("administered_units", 0) or 0
    vial_yield = ctx.q_int("vial_yield_units", 1) or 1

    plan = administer.draw_plan(administered_units, vial_yield, requested_doses)
    demand = plan["total_draw_units"]
    shortfall = max(demand - usable, 0)
    per_dose_draw = plan["dose_units_per_dose"]
    unmet = 0
    if per_dose_draw > 0 and shortfall > 0:
        met_doses = int(usable // per_dose_draw)
        unmet = max(requested_doses - met_doses, 0)
    return {
        "expiring_on_hand_units": expiring,
        "usable_on_hand_units": usable,
        "requested_doses": requested_doses,
        "doses_required": requested_doses,
        "unmet_dose_units": unmet,
        "dose_allocations": plan["dose_allocations"],
        "stock_sufficient": usable >= demand,
    }


# ---------------------------------------------------------------------------
# Practice-scoped collection reads


@route("GET", f"{P}/{{practiceId}}/providers", roles=READ_ROLES)
def practice_providers(ctx):
    practice = helpers.practice_or_404(ctx.path_id("practiceId"))
    rows = filtered(
        db.where("providers", practice_id=practice["id"]), ctx, {"status": "status"}
    )
    return paginate(ctx, rows)


@route("GET", f"{P}/{{practiceId}}/pricing-agreements", roles=READ_ROLES)
def practice_pricing_agreements(ctx):
    practice = helpers.practice_or_404(ctx.path_id("practiceId"))
    rows = filtered(
        db.where("pricing_agreements", practice_id=practice["id"]),
        ctx,
        {"status": "status", "tier_level": "tier_level"},
    )
    return paginate(ctx, rows)


@route("GET", f"{P}/{{practiceId}}/purchase-orders", roles=READ_ROLES)
def practice_purchase_orders(ctx):
    practice = helpers.practice_or_404(ctx.path_id("practiceId"))
    rows = filtered(
        db.where("purchase_orders", practice_id=practice["id"]),
        ctx,
        {"status": "status", "drug_product_id": "drug_product_id"},
    )
    return paginate(ctx, rows)


@route("GET", f"{P}/{{practiceId}}/inventory-lots", roles=READ_ROLES)
def practice_lots(ctx):
    practice = helpers.practice_or_404(ctx.path_id("practiceId"))
    rows = filtered(
        db.where("inventory_lots", practice_id=practice["id"]),
        ctx,
        {"drug_product_id": "drug_product_id", "status": "status"},
    )
    return paginate(ctx, rows)


@route("GET", f"{P}/{{practiceId}}/treatments", roles=READ_ROLES)
def practice_treatments(ctx):
    practice = helpers.practice_or_404(ctx.path_id("practiceId"))
    rows = filtered(
        db.where("treatments", practice_id=practice["id"]),
        ctx,
        {"status": "status", "provider_id": "provider_id"},
    )
    return paginate(ctx, rows)


@route("GET", f"{P}/{{practiceId}}/payer-claims", roles=READ_ROLES)
def practice_claims(ctx):
    practice = helpers.practice_or_404(ctx.path_id("practiceId"))
    rows = filtered(
        db.where("claims", practice_id=practice["id"]),
        ctx,
        {"status": "status", "treatment_id": "treatment_id"},
    )
    return paginate(ctx, rows)


@route("GET", f"{P}/{{practiceId}}/rebate-qualifications", roles=READ_ROLES)
def practice_qualifications(ctx):
    practice = helpers.practice_or_404(ctx.path_id("practiceId"))
    rows = filtered(
        db.where("rebate_qualifications", practice_id=practice["id"]),
        ctx,
        {"status": "status", "period_epoch_index": "period_epoch_index"},
    )
    return paginate(ctx, rows)


@route("GET", f"{P}/{{practiceId}}/management-agreements", roles=READ_ROLES)
def practice_management(ctx):
    practice = helpers.practice_or_404(ctx.path_id("practiceId"))
    rows = filtered(
        db.where("management_agreements", practice_id=practice["id"]),
        ctx,
        {"status": "status", "service_line": "service_line"},
    )
    return paginate(ctx, rows)


@route("GET", f"{P}/{{practiceId}}/research-participations", roles=READ_ROLES)
def practice_research(ctx):
    practice = helpers.practice_or_404(ctx.path_id("practiceId"))
    rows = filtered(
        db.where("research_participations", practice_id=practice["id"]),
        ctx,
        {"site_status": "site_status"},
    )
    return paginate(ctx, rows)


@route("GET", f"{P}/{{practiceId}}/affiliation-contracts", roles=READ_ROLES)
def practice_contracts(ctx):
    practice = helpers.practice_or_404(ctx.path_id("practiceId"))
    rows = filtered(
        db.where("affiliation_contracts", practice_id=practice["id"]), ctx, {"status": "status"}
    )
    return paginate(ctx, rows)


@route("GET", f"{P}/{{practiceId}}/shortage-allocations", roles=READ_ROLES)
def practice_allocations(ctx):
    practice = helpers.practice_or_404(ctx.path_id("practiceId"))
    rows = filtered(
        db.where("shortage_allocations", practice_id=practice["id"]), ctx, {"status": "status"}
    )
    return paginate(ctx, rows)