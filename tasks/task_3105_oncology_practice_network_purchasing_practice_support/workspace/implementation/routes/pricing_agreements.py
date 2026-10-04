"""Practice pricing agreements: the cyclic draft/approval loop and the window
conflict model."""

from decimal import Decimal

import db
from errors import ApiError
from registry import route
from routes._shared import filtered, paginate, serial
from services import helpers, rebates
from services.helpers import as_bool, as_dt, as_enum, as_num, check_occ
from utils import parse_iso

READ_ROLES = [
    "NetworkAdmin",
    "PracticeAdmin",
    "RevenueCycleManager",
    "NetworkAnalyst",
    "PlatformAdmin",
]
MAX_DISCOUNT_PCT = Decimal("0.35")


@route(
    "POST",
    "/networks/practices/{practiceId}/pricing-agreements",
    roles=["PracticeAdmin", "NetworkAdmin"],
    status=201,
    write=True,
)
def create_agreement(ctx):
    practice = helpers.practice_or_404(ctx.path_id("practiceId"))
    helpers.may_edit_practice(ctx.principal, practice["id"])
    network = helpers.network_or_404(practice["network_id"])
    if network.get("is_commercial_terms_frozen"):
        raise ApiError("ERR_TERMS_FROZEN")

    data = ctx.body
    tier = as_enum(data, "tier_level", ("TIER_1", "TIER_2", "TIER_3"), required_=True)
    discount = as_num(data, "discount_pct", required_=True)
    if discount < 0 or discount > MAX_DISCOUNT_PCT:
        raise ApiError("ERR_INVALID_REQUEST", "discount_pct must be between 0 and 0.35")
    effective_from = as_dt(data, "effective_from", required_=True)
    effective_to = as_dt(data, "effective_to", default=None)

    agreement = db.create(
        "pricing_agreements",
        {
            "practice_id": practice["id"],
            "tier_level": tier,
            "discount_pct": float(discount),
            "routing_includes_out_of_scope": as_bool(
                data, "routing_includes_out_of_scope", default=False
            ),
            "effective_from": _fmt(effective_from),
            "effective_to": _fmt(effective_to) if effective_to else None,
            "status": "DRAFT",
            "approved_by_user_id": None,
            "submitted_by_user_id": ctx.principal.user_id,
            "status_changed_by": "MANUAL",
            "superseded_by_agreement_id": None,
        },
    )
    return serial(agreement), 201


def _fmt(dt):
    from utils import fmt_ts

    return fmt_ts(dt)


@route("GET", "/networks/pricing-agreements", roles=READ_ROLES)
def list_agreements(ctx):
    rows = filtered(
        db.all_records("pricing_agreements"),
        ctx,
        {
            "practice_id": "practice_id",
            "status": "status",
            "tier_level": "tier_level",
        },
    )
    network_id = ctx.q("network_id")
    if network_id:
        rows = [
            a
            for a in rows
            if helpers.network_id_of(a) == network_id
        ]
    return paginate(ctx, rows)


@route("GET", "/networks/pricing-agreements/{agreementId}", roles=READ_ROLES)
def get_agreement(ctx):
    return serial(helpers.agreement_or_404(ctx.path_id("agreementId")))


@route("POST", "/networks/pricing-agreements/{agreementId}/submit", roles=["PracticeAdmin"], write=True)
def submit_agreement(ctx):
    agreement = helpers.agreement_or_404(ctx.path_id("agreementId"))
    practice = helpers.practice_or_404(agreement["practice_id"])
    helpers.may_edit_practice(ctx.principal, practice["id"])
    network = helpers.network_or_404(practice["network_id"])

    # Priority 3.5 — the stale-version check runs ahead of any business logic.
    check_occ(ctx.body, practice)

    # Priority 4 — the temporal conflict precedes the state and affiliation
    # conditions that would otherwise guard the submission. PRD §2.6 pins this
    # ordering explicitly, so the window check runs unconditionally rather than
    # only when the row happens to be DRAFT.
    _check_window_overlap(agreement, practice)

    if agreement["status"] != "DRAFT":
        raise ApiError("ERR_AGREEMENT_NOT_DRAFT")
    if network.get("is_commercial_terms_frozen"):
        raise ApiError("ERR_TERMS_FROZEN")
    if practice["affiliation_status"] != "AFFILIATED":
        raise ApiError("ERR_PRACTICE_NOT_AFFILIATED")

    effective_from = parse_iso(agreement.get("effective_from"))
    earliest = helpers.earliest_contract_start(practice["id"])
    if earliest is not None and effective_from is not None:
        if effective_from < parse_iso(earliest):
            raise ApiError("ERR_PRICING_WINDOW_BEFORE_CONTRACT")

    agreement["status"] = "PENDING_APPROVAL"
    agreement["submitted_by_user_id"] = ctx.principal.user_id
    db.touch(agreement)
    # Submitting advances the practice's version, which is exactly why the
    # stale-version guard exists on the next write.
    db.touch(practice)
    return serial(agreement)


def _check_window_overlap(agreement, practice, exclude_self=True):
    if agreement.get("effective_to") is not None:
        start = parse_iso(agreement.get("effective_from"))
        end = parse_iso(agreement.get("effective_to"))
        if end is not None and start is not None and not (end > start):
            raise ApiError("ERR_INVALID_EFFECTIVE_WINDOW")
    a_start = parse_iso(agreement.get("effective_from"))
    a_end = parse_iso(agreement.get("effective_to"))
    for other in helpers.agreements_of(practice["id"]):
        if exclude_self and other["id"] == agreement["id"]:
            continue
        if other.get("tier_level") != agreement.get("tier_level"):
            continue
        if other["status"] not in ("PENDING_APPROVAL", "ACTIVE"):
            continue
        if helpers.windows_intersect(
            a_start, a_end, parse_iso(other.get("effective_from")), parse_iso(other.get("effective_to"))
        ):
            raise ApiError("ERR_PRICING_WINDOW_OVERLAP")


@route("POST", "/networks/pricing-agreements/{agreementId}/approve", roles=["NetworkAdmin"], write=True)
def approve_agreement(ctx):
    agreement = helpers.agreement_or_404(ctx.path_id("agreementId"))
    practice = helpers.practice_or_404(agreement["practice_id"])
    if agreement["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_AGREEMENT_NOT_PENDING")

    approver = ctx.principal.user_id
    if agreement.get("submitted_by_user_id") and approver == agreement["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if approver == practice["id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    agreement["status"] = "ACTIVE"
    agreement["approved_by_user_id"] = approver
    a_start = parse_iso(agreement.get("effective_from"))
    a_end = parse_iso(agreement.get("effective_to"))
    for other in helpers.agreements_of(practice["id"]):
        if other["id"] == agreement["id"]:
            continue
        if other["status"] != "ACTIVE" or other.get("tier_level") != agreement.get("tier_level"):
            continue
        if helpers.windows_intersect(
            a_start, a_end, parse_iso(other.get("effective_from")), parse_iso(other.get("effective_to"))
        ):
            other["status"] = "SUPERSEDED"
            other["superseded_by_agreement_id"] = agreement["id"]
            other["status_changed_by"] = "AGREEMENT_APPROVAL"
            db.touch(other)

    practice["tier_level"] = agreement["tier_level"]
    for qualification in db.where("rebate_qualifications", practice_id=practice["id"]):
        if qualification["status"] in ("PENDING", "QUALIFIED"):
            rebates.refresh_qualification(qualification)
            db.touch(qualification)

    db.touch(agreement)
    db.touch(practice)
    return serial(agreement)


@route(
    "POST",
    "/networks/pricing-agreements/{agreementId}/return-to-draft",
    roles=["NetworkAdmin"],
    write=True,
)
def return_to_draft(ctx):
    agreement = helpers.agreement_or_404(ctx.path_id("agreementId"))
    if agreement["status"] == "PENDING_APPROVAL":
        agreement["status"] = "DRAFT"
        agreement["approved_by_user_id"] = None
    elif agreement["status"] == "ACTIVE":
        practice = helpers.practice_or_404(agreement["practice_id"])
        in_use = any(
            o["status"] in ("CONFIRMED", "SHIPPED", "RECEIVED")
            for o in db.where("purchase_orders", practice_id=practice["id"])
            if o.get("pricing_tier_applied") == agreement.get("tier_level")
        )
        if in_use:
            raise ApiError("ERR_AGREEMENT_IN_USE")
        agreement["status"] = "DRAFT"
        agreement["approved_by_user_id"] = None
    else:
        raise ApiError("ERR_AGREEMENT_NOT_PENDING")
    db.touch(agreement)
    return serial(agreement)


@route("POST", "/networks/pricing-agreements/{agreementId}/reject", roles=["NetworkAdmin"], write=True)
def reject_agreement(ctx):
    agreement = helpers.agreement_or_404(ctx.path_id("agreementId"))
    if agreement["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_AGREEMENT_NOT_PENDING")
    agreement["status"] = "REJECTED"
    db.touch(agreement)
    return serial(agreement)


@route("POST", "/networks/pricing-agreements/{agreementId}/reinstate", roles=["NetworkAdmin"], write=True)
def reinstate_agreement(ctx):
    agreement = helpers.agreement_or_404(ctx.path_id("agreementId"))
    practice = helpers.practice_or_404(agreement["practice_id"])
    if agreement["status"] != "SUSPENDED":
        raise ApiError("ERR_AGREEMENT_NOT_SUSPENDED")
    threshold = Decimal(str(practice.get("denial_ratio_threshold_pct", "0.20")))
    if helpers.denial_ratio_exact(practice) > threshold:
        raise ApiError("ERR_DENIAL_RATIO_STILL_BREACHED")
    agreement["status"] = "ACTIVE"
    helpers.recompute_tier(practice)
    db.touch(agreement)
    db.touch(practice)
    return serial(agreement)