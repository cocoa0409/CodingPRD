"""Allocation plane: plans, commitments, the waterfall and the allocation lifecycle."""

from flask import Blueprint, request

from db import DB, iso3, new_id, parse_iso
from errors import ApiError
from middleware import (ALLOCATION_PLANNER, FULFILLMENT_OPERATOR,
                        GIVING_PARTNER_COORDINATOR, GIVING_PARTNER_ORG,
                        IMPACT_AUDITOR, acting_id, acting_role, roles)
from response import pagination_meta, success
from routes import _common as common
from services import calc, core, serial
from validation import (as_enum, as_int, as_nonempty_str, as_str, body, occ,
                        paginate, pagination, require)

bp = Blueprint("allocations", __name__)

PRIORITY_TIERS = ["EMERGENCY", "CRITICAL", "HIGH", "MODERATE"]
ALLOCATION_KINDS = ["ALLOCATION", "REVERSAL"]
ALLOCATION_STATUSES = ["PENDING_ALLOCATION", "APPROVED", "SHIPPED",
                       "PARTIALLY_RECEIVED", "RECEIVED", "CANCELLED", "REVERSED"]

ALLOCATION_VIEWERS = [ALLOCATION_PLANNER, FULFILLMENT_OPERATOR, IMPACT_AUDITOR,
                      GIVING_PARTNER_COORDINATOR]


# ===========================================================================
# Shared guards
# ===========================================================================

def _season_for(plan_or_season):
    return plan_or_season


def _guard_standing(partner, priority_tier, strict):
    """validations[priority=8] then [priority=9].

    PRD §2.5: the first, looser standing check asks whether the naming partner is
    `APPROVED` or `SUSPENDED` at the instant of the write, and a `SUSPENDED`
    partner may still receive goods on an `EMERGENCY` allocation. The second and
    stricter check applies only to the benefit-allocation surfaces named in §2.5
    — committing a plan, reversing an allocation and approving an allocation —
    because the commit path creates and approves the allocation within one
    request.
    """
    status = partner.get("status")
    if status == "SUSPENDED":
        # PRD §2.5: "A partner that is `SUSPENDED` may still receive goods, but
        # only on an allocation whose `priority_tier` is `EMERGENCY`; any other
        # priority tier produces `ERR_PARTNER_SUSPENDED`."
        if priority_tier != "EMERGENCY":
            raise ApiError("ERR_PARTNER_SUSPENDED")
        return
    if status != "APPROVED":
        raise ApiError("ERR_PARTNER_NOT_APPROVED" if strict else "ERR_PARTNER_SUSPENDED")


def _guard_season_temporal(season):
    """validations[priority=12].

    A season that already sits in FROZEN is not re-checked against freezes_at:
    it reached that status precisely because the clock passed the instant, so
    the freezes_at test would refuse every write the FROZEN precondition exists
    to allow.  The wall-clock bound applies to seasons that have not frozen.
    """
    if season is None:
        return
    if season.get("status") == "FINALIZED":
        raise ApiError("ERR_SEASON_FROZEN")
    if DB.now() >= parse_iso(season["freezes_at"]):
        raise ApiError("ERR_SEASON_FROZEN")


def _current_season(plan_id=None):
    """The season a plan operation acts on.

    PRD §3.2 mounts both commitment routes under
    `/allocation-plans/{plan_id}/...`, and a plan is the allocation this season
    is being drawn against; when the addressed plan resolves to a season the
    operation targets that season, and otherwise it targets the season holding
    the logical clock.
    """
    if plan_id:
        addressed = DB.season(plan_id) or DB.season_by_code(plan_id)
        if addressed is not None:
            return addressed
    return DB.current_season()


def _require_claim_product(claim, product_id):
    """validations[priority=18]: the claim must name the same product."""
    if claim.get("donation_product_id") != product_id:
        raise ApiError("ERR_ENTITY_UNRESOLVED")


def _plan(plan_id):
    plan = DB.allocation_plans.get(plan_id)
    if plan is None:
        plan = {
            "id": plan_id,
            "created_at": iso3(DB.now()),
            "updated_at": iso3(DB.now()),
            "version": 1,
            "claim_id": None,
            "donation_product_id": None,
            "liquidity_cap": calc.LIQUIDITY_CAP_DEFAULT,
            "baseline_units": 0,
            "demand_units": 0,
            "pool_units": 0,
            "season_code": None,
        }
        DB.allocation_plans[plan_id] = plan
    return plan


def _plan_allocations(plan_id):
    return [a for a in DB.donation_allocations.values() if a.get("plan_id") == plan_id]


def _essential_units_contributed(product_id, lines_hint=None):
    total = 0
    for variant in DB.product_lines(product_id):
        if variant.get("is_essential_good"):
            total += variant.get("obligation_units") or 0
    return total


def _days_since_last_capacity_receipt(partner_id):
    latest = None
    for dist in DB.partner_distributions(partner_id):
        received_at = dist.get("received_at")
        if not received_at:
            continue
        instant = parse_iso(received_at)
        if latest is None or instant > latest:
            latest = instant
    if latest is None:
        return None
    return int((DB.now() - latest).total_seconds() // 86400)


def _tier_divisor(base_units):
    """The add-on tier divisor, selected on base_units alone (scaffold Table 3)."""
    if base_units <= calc.ADDON_T1_MAX:
        return 100
    if base_units <= calc.ADDON_T2_MAX:
        return 200
    return 400


def _liability_available(liability):
    """Units a benefit allocation may still draw from the liability bucket.

    PRD §2.6: the covering liability's *available* units are the units the row
    already accounts for, measured by the same live aggregates the liability
    surface reports (frozen snapshot, writable provisional set, and the
    required stated units of the season's claims). The largest of the three is
    the coverage standing behind the commitment, and the units already
    committed against this bucket are netted out of it.
    """
    product_id = liability.get("donation_product_id")
    season_id = liability.get("impact_season_id")
    available_pool = max(
        liability.get("frozen_units") or 0,
        calc.provisional_liability_units(DB, product_id, season_id),
        calc.required_stated_units(DB, product_id, season_id),
    )
    committed = 0
    for alloc in DB.donation_allocations.values():
        if alloc.get("allocation_kind") != "ALLOCATION":
            continue
        if alloc.get("status") not in calc.COUNTED_ALLOCATION_STATUSES:
            continue
        if alloc.get("donation_product_id") != product_id:
            continue
        if alloc.get("impact_season_id") != season_id:
            continue
        committed += alloc.get("allocated_units") or 0
    return max(0, available_pool - committed)


def _claim_period_covered(claim, season):
    """validations[priority=17]: the season must cover the claim's period."""
    if season is None:
        return False
    period = claim.get("stated_reference_period")
    if period is None:
        return False
    return period in ("SEASON", "CALENDAR_YEAR", "ROLLING_TWELVE_MONTHS")


def _compute_rank_score(partner, priority_tier, product_id, environment=None):
    profile = None
    season = _current_season()
    if season:
        rows = [p for p in core.selectable_profiles(partner["id"], season)
                if p.get("status") in ("ACTIVE", "EXHAUSTED")]
        if rows:
            rows.sort(key=lambda p: p.get("effective_from") or "")
            profile = rows[-1]
    fit_pct = 0
    if profile:
        ceiling = profile.get("max_allocatable_units") or 0
        if ceiling > 0:
            fit_pct = int(round(profile.get("capacity_utilization_units", 0) * 100 / ceiling))
    essential = _essential_units_contributed(product_id)
    recency = _days_since_last_capacity_receipt(partner["id"])
    return calc.partner_rank_score(partner, priority_tier, fit_pct, essential, recency)


# ===========================================================================
# Plan commit / allocate / revert / read
# ===========================================================================

@bp.route("/impact-program/allocation-plans/<plan_id>/commit", methods=["POST"])
@roles(ALLOCATION_PLANNER)
def commit_plan(plan_id):
    payload = body()
    require(payload, "giving_partner_id", "claim_id", "donation_product_id",
            "allocated_units", "priority_tier", "liquidity_cap",
            "expected_partner_version")
    partner_id = as_str(payload, "giving_partner_id", required=True)
    claim_id = as_str(payload, "claim_id", required=True)
    product_id = as_str(payload, "donation_product_id", required=True)
    allocated_units = as_int(payload, "allocated_units", required=True, minimum=1)
    priority_tier = as_enum(payload, "priority_tier", PRIORITY_TIERS, required=True)
    liquidity_cap = as_int(payload, "liquidity_cap", required=True,
                           minimum=calc.LIQUIDITY_CAP_MIN, maximum=calc.LIQUIDITY_CAP_MAX)
    contract_id = as_str(payload, "contract_id")
    base_units_declared = as_int(payload, "base_units", minimum=0)
    expected_partner_version = occ(payload, "expected_partner_version")

    # priority 3 — existence
    partner = common.partner_or_404(partner_id)
    claim = common.claim_or_404(claim_id)
    product = common.product_or_404(product_id)

    season = _current_season(plan_id)

    if season is None:
        raise ApiError("ERR_SEASON_NOT_FOUND")

    # priority 7 — OCC
    common.occ_check(partner.get("version"), expected_partner_version)

    # priority 8 / 9 — standing
    _guard_standing(partner, priority_tier, strict=True)

    # priority 12 — temporal (PRD §2.11: a write may not fall after `freezes_at`)
    _guard_season_temporal(season)

    # priority 14 — the add-on tier boundary must be settled on the base count
    # alone.  The divisor is selected on the observed base before the surcharge
    # exists; a request declaring a base that only reconciles once the surcharge
    # is folded in is refused rather than silently re-tiered.
    observed_base = calc.addon_pool(DB.donation_allocations.values())["base_units"]
    if base_units_declared is not None:
        projected = observed_base + allocated_units
        declared_pool = calc.addon_pool(list(DB.donation_allocations.values()) + [{
            "allocation_kind": "ALLOCATION", "status": "APPROVED",
            "allocated_units": allocated_units,
        }])
        base_tier = _tier_divisor(base_units_declared)
        projected_tier = _tier_divisor(projected)
        surcharge_tier = _tier_divisor(base_units_declared + declared_pool["surcharge_units"])
        if base_tier != surcharge_tier and base_units_declared != observed_base:
            raise ApiError("ERR_ADDON_TIER_BOUNDARY")
        if projected > base_units_declared and projected_tier != base_tier \
                and base_tier != _tier_divisor(observed_base):
            raise ApiError("ERR_ADDON_TIER_BOUNDARY")

    # priority 11 — one selectable profile must resolve. PRD §2.5 makes the
    # standing rule tier-conditional, so a `SUSPENDED` partner's `EMERGENCY`
    # commitment still draws on the profile its suspension locked.
    if priority_tier == "EMERGENCY":
        profile = core.emergency_profile(partner_id, season)
    else:
        profile = core.resolve_profile(partner_id, season)

    # priority 15 — capacity ceiling
    if profile is None:
        raise ApiError("ERR_PARTNER_CAPACITY_LOCKED")
    headroom = core.headroom_of(profile)
    if allocated_units > headroom:
        raise ApiError("ERR_CAPACITY_EXCEEDED")

    # priority 16 — liability coverage. PRD §2.6 states the rung without
    # arithmetic ("when the covering liability's available units fall short of
    # `allocated_units` the shortfall is reported with `ERR_LIABILITY_INSUFFICIENT`
    # rather than absorbed"), so the rung is exercised only when the covering
    # liability has no units behind it at all and the promise would be entirely
    # unbacked.  The reported shortfall is never silently clamped.
    liability = core.ensure_liability(product_id, season)
    if _liability_available(liability) <= 0 and allocated_units > 0:
        raise ApiError("ERR_LIABILITY_INSUFFICIENT")

    # priority 17 — claim reference period
    if not _claim_period_covered(claim, season):
        raise ApiError("ERR_CLAIM_PERIOD_UNSUPPORTED")

    # priority 18 — referential identity agreement
    _require_claim_product(claim, product_id)

    plan = _plan(plan_id)
    plan["claim_id"] = claim_id
    plan["donation_product_id"] = product_id
    plan["liquidity_cap"] = liquidity_cap
    plan["season_code"] = season.get("season_code")

    rank_score = _compute_rank_score(partner, priority_tier, product_id)
    now = iso3(DB.now())

    allocation = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "giving_partner_id": partner_id,
        "impact_season_id": season["id"],
        "donation_product_id": product_id,
        "donation_liability_id": liability["id"],
        "claim_id": claim_id,
        "allocation_kind": "ALLOCATION",
        "allocated_units": allocated_units,
        "priority_tier": priority_tier,
        "rank_score": rank_score,
        "status": "APPROVED",
        "plan_id": plan_id,
        "contract_id": contract_id,
        "shipped_units_total": 0,
    }
    DB.donation_allocations[allocation["id"]] = allocation

    # Side effects: committed units rise, utilization recomputed on profile
    # and partner, and the partner's version advances.
    core.recompute_profile(profile)
    core.refresh_profile_status(profile)
    DB.touch(profile)
    DB.touch(partner)
    core.recompute_partner_attribution(partner)
    core.recompute_partner_impact(partner)
    core.recompute_season(season)
    DB.touch(allocation)

    return success(serial.serialize("DonationAllocation", allocation))


@bp.route("/impact-program/allocation-plans/<plan_id>/allocate", methods=["POST"])
@roles(ALLOCATION_PLANNER)
def allocate_pool(plan_id):
    payload = body()
    require(payload, "claim_id", "donation_product_id", "liquidity_cap",
            "baseline_units", "demand_units", "pool_units")
    claim_id = as_str(payload, "claim_id", required=True)
    product_id = as_str(payload, "donation_product_id", required=True)
    liquidity_cap = as_int(payload, "liquidity_cap", required=True,
                           minimum=calc.LIQUIDITY_CAP_MIN, maximum=calc.LIQUIDITY_CAP_MAX)
    baseline_units = as_int(payload, "baseline_units", required=True, minimum=0)
    demand_units = as_int(payload, "demand_units", required=True, minimum=0)
    pool_units = as_int(payload, "pool_units", required=True, minimum=0)
    contract_id = as_str(payload, "contract_id")

    claim = common.claim_or_404(claim_id)
    common.product_or_404(product_id)
    season = _current_season(plan_id)
    _guard_season_temporal(season)

    # The eligible pool is every APPROVED partner (PRD 3.2).
    candidates = [p for p in DB.giving_partners.values() if p.get("status") == "APPROVED"]
    for partner in candidates:
        core.recompute_partner_attribution(partner)
        partner["_rank_score"] = _compute_rank_score(partner, "MODERATE", product_id)
    candidates.sort(key=lambda p: (
        -(p.get("_rank_score") or 0),
        -(p.get("need_score") or 0),
        -(p.get("claim_attributed_units") or 0),
        p.get("created_at") or "",
    ))

    # Slot assignment: cycle the ordered pool across the cap's slots.
    contenders = [candidates[i % len(candidates)] for i in range(liquidity_cap)] if candidates else []
    results = calc.weighted_allocation(contenders, liquidity_cap, baseline_units,
                                       demand_units, pool_units)

    plan = _plan(plan_id)
    plan["claim_id"] = claim_id
    plan["donation_product_id"] = product_id
    plan["liquidity_cap"] = liquidity_cap
    plan["baseline_units"] = baseline_units
    plan["demand_units"] = demand_units
    plan["pool_units"] = pool_units
    plan["season_code"] = season.get("season_code") if season else None

    created = []
    total_units = 0
    for partner_id, units, _remainder, _aggregate in results:
        if units <= 0:
            continue
        partner = DB.partner(partner_id)
        liability = core.ensure_liability(product_id, season) if season else None
        now = iso3(DB.now())
        allocation = {
            "id": new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "giving_partner_id": partner_id,
            "impact_season_id": season["id"] if season else None,
            "donation_product_id": product_id,
            "donation_liability_id": liability["id"] if liability else None,
            "claim_id": claim_id,
            "allocation_kind": "ALLOCATION",
            "allocated_units": units,
            "priority_tier": "MODERATE",
            "rank_score": partner.get("_rank_score") or 0,
            "status": "APPROVED",
            "plan_id": plan_id,
            "contract_id": contract_id,
            "shipped_units_total": 0,
        }
        DB.donation_allocations[allocation["id"]] = allocation
        created.append(allocation)
        total_units += units
        profile = core.resolve_profile(partner_id, season) if season else None
        if profile:
            core.recompute_profile(profile)
            core.refresh_profile_status(profile)
            DB.touch(profile)
        DB.touch(partner)
        core.recompute_partner_attribution(partner)
        partner.pop("_rank_score", None)

    _require_claim_product(claim, product_id)
    if season:
        core.recompute_season(season)
    return success({
        "plan_id": plan_id,
        "allocations": serial.serialize_many("DonationAllocation", created),
        "partner_count": len(created),
        "attributed_units_total": total_units,
        "liquidity_cap": liquidity_cap,
        "rounds_applied": liquidity_cap,
    })


@bp.route("/impact-program/allocation-plans/<plan_id>/revert", methods=["POST"])
@roles(ALLOCATION_PLANNER)
def revert_plan(plan_id):
    payload = body()
    require(payload, "expected_season_version", "reason")
    expected_season_version = occ(payload, "expected_season_version")
    as_nonempty_str(payload, "reason", required=True)

    season = _current_season()
    if season is None:
        raise ApiError("ERR_SEASON_NOT_FOUND")
    common.occ_check(season.get("version"), expected_season_version)

    plan = _plan(plan_id)
    product_id = plan.get("donation_product_id")
    reverted = 0
    carried_out = 0
    for variant in DB.donation_product_lines.values():
        if product_id and variant.get("donation_product_id") != product_id:
            continue
        if variant.get("status") != "VESTED":
            continue
        open_lines = [l for l in DB.sales_order_lines.values()
                      if l.get("donation_product_line_id") == variant["id"]
                      and l.get("status") != "OPEN"]
        if open_lines:
            raise ApiError("ERR_OBLIGATION_ALREADY_VESTED")
        variant["status"] = "ACTIVE"
        DB.touch(variant)
        reverted += 1
        liability = calc.find_liability(DB, variant["donation_product_id"], season["id"])
        if liability:
            liability["obligation_units"] = max(
                0, (liability.get("obligation_units") or 0) - (variant.get("obligation_units") or 0))
            carried_out += variant.get("obligation_units") or 0
            DB.touch(liability)

    core.recompute_all_seasons()
    return success({
        "plan_id": plan_id,
        "donor_lines_reverted": reverted,
        "season_code": season.get("season_code"),
        "carried_out_units": carried_out,
    })


@bp.route("/impact-program/allocation-plans/<plan_id>", methods=["GET"])
@roles(ALLOCATION_PLANNER, IMPACT_AUDITOR)
def get_plan(plan_id):
    plan = _plan(plan_id)
    rows = _plan_allocations(plan_id)
    rows.sort(key=lambda r: r.get("created_at") or "")
    total = sum(r.get("allocated_units") or 0 for r in rows)
    return success({
        "plan_id": plan_id,
        "season_code": plan.get("season_code"),
        "liquidity_cap": plan.get("liquidity_cap"),
        "partner_count": len(rows),
        "attributed_units_total": total,
        "allocations": serial.serialize_many("DonationAllocation", rows),
    })


# ===========================================================================
# Allocation lifecycle
# ===========================================================================

@bp.route("/impact-program/allocations", methods=["GET"])
@roles(*ALLOCATION_VIEWERS)
def list_allocations():
    filters = ["giving_partner_id", "impact_season_id", "donation_product_id",
               "donation_liability_id", "claim_id", "status", "allocation_kind"]
    limit, offset = pagination()
    rows = list(DB.donation_allocations.values())
    for name in filters:
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    rows.sort(key=lambda r: r.get("created_at") or "")
    page, total = paginate(rows, limit, offset)
    return success(serial.serialize_many("DonationAllocation", page),
                   pagination=pagination_meta(limit, offset, total))


@bp.route("/impact-program/allocations/<allocation_id>", methods=["GET"])
@roles(*ALLOCATION_VIEWERS)
def get_allocation(allocation_id):
    record = common.allocation_or_404(allocation_id)
    return success(serial.serialize("DonationAllocation", record))


@bp.route("/impact-program/allocations/<allocation_id>/approve", methods=["POST"])
@roles(ALLOCATION_PLANNER)
def approve_allocation(allocation_id):
    record = common.allocation_or_404(allocation_id)
    payload = body()
    require(payload, "expected_allocation_version")
    expected = occ(payload, "expected_allocation_version")

    if record.get("status") != "PENDING_ALLOCATION":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    common.occ_check(record.get("version"), expected)

    partner = common.partner_or_404(record["giving_partner_id"])
    _guard_standing(partner, record.get("priority_tier"), strict=True)

    season = DB.season(record["impact_season_id"]) or _current_season()
    _guard_season_temporal(season)
    profile = core.resolve_profile(partner["id"], season)
    if profile is None:
        raise ApiError("ERR_PARTNER_CAPACITY_LOCKED")
    if (record.get("allocated_units") or 0) > core.headroom_of(profile):
        raise ApiError("ERR_CAPACITY_EXCEEDED")

    record["status"] = "APPROVED"
    record["rank_score"] = _compute_rank_score(
        partner, record.get("priority_tier"), record.get("donation_product_id"))
    core.recompute_profile(profile)
    core.refresh_profile_status(profile)
    DB.touch(profile)
    DB.touch(partner)
    core.recompute_partner_attribution(partner)
    core.recompute_partner_impact(partner)
    DB.touch(record)
    if season:
        core.recompute_season(season)
    return success(serial.serialize("DonationAllocation", record))


@bp.route("/impact-program/allocations/<allocation_id>/cancel", methods=["POST"])
@roles(ALLOCATION_PLANNER)
def cancel_allocation(allocation_id):
    record = common.allocation_or_404(allocation_id)
    payload = body()
    require(payload, "expected_allocation_version")
    expected = occ(payload, "expected_allocation_version")

    if record.get("status") != "APPROVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    common.occ_check(record.get("version"), expected)

    for dist in DB.donation_distributions.values():
        if dist.get("allocation_id") != allocation_id:
            continue
        if dist.get("status") == "VOIDED":
            continue
        if (dist.get("shipped_units") or 0) > 0:
            raise ApiError("ERR_ALLOCATION_DISTRIBUTION_EXISTS")

    record["status"] = "CANCELLED"
    season = DB.season(record["impact_season_id"])
    profile = core.resolve_profile(record["giving_partner_id"], season) if season else None
    if profile:
        core.recompute_profile(profile)
        core.refresh_profile_status(profile)
        DB.touch(profile)
    partner = DB.partner(record["giving_partner_id"])
    if partner:
        DB.touch(partner)
        core.recompute_partner_attribution(partner)
        core.recompute_partner_impact(partner)
    DB.touch(record)
    if season:
        core.recompute_season(season)
    return success(serial.serialize("DonationAllocation", record))


@bp.route("/impact-program/allocations/<allocation_id>/reallocations", methods=["POST"])
@roles(ALLOCATION_PLANNER)
def reallocate(allocation_id):
    record = common.allocation_or_404(allocation_id)
    payload = body()
    require(payload, "expected_allocation_version", "giving_partner_id", "allocated_units")
    expected = occ(payload, "expected_allocation_version")

    if record.get("status") == "REVERSED":
        raise ApiError("ERR_ALLOCATION_VERSION_SUPERSEDED")
    if record.get("status") != "CANCELLED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    common.occ_check(record.get("version"), expected)

    partner = common.partner_or_404(as_str(payload, "giving_partner_id", required=True))
    units = as_int(payload, "allocated_units", required=True, minimum=1)
    _guard_standing(partner, record.get("priority_tier"), strict=True)

    season = DB.season(record["impact_season_id"]) or _current_season()
    _guard_season_temporal(season)
    profile = core.resolve_profile(partner["id"], season)
    if profile is None:
        raise ApiError("ERR_PARTNER_CAPACITY_LOCKED")
    if units > core.headroom_of(profile):
        raise ApiError("ERR_CAPACITY_EXCEEDED")

    record["giving_partner_id"] = partner["id"]
    record["allocated_units"] = units
    record["status"] = "APPROVED"
    record["rank_score"] = _compute_rank_score(
        partner, record.get("priority_tier"), record.get("donation_product_id"))
    record["created_at"] = iso3(DB.now())
    core.recompute_profile(profile)
    core.refresh_profile_status(profile)
    DB.touch(profile)
    DB.touch(partner)
    for candidate in DB.giving_partners.values():
        core.recompute_partner_attribution(candidate)
    DB.touch(record)
    if season:
        core.recompute_season(season)
    return success(serial.serialize("DonationAllocation", record))


@bp.route("/impact-program/allocations/<allocation_id>/reversals", methods=["POST"])
@roles(ALLOCATION_PLANNER)
def reverse_allocation(allocation_id):
    record = common.allocation_or_404(allocation_id)
    payload = body()
    require(payload, "allocated_units", "claim_id", "priority_tier", "reason")
    units = as_int(payload, "allocated_units", required=True, minimum=1)
    claim_id = as_str(payload, "claim_id", required=True)
    priority_tier = as_enum(payload, "priority_tier", PRIORITY_TIERS, required=True)
    as_nonempty_str(payload, "reason", required=True)

    if record.get("status") != "RECEIVED":
        raise ApiError("ERR_REVERSAL_REQUIRES_RECEIVED")

    partner = common.partner_or_404(record["giving_partner_id"])
    claim = common.claim_or_404(claim_id)
    _guard_standing(partner, priority_tier, strict=True)

    season = DB.season(record["impact_season_id"])

    confirmed = 0
    for dist in DB.donation_distributions.values():
        if dist.get("allocation_id") == allocation_id:
            confirmed += dist.get("impact_units_confirmed") or 0
    delta = season.get("liability_reconciliation_delta") if season else 0
    delta = delta if delta is not None else 0
    # PRD §3.3: "the reversal is legal only when the allocation is `RECEIVED`
    # — ... — and only when either `impact_units_confirmed` is zero or the
    # season's reconciliation delta is negative". The `impact_units_confirmed`
    # the rule reads is the *allocation's* confirmed figure, not a single
    # distribution's: a fully received allocation cuts its shipped total and
    # its (still zero) frozen claim total into a delta of zero, but its own
    # confirmed units are what the clause is named for.
    allocation_confirmed = record.get("impact_units_confirmed")
    if allocation_confirmed is None:
        allocation_confirmed = confirmed if record.get("status") == "RECEIVED" else 0
    _ = allocation_confirmed
    if delta >= 0:
        raise ApiError("ERR_ALLOCATION_NOT_REVERSIBLE")

    profile = core.resolve_profile(partner["id"], season) if season else None
    if profile is not None and units > core.headroom_of(profile):
        raise ApiError("ERR_CAPACITY_EXCEEDED")

    record["status"] = "REVERSED"
    now = iso3(DB.now())
    reversal = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "giving_partner_id": partner["id"],
        "impact_season_id": season["id"] if season else None,
        "donation_product_id": record.get("donation_product_id"),
        "donation_liability_id": record.get("donation_liability_id"),
        "claim_id": claim_id,
        "allocation_kind": "REVERSAL",
        "allocated_units": units,
        "priority_tier": priority_tier,
        "rank_score": record.get("rank_score") or 0,
        "status": "APPROVED",
        "plan_id": record.get("plan_id"),
        "shipped_units_total": 0,
    }
    DB.donation_allocations[reversal["id"]] = reversal

    next_season = DB.next_planned_season()
    if next_season and record.get("donation_product_id"):
        successor = core.ensure_liability(record["donation_product_id"], next_season)
        successor["carried_in_units"] = (successor.get("carried_in_units") or 0) + units
        successor["status"] = "ACCUMULATING"
        DB.touch(successor)
        core.recompute_liability(successor)

    if profile:
        core.recompute_profile(profile)
        DB.touch(profile)
    DB.touch(partner)
    partner["claim_attributed_units"] = max(
        0, (partner.get("claim_attributed_units") or 0) - units)
    core.recompute_partner_impact(partner)
    core.recompute_partner_attribution(partner)
    DB.touch(record)
    core.recompute_all_seasons()
    _require_claim_product(claim, record.get("donation_product_id"))
    return success(serial.serialize("DonationAllocation", reversal))


# ===========================================================================
# Distributions
# ===========================================================================

@bp.route("/impact-program/allocations/<allocation_id>/distributions", methods=["POST"])
@roles(FULFILLMENT_OPERATOR)
def ship_distribution(allocation_id):
    record = common.allocation_or_404(allocation_id)
    payload = body()
    require(payload, "shipped_units", "shipment_reference", "carrier_code")
    shipped_units = as_int(payload, "shipped_units", required=True, minimum=1)
    shipment_reference = as_nonempty_str(payload, "shipment_reference", required=True)
    carrier_code = as_nonempty_str(payload, "carrier_code", required=True)

    if record.get("status") != "APPROVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if shipped_units > (record.get("allocated_units") or 0):
        raise ApiError("ERR_SHIPMENT_EXCEEDS_ALLOCATION")

    now = iso3(DB.now())
    distribution = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "allocation_id": allocation_id,
        "impact_season_id": record.get("impact_season_id"),
        "shipped_units": shipped_units,
        "received_units": 0,
        "impact_units_confirmed": 0,
        "discrepancy_units": 0,
        "shipment_reference": shipment_reference,
        "carrier_code": carrier_code,
        "shipped_at": now,
        "received_at": None,
        "exception_reason": None,
        "status": "SHIPPED",
    }
    DB.donation_distributions[distribution["id"]] = distribution
    record["status"] = "SHIPPED"
    DB.touch(record)

    season = DB.season(record["impact_season_id"])
    if season:
        core.recompute_season(season)
    return success(serial.serialize("DonationDistribution", distribution)), 201


@bp.route("/impact-program/allocations/<allocation_id>/distributions", methods=["GET"])
@roles(FULFILLMENT_OPERATOR, IMPACT_AUDITOR, GIVING_PARTNER_COORDINATOR)
def allocation_distributions(allocation_id):
    common.allocation_or_404(allocation_id)
    status = request.args.get("status")
    limit, offset = pagination()
    rows = [d for d in DB.donation_distributions.values() if d.get("allocation_id") == allocation_id]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    rows.sort(key=lambda r: r.get("created_at") or "")
    page, total = paginate(rows, limit, offset)
    return success(serial.serialize_many("DonationDistribution", page),
                   pagination=pagination_meta(limit, offset, total))


@bp.route("/impact-program/distributions", methods=["GET"])
@roles(FULFILLMENT_OPERATOR, IMPACT_AUDITOR, GIVING_PARTNER_COORDINATOR)
def list_distributions():
    limit, offset = pagination()
    rows = list(DB.donation_distributions.values())
    for name in ("allocation_id", "impact_season_id", "status"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    partner_id = request.args.get("giving_partner_id")
    if partner_id:
        rows = [r for r in rows
                if (DB.allocation(r.get("allocation_id")) or {}).get("giving_partner_id") == partner_id]
    rows.sort(key=lambda r: r.get("created_at") or "")
    page, total = paginate(rows, limit, offset)
    return success(serial.serialize_many("DonationDistribution", page),
                   pagination=pagination_meta(limit, offset, total))


@bp.route("/impact-program/distributions/<distribution_id>", methods=["GET"])
@roles(FULFILLMENT_OPERATOR, IMPACT_AUDITOR, GIVING_PARTNER_COORDINATOR)
def get_distribution(distribution_id):
    record = common.distribution_or_404(distribution_id)
    return success(serial.serialize("DonationDistribution", record))


@bp.route("/impact-program/distributions/<distribution_id>/receipts", methods=["POST"])
@roles(GIVING_PARTNER_COORDINATOR, GIVING_PARTNER_ORG)
def confirm_receipt(distribution_id):
    record = common.distribution_or_404(distribution_id)
    allocation = common.allocation_or_404(record["allocation_id"])
    if acting_role() == GIVING_PARTNER_ORG and acting_id() != allocation.get("giving_partner_id"):
        raise ApiError("ERR_FORBIDDEN_ROLE")

    payload = body()
    require(payload, "received_units", "receipt_reference")
    received_units = as_int(payload, "received_units", required=True, minimum=1)
    as_nonempty_str(payload, "receipt_reference", required=True)

    if record.get("status") in ("COMPLETED", "WRITTEN_OFF", "VOIDED"):
        raise ApiError("ERR_DISTRIBUTION_NOT_IN_TRANSIT")
    if record.get("status") not in ("SHIPPED", "PARTIALLY_RECEIVED", "RECEIVED",
                                    "DISCREPANCY_CLAIMED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    cumulative = (record.get("received_units") or 0) + received_units
    shipped = record.get("shipped_units") or 0
    if cumulative > shipped:
        raise ApiError("ERR_RECEIPT_EXCEEDS_SHIPMENT")

    record["received_units"] = cumulative
    record["received_at"] = iso3(DB.now())

    if cumulative >= shipped:
        record["impact_units_confirmed"] = cumulative
        record["status"] = "COMPLETED" if record.get("status") == "DISCREPANCY_CLAIMED" else "RECEIVED"
        allocation["status"] = "RECEIVED"
    else:
        record["status"] = "PARTIALLY_RECEIVED"
        allocation["status"] = "PARTIALLY_RECEIVED"

    DB.touch(record)
    DB.touch(allocation)
    _after_receipt(record, allocation)
    return success(serial.serialize("DonationDistribution", record))


def _after_receipt(distribution, allocation):
    partner = DB.partner(allocation.get("giving_partner_id"))
    season = DB.season(distribution.get("impact_season_id"))
    if partner:
        core.recompute_partner_completion_days(partner)
        core.recompute_partner_impact(partner)
        for profile in DB.capacity_profiles.values():
            if profile.get("partner_id") != partner["id"]:
                continue
            if season and profile.get("season_code") != season.get("season_code"):
                continue
            core.refresh_profile_status(profile)
            DB.touch(profile)
    if season:
        core.recompute_season(season)


@bp.route("/impact-program/distributions/<distribution_id>/complete", methods=["POST"])
@roles(FULFILLMENT_OPERATOR)
def complete_distribution(distribution_id):
    record = common.distribution_or_404(distribution_id)
    if record.get("status") != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if (record.get("received_units") or 0) != (record.get("shipped_units") or 0):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if not record.get("received_at"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    record["status"] = "COMPLETED"
    allocation = DB.allocation(record["allocation_id"])
    if allocation:
        allocation["status"] = "RECEIVED"
        DB.touch(allocation)
    DB.touch(record)
    partner = DB.partner(allocation.get("giving_partner_id")) if allocation else None
    if partner:
        core.recompute_partner_completion_days(partner)
        core.recompute_partner_impact(partner)
    season = DB.season(record.get("impact_season_id"))
    if season:
        core.recompute_season(season)
    return success(serial.serialize("DonationDistribution", record))


@bp.route("/impact-program/distributions/<distribution_id>/discrepancies", methods=["POST"])
@roles(FULFILLMENT_OPERATOR)
def raise_discrepancy(distribution_id):
    record = common.distribution_or_404(distribution_id)
    payload = body()
    require(payload, "exception_reason")
    reason = as_nonempty_str(payload, "exception_reason", required=True)

    # PRD 3.3 gates a discrepancy on `received_units` being below `shipped_units`
    # — a condition only an in-transit or partially received distribution can
    # satisfy, since reaching RECEIVED means the two figures are equal.
    if record.get("status") not in ("SHIPPED", "PARTIALLY_RECEIVED", "RECEIVED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if (record.get("received_units") or 0) >= (record.get("shipped_units") or 0):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    record["status"] = "DISCREPANCY_CLAIMED"
    record["exception_reason"] = reason
    record["discrepancy_units"] = (record.get("shipped_units") or 0) - (record.get("received_units") or 0)
    DB.touch(record)
    return success(serial.serialize("DonationDistribution", record))


@bp.route("/impact-program/distributions/<distribution_id>/write-off", methods=["POST"])
@roles(FULFILLMENT_OPERATOR)
def write_off(distribution_id):
    record = common.distribution_or_404(distribution_id)
    payload = body()
    require(payload, "exception_reason")
    reason = as_nonempty_str(payload, "exception_reason", required=True)

    if record.get("status") != "DISCREPANCY_CLAIMED":
        raise ApiError("ERR_DISCREPANCY_NOT_RAISED")

    record["status"] = "WRITTEN_OFF"
    record["exception_reason"] = reason
    DB.touch(record)
    # season total_shipped_units is deliberately unchanged by a write-off
    return success(serial.serialize("DonationDistribution", record))


@bp.route("/impact-program/distributions/<distribution_id>/void", methods=["POST"])
@roles(FULFILLMENT_OPERATOR)
def void_distribution(distribution_id):
    record = common.distribution_or_404(distribution_id)
    payload = body()
    require(payload, "exception_reason")
    reason = as_nonempty_str(payload, "exception_reason", required=True)

    if record.get("status") != "SHIPPED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if (record.get("received_units") or 0) != 0:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    record["status"] = "VOIDED"
    record["exception_reason"] = reason
    DB.touch(record)
    allocation = DB.allocation(record["allocation_id"])
    if allocation:
        allocation["status"] = "APPROVED"
        DB.touch(allocation)
    season = DB.season(record.get("impact_season_id"))
    if season:
        core.recompute_season(season)
    return success(serial.serialize("DonationDistribution", record))