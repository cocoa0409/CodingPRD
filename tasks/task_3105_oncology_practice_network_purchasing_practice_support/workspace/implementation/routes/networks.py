"""Networks, the epoch engine of time, and the freeze flag."""

from decimal import Decimal

import db
from errors import ApiError
from registry import route
from routes._shared import paginate, serial
from services import helpers, pricing, rebates
from services import shortage as shortage_service
from services.helpers import as_int, as_num, as_str
from utils import ratio4

READ_ROLES = [
    "NetworkAdmin",
    "PracticeAdmin",
    "RevenueCycleManager",
    "PayerAdjudicator",
    "NetworkAnalyst",
    "PlatformAdmin",
]


@route("POST", "/networks", roles=["NetworkAdmin"], status=201, write=True)
def create_network(ctx):
    data = ctx.body
    name = as_str(data, "name")
    code = as_str(data, "network_agreement_code")
    method = as_str(data, "shortage_allocation_method")
    if method not in ("PRO_RATA_BASELINE", "PRIORITY_PATHWAY", "EQUAL_SPLIT"):
        raise ApiError("ERR_INVALID_REQUEST", "shortage_allocation_method outside its enum")
    ladder = data.get("tier_market_share_boundaries")
    if not isinstance(ladder, list):
        raise ApiError("ERR_INVALID_REQUEST", "tier_market_share_boundaries must be an array")

    network = db.create(
        "networks",
        {
            "name": name,
            "network_agreement_code": code,
            "rebate_market_share_threshold_pct": _opt_num(data, "rebate_market_share_threshold_pct", 0),
            "rebate_min_compliance_score": _opt_num(data, "rebate_min_compliance_score", 0),
            "compliance_report_grace_days": as_int(data, "compliance_report_grace_days", default=30),
            "shortage_allocation_method": method,
            "payment_terms_days": as_int(data, "payment_terms_days", default=60),
            "tier_market_share_boundaries": ladder,
            "allocation_epoch_index": 0,
            "is_commercial_terms_frozen": False,
        },
    )
    return serial(network), 201


def _opt_num(data, key, default):
    value = as_num(data, key, default=None)
    if value is None:
        return default
    return float(value)


@route("GET", "/networks", roles=READ_ROLES)
def list_networks(ctx):
    return paginate(ctx, db.all_records("networks"))


@route("GET", "/networks/{networkId}", roles=READ_ROLES)
def get_network(ctx):
    return serial(helpers.network_or_404(ctx.path_id("networkId")))


@route("POST", "/networks/{networkId}/advance-epoch", roles=["NetworkAdmin"], write=True)
def advance_epoch(ctx):
    network = helpers.network_or_404(ctx.path_id("networkId"))
    by_epochs = ctx.body.get("by_epochs")
    if isinstance(by_epochs, bool) or not isinstance(by_epochs, int):
        raise ApiError("ERR_INVALID_REQUEST", "by_epochs must be a positive integer")
    if by_epochs <= 0 or by_epochs > 12:
        raise ApiError("ERR_INVALID_REQUEST", "by_epochs must be between 1 and 12")

    current = int(network.get("allocation_epoch_index") or 0)
    target = current + by_epochs

    # A period may not be closed while its settlement is still unresolved; the
    # check runs before the epoch moves at all.
    for qualification in db.all_records("rebate_qualifications"):
        if qualification["status"] != "PENDING":
            continue
        if int(qualification.get("period_epoch_index") or 0) <= target:
            program = db.get("rebate_programs", qualification.get("rebate_program_id"))
            if program is not None and program.get("network_id") == network["id"]:
                raise ApiError("ERR_OPEN_REBATE_CLAIMS_EXIST")

    network["allocation_epoch_index"] = target

    # Expiry of uncommitted grants whose epoch has arrived.
    for grant in db.all_records("shortage_allocations"):
        parent = db.get("drug_shortages", grant.get("shortage_id"))
        if parent is None or parent.get("network_id") != network["id"]:
            continue
        if int(grant.get("expires_epoch_index") or 0) <= target:
            if grant["status"] in ("GRANTED", "PARTIALLY_COMMITTED"):
                shortage_service.expire_grant(grant)

    # Departures land because the epoch arrived, not because anyone called.
    for practice in db.where("practices", network_id=network["id"]):
        if practice["affiliation_status"] != "DEPARTING":
            continue
        effective = practice.get("departure_effective_epoch_index")
        if effective is None or int(effective) > target:
            continue
        _complete_departure(practice, network)

    # Unverified pending periods past their epoch are disqualified.
    for qualification in db.all_records("rebate_qualifications"):
        practice = db.get("practices", qualification.get("practice_id"))
        if practice is None or practice.get("network_id") != network["id"]:
            continue
        period = int(qualification.get("period_epoch_index") or 0)
        if qualification["status"] == "PENDING" and period < target and not qualification.get(
            "compliance_report_verified"
        ):
            qualification["status"] = "DISQUALIFIED"
            qualification["rebate_amount_cents"] = 0
            db.touch(qualification)
            rebates.mark_practice_mirror(practice)
        elif qualification["status"] in ("QUALIFIED", "PAID") and period < target:
            rebates.refresh_qualification(qualification)
            db.touch(qualification)

    helpers.recompute_freeze(network)
    db.touch(network)
    return serial(network)


def _complete_departure(practice, network):
    practice["affiliation_status"] = "DEPARTED"
    for agreement in db.where("pricing_agreements", practice_id=practice["id"]):
        if agreement["status"] == "ACTIVE":
            agreement["status"] = "SUPERSEDED"
            agreement["superseded_by_agreement_id"] = None
            agreement["status_changed_by"] = "DEPARTURE_UNWIND"
            db.touch(agreement)
    practice["pathway_steering_status"] = "NOT_ADOPTED"
    practice["pathway_adherence_pct"] = 0.0
    for contract in db.where("affiliation_contracts", practice_id=practice["id"]):
        if contract["status"] in ("DEPARTURE_NOTICE", "ACTIVE"):
            contract["status"] = "UNWIND_IN_PROGRESS"
            remaining = [
                a
                for a in db.where("pricing_agreements", practice_id=practice["id"])
                if a["status"] != "SUPERSEDED"
            ]
            contract["pricing_agreements_unwound"] = not remaining
            db.touch(contract)
    db.touch(practice)


@route("POST", "/networks/{networkId}/freeze-commercial-terms", roles=["NetworkAdmin"], write=True)
def freeze_terms(ctx):
    network = helpers.network_or_404(ctx.path_id("networkId"))
    if network.get("is_commercial_terms_frozen"):
        raise ApiError("ERR_TERMS_ALREADY_FROZEN")
    helpers.order_freeze(network, True)
    db.touch(network)
    return serial(network)


@route("POST", "/networks/{networkId}/unfreeze-commercial-terms", roles=["NetworkAdmin"], write=True)
def unfreeze_terms(ctx):
    network = helpers.network_or_404(ctx.path_id("networkId"))
    helpers.order_freeze(network, False)
    db.touch(network)
    return serial(network)


@route(
    "GET",
    "/networks/{networkId}/reporting/rebate-share",
    roles=["NetworkAdmin", "NetworkAnalyst", "PlatformAdmin"],
)
def rebate_share_report(ctx):
    network = helpers.network_or_404(ctx.path_id("networkId"))
    practice_id = ctx.q("practice_id")
    practice = db.get("practices", practice_id) if practice_id else None

    program_id = ctx.q("rebate_program_id")
    program = db.get("rebate_programs", program_id) if program_id else None

    start = ctx.q_dt("window_start_at")
    end = ctx.q_dt("window_end_at")
    if start is None and end is None and program is not None:
        start, end = helpers.epoch_window(network, program.get("period_epoch_index"))

    if practice is None:
        return {
            "practice_id": None,
            "provisional_network_spend_cents": 0,
            "final_network_spend_cents": 0,
            "routing_denominator_cents": 0,
            "market_share_pct": 0.0,
            "denial_ratio": 0.0,
        }

    scope = (program.get("drug_ndc_scope") if program is not None else None) or "ALL"
    provisional, final, fallback = pricing.spend_variants(practice["id"], scope, (start, end))
    denominator, _rider = pricing.routing_denominator(practice, (start, end))
    share = 0.0 if denominator == 0 else ratio4(Decimal(provisional) / Decimal(denominator))
    return {
        "practice_id": practice["id"],
        "provisional_network_spend_cents": provisional,
        "final_network_spend_cents": final,
        "routing_denominator_cents": denominator,
        "market_share_pct": share,
        "denial_ratio": helpers.denial_ratio_reported(practice),
    }