"""Derived-field reconciliation and the shared lifecycle operations.

Everything in here is a *recomputation*: given the current rows, re-derive the
denormalised figures the catalogue declares as ``source: computed``.  Routes
call these after they mutate a record, which is also what makes derived
recomputations count as mutations for version purposes (PRD 2.10).
"""

from decimal import Decimal

from db import DB, iso3, parse_iso
from errors import ApiError
from services import calc


# ===========================================================================
# Season aggregates (ImpactSeason)
# ===========================================================================

def recompute_season(season):
    season["liability_carry_in_units"] = sum(
        (l.get("carried_in_units") or 0) for l in DB.season_liabilities(season["id"])
    )
    # PRD §3.5: "the season liability's `provisional_liability_units` is
    # recomputed, the season's `claim_frozen_units_total` is recomputed" — so the
    # season figure tracks the writable provisional set, and §3.1's "the season's
    # frozen claim total" is the same aggregate seen after a freeze snapshot.
    season["claim_frozen_units_total"] = sum(
        ((l.get("frozen_units") or 0) if l.get("freeze_recorded_at")
         else (l.get("provisional_liability_units") or 0))
        for l in DB.season_liabilities(season["id"])
    )
    season["opening_carry_obligation_cents"] = sum(
        (l.get("accrued_obligation_cents") or 0)
        for l in DB.season_liabilities(season["id"]) if l.get("status") == "CARRIED"
    )

    approved_partners = [p for p in DB.giving_partners.values() if p.get("status") == "APPROVED"]
    total_attributed = 0
    for partner in approved_partners:
        recompute_partner_attribution(partner)
        total_attributed += partner.get("claim_attributed_units") or 0
    season["attributed_units_total"] = total_attributed

    shares, total_pct = calc.attributed_percentages(DB, approved_partners, total_attributed)
    for partner in approved_partners:
        partner["attributed_percentage"] = shares.get(partner["id"], 0.0)
    season["attributed_percentage_total"] = total_pct

    rows = DB.season_distributions(season["id"])
    season["total_shipped_units"] = sum(
        (d.get("shipped_units") or 0) for d in rows if d.get("status") != "VOIDED"
    ) + sum((season.get("settled_line_units") or {}).values())
    season["total_received_units"] = sum(
        (d.get("received_units") or 0) for d in rows if d.get("status") != "VOIDED"
    )
    # PRD §3.7 fixes the reported sign: "`liability_reconciliation_delta` is the
    # shipped units minus the frozen claim units, negative when claims understate
    # what actually shipped." The sign convention is what the reversal rule in
    # §3.3 reads, so the delta is reported negative exactly when the season's
    # claims fall short of what shipped.
    season["liability_reconciliation_delta"] = (
        season["claim_frozen_units_total"] - season["total_shipped_units"]
    )
    return season


def recompute_all_seasons():
    for season in DB.impact_seasons.values():
        recompute_season(season)


def season_code_of(season):
    return season.get("season_code") if season else None


# ===========================================================================
# Partner aggregates (GivingPartner)
# ===========================================================================

def recompute_partner_attribution(partner):
    """claim_attributed_units — season allocations minus reversals, floored at 0."""
    total = 0
    for alloc in DB.donation_allocations.values():
        if alloc.get("giving_partner_id") != partner["id"]:
            continue
        if alloc.get("allocation_kind") == "ALLOCATION":
            if alloc.get("status") in ("APPROVED", "SHIPPED", "PARTIALLY_RECEIVED", "RECEIVED"):
                total += alloc.get("allocated_units") or 0
        elif alloc.get("allocation_kind") == "REVERSAL":
            total -= alloc.get("allocated_units") or 0
    partner["claim_attributed_units"] = max(0, total)
    return partner


def attributed_partner_id(product_id):
    """The partner a product's retail units are attributed to.

    Attribution flows through the product's marketing claims: a claim names one
    product and one beneficiary partner (the MarketingClaim <-> GivingPartner
    <-> DonationAllocation coupling).
    """
    claims = [c for c in DB.marketing_claims.values() if c.get("donation_product_id") == product_id]
    if not claims:
        return None
    claims.sort(key=lambda c: (c.get("created_at") or ""), reverse=True)
    return claims[0].get("partner_id")


def recompute_partner_impact(partner):
    """impact_units_total, capacity_utilization_units, impact_units_retail_equivalent."""
    impact = 0
    for dist in DB.partner_distributions(partner["id"]):
        alloc = DB.allocation(dist["allocation_id"])
        if not alloc or alloc.get("allocation_kind") != "ALLOCATION":
            continue
        # PRD §3.3: "Once the cumulative figure reaches `shipped_units`, the
        # distribution becomes `RECEIVED`, `impact_units_confirmed` is set equal
        # to `received_units`" — so the confirmed figure is the completed
        # receipt only, and §3.3's "after the season finalizes — the partner's
        # `impact_units_total`" reads that figure. A distribution still short of
        # its shipment reports no confirmed impact.
        if dist.get("status") in ("WRITTEN_OFF", "VOIDED"):
            continue
        if (dist.get("received_units") or 0) >= (dist.get("shipped_units") or 0):
            impact += dist.get("impact_units_confirmed") or 0
    partner["impact_units_total"] = impact

    utilization = 0
    for profile in DB.capacity_profiles.values():
        if profile.get("partner_id") != partner["id"]:
            continue
        if profile.get("status") == "SUPERSEDED":
            # A superseded profile is a dead version of the same ceiling and
            # must not be double-counted against the partner's live headroom.
            continue
        recompute_profile(profile)
        utilization += profile.get("capacity_utilization_units") or 0
    partner["capacity_utilization_units"] = utilization

    retail_equivalent = 0
    for line in DB.sales_order_lines.values():
        variant = DB.product_line(line.get("donation_product_line_id"))
        if not variant:
            continue
        product = DB.product(variant.get("donation_product_id"))
        if not product:
            continue
        if attributed_partner_id(product["id"]) == partner["id"]:
            retail_equivalent += line.get("quantity") or 0
    partner["impact_units_retail_equivalent"] = retail_equivalent

    partner["latest_vetting_round_id"] = latest_round_id(partner)
    return partner


def recompute_partner_completion_days(partner):
    """Mean whole days between shipped_at and received_at over RECEIVED/COMPLETED."""
    deltas = []
    for dist in DB.partner_distributions(partner["id"]):
        if dist.get("status") not in ("RECEIVED", "COMPLETED"):
            continue
        shipped_at = dist.get("shipped_at")
        received_at = dist.get("received_at")
        if not shipped_at or not received_at:
            continue
        delta = parse_iso(received_at) - parse_iso(shipped_at)
        deltas.append(delta.total_seconds() / 86400.0)
    if not deltas:
        partner["avg_distribution_completion_days"] = None
        return partner
    mean = sum(Decimal(str(d)) for d in deltas) / Decimal(len(deltas))
    partner["avg_distribution_completion_days"] = calc.rhu(mean, 2)


def recompute_partner_entrance_returns(partner):
    """entrance_returns_units — credited/exchanged requests attributed to the partner."""
    total = 0
    for request in DB.return_requests.values():
        if request.get("status") not in ("CREDITED", "EXCHANGED"):
            continue
        line = DB.order_line(request.get("sales_order_line_id"))
        if not line:
            continue
        variant = DB.product_line(line.get("donation_product_line_id"))
        if not variant:
            continue
        product = DB.product(variant.get("donation_product_id"))
        if not product:
            continue
        if attributed_partner_id(product["id"]) == partner["id"]:
            total += request.get("requested_units") or 0
    partner["entrance_returns_units"] = total
    return partner


def latest_round_id(partner):
    rounds = [r for r in DB.vetting_rounds.values() if r.get("partner_id") == partner["id"]]
    if not rounds:
        return None
    rounds.sort(key=lambda r: r.get("round_number") or 0)
    return rounds[-1]["id"]


def recompute_partner(partner):
    recompute_partner_attribution(partner)
    recompute_partner_impact(partner)
    recompute_partner_completion_days(partner)
    recompute_partner_entrance_returns(partner)
    return partner


# ===========================================================================
# Capacity profiles (PartnerCapacityProfile)
# ===========================================================================

def profile_committed_units(profile):
    total = 0
    for alloc in DB.donation_allocations.values():
        if alloc.get("giving_partner_id") != profile.get("partner_id"):
            continue
        if alloc.get("allocation_kind") != "ALLOCATION":
            continue
        if alloc.get("status") not in calc.COUNTED_ALLOCATION_STATUSES:
            continue
        season = DB.season(alloc.get("impact_season_id"))
        if not season:
            continue
        if season.get("season_code") != profile.get("season_code"):
            continue
        total += alloc.get("allocated_units") or 0
    return total


def profile_reserved_units(profile):
    total = 0
    for alloc in DB.donation_allocations.values():
        if alloc.get("giving_partner_id") != profile.get("partner_id"):
            continue
        if alloc.get("allocation_kind") != "REVERSAL":
            continue
        if alloc.get("status") in calc.TERMINAL_ALLOCATION_STATUSES:
            continue
        season = DB.season(alloc.get("impact_season_id"))
        if not season or season.get("season_code") != profile.get("season_code"):
            continue
        total += alloc.get("allocated_units") or 0
    return total


def profile_impact_confirmed(profile):
    total = 0
    partner_id = profile.get("partner_id")
    for dist in DB.partner_distributions(partner_id):
        season = DB.season(dist.get("impact_season_id"))
        if not season or season.get("season_code") != profile.get("season_code"):
            continue
        if dist.get("status") in ("WRITTEN_OFF", "VOIDED"):
            continue
        # PRD §2.6: "`impact_units_confirmed` is the count of units a partner
        # has actually confirmed receiving." That count accumulates across
        # partial receipts, so the live headroom falls as each receipt lands;
        # once the cumulative figure reaches the shipment the two figures are
        # equal (PRD §3.3).
        total += dist.get("received_units") or 0
    return total


def recompute_profile(profile):
    committed = profile_committed_units(profile)
    reserved = profile_reserved_units(profile)
    confirmed = profile_impact_confirmed(profile)
    profile["committed_units"] = committed
    profile["reserved_units"] = reserved
    profile["capacity_utilization_units"] = max(0, committed + reserved - confirmed)
    return profile


def refresh_profile_status(profile):
    """ACTIVE <-> EXHAUSTED from live headroom; LOCKED/SUPERSEDED are sticky."""
    if profile.get("status") in ("LOCKED", "SUPERSEDED"):
        return profile
    recompute_profile(profile)
    # PRD §3.2: "A profile whose owning partner leaves `APPROVED` — that is,
    # whose partner's status is `SUSPENDED` or `INACTIVE` — is moved to
    # `LOCKED`, and it returns to `ACTIVE` only when the partner is restored to
    # `APPROVED`."  A profile for a partner who is not APPROVED therefore never
    # reports itself ACTIVE merely because it happens to have headroom.
    partner = DB.partner(profile.get("partner_id"))
    if partner is not None and partner.get("status") != "APPROVED":
        profile["status"] = "LOCKED"
        return profile
    headroom = (profile.get("max_allocatable_units") or 0) - profile["capacity_utilization_units"]
    if headroom == 0:
        profile["status"] = "EXHAUSTED"
    else:
        profile["status"] = "ACTIVE"
    return profile


def selectable_profiles(partner_id, season):
    """Profiles of the partner whose effective window covers the season."""
    if season is None:
        return []
    start = parse_iso(season["starts_at"])
    end = parse_iso(season["ends_at"])
    rows = []
    for profile in DB.capacity_profiles.values():
        if profile.get("partner_id") != partner_id:
            continue
        if profile.get("season_code") != season.get("season_code"):
            continue
        if profile.get("status") in ("SUPERSEDED",):
            continue
        if not profile.get("effective_from") or not profile.get("effective_to"):
            continue
        eff_from = parse_iso(profile["effective_from"])
        eff_to = parse_iso(profile["effective_to"])
        if eff_from <= end and start <= eff_to:
            rows.append(profile)
    return rows


def resolve_profile(partner_id, season):
    """Exactly one selectable profile must resolve (validations[priority=11])."""
    rows = selectable_profiles(partner_id, season)
    live = [p for p in rows if p.get("status") in ("ACTIVE", "EXHAUSTED")]
    if len(live) > 1:
        raise ApiError("ERR_CAPACITY_PROFILE_AMBIGUOUS")
    if live:
        return live[0]
    locked = [p for p in rows if p.get("status") == "LOCKED"]
    if locked and len(locked) == 1:
        raise ApiError("ERR_PARTNER_CAPACITY_LOCKED")
    if locked and len(locked) > 1:
        raise ApiError("ERR_CAPACITY_PROFILE_AMBIGUOUS")
    if len(rows) > 1:
        raise ApiError("ERR_CAPACITY_PROFILE_AMBIGUOUS")
    if rows:
        raise ApiError("ERR_PARTNER_CAPACITY_LOCKED")
    return None


def emergency_profile(partner_id, season):
    """The profile an EMERGENCY commitment may still draw on (PRD §2.5).

    PRD §3.2 moves a profile whose owning partner left APPROVED to `LOCKED`
    while leaving its committed figure intact, so the row is still the partner's
    capacity picture even though it is no longer selectable for an ordinary
    benefit allocation.
    """
    try:
        return resolve_profile(partner_id, season)
    except ApiError as error:
        if error.error_id not in ("ERR_PARTNER_CAPACITY_LOCKED",
                                  "ERR_CAPACITY_PROFILE_AMBIGUOUS"):
            raise
        rows = [p for p in DB.capacity_profiles.values()
                if p.get("partner_id") == partner_id
                and p.get("season_code") == (season or {}).get("season_code")
                and p.get("status") != "SUPERSEDED"]
        live = [p for p in rows if p.get("status") in ("ACTIVE", "EXHAUSTED", "LOCKED")]
        return live[0] if len(live) == 1 else None


def headroom_of(profile):
    recompute_profile(profile)
    return (profile.get("max_allocatable_units") or 0) - profile["capacity_utilization_units"]


# ===========================================================================
# Liabilities (DonationLiability)
# ===========================================================================

def ensure_liability(product_id, season):
    """Find or lazily materialise the (product, season) liability bucket."""
    existing = calc.find_liability(DB, product_id, season["id"])
    if existing:
        return existing
    now = iso3(DB.now())
    record = {
        "id": _uuid(),
        "donation_product_id": product_id,
        "impact_season_id": season["id"],
        "donation_liability_units": 0,
        "final_liability_units": 0,
        "provisional_liability_units": 0,
        "obligation_units": 0,
        "accrued_obligation_cents": 0,
        "donation_cost_cents": 0,
        "donation_credit_units": 0,
        "frozen_units": 0,
        "required_stated_units": 0,
        "carried_in_units": 0,
        "carried_out_units": 0,
        "carry_from_season_code": None,
        "status": "ACCUMULATING",
        "freeze_recorded_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    DB.donation_liabilities[record["id"]] = record
    return record


def _uuid():
    from db import new_id
    return new_id()


def recompute_liability(liability):
    season = DB.season(liability["impact_season_id"])
    product_id = liability["donation_product_id"]
    season_id = liability["impact_season_id"]

    ledger = calc.donation_credit_ledger(DB, product_id, season_id)
    liability["donation_cost_cents"] = ledger["donation_cost_cents"]
    liability["donation_credit_units"] = ledger["donation_credit_units"]
    if liability.get("status") == "AUDIT_LOCKED" or liability.get("status") == "CLOSED":
        # frozen_units is not re-snapshotted outside the audit-lock paths
        pass
    else:
        liability["provisional_liability_units"] = calc.provisional_liability_units(
            DB, product_id, season_id
        )
    liability["final_liability_units"] = calc.final_liability_units(DB, product_id, season_id)

    if liability.get("status") in ("ACCUMULATING", "CARRIED"):
        liability["donation_liability_units"] = liability["final_liability_units"]

    liability["required_stated_units"] = calc.required_stated_units(DB, product_id, season_id)
    product = DB.product(product_id)
    if product:
        product["obligation_units_total"] = sum(
            (l.get("obligation_units") or 0)
            for l in DB.donation_liabilities.values()
            if l["donation_product_id"] == product_id
        )
    if season:
        recompute_season(season)
    return liability


def recompute_product_liabilities(product_id, season_id=None):
    for liability in DB.donation_liabilities.values():
        if liability["donation_product_id"] != product_id:
            continue
        if season_id and liability["impact_season_id"] != season_id:
            continue
        recompute_liability(liability)


# ===========================================================================
# Allocations and distributions
# ===========================================================================

def recompute_allocation(allocation):
    season = DB.season(allocation["impact_season_id"])
    distributions = [d for d in DB.donation_distributions.values()
                     if d.get("allocation_id") == allocation["id"]]
    shipped = sum(d.get("shipped_units") or 0 for d in distributions
                  if d.get("status") != "VOIDED")
    allocation["shipped_units_total"] = shipped
    partner = DB.partner(allocation["giving_partner_id"])
    if partner:
        recompute_partner_impact(partner)
    if season:
        recompute_season(season)
    return allocation


def recompute_distribution(distribution):
    allocation = DB.allocation(distribution["allocation_id"])
    partner = DB.partner(allocation["giving_partner_id"]) if allocation else None
    if partner:
        recompute_partner_completion_days(partner)
        recompute_partner_impact(partner)
    season = DB.season(distribution["impact_season_id"])
    if season:
        recompute_season(season)
    return distribution


# ===========================================================================
# Claims
# ===========================================================================

def recompute_claim(claim):
    result = calc.claim_substantiation(DB, claim)
    claim["substantiated_donation_units"] = result["substantiated_donation_units"]
    claim["substantiated_ratio_value"] = result["substantiated_ratio_value"]
    liability = calc.find_liability(DB, claim.get("donation_product_id"), claim.get("impact_season_id"))
    if liability:
        recompute_liability(liability)
    return claim


# ===========================================================================
# Orders and lines
# ===========================================================================

def recompute_order(order):
    lines = DB.order_lines(order["id"])
    order["ordered_units"] = sum(l.get("quantity") or 0 for l in lines)

    returned = 0
    refunded = 0
    for line in lines:
        for request in DB.line_return_requests(line["id"]):
            if request.get("status") == "CREDITED":
                returned += request.get("requested_units") or 0
                refunded += request.get("refund_amount_cents") or 0
    order["returned_units"] = returned
    order["refunded_cents"] = refunded

    fulfilled = 0
    for line in lines:
        if line.get("status") == "EXEMPTED":
            fulfilled += line.get("quantity") or 0
        elif order.get("fulfillment_status") == "DELIVERED":
            fulfilled += line.get("quantity") or 0
    order["fulfilled_units"] = fulfilled

    # The parallel donation dimension advances on its own (PRD 3.5).
    #
    # Precedence follows PRD 3.6: a credit drags the order into the refund
    # ladder first (PAID/DONATION_SATISFIED -> PARTIALLY_REFUNDED, and then
    # PARTIALLY_REFUNDED -> REFUNDED once every line is credited and the
    # returned units match the ordered units); only an order whose lines are
    # terminally donated without a credit reaches DONATION_SATISFIED.
    if order.get("status") in ("PAID", "DONATION_SATISFIED", "PARTIALLY_REFUNDED") and lines:
        credited = [l for l in lines if l.get("status") == "RETURNED_CREDITED"]
        exchanged = [l for l in lines if l.get("status") == "EXCHANGED_REPLACED"]
        if credited or exchanged:
            # PRD §3.6: an order at `PAID`/`DONATION_SATISFIED` whose requested
            # units are fewer than its ordered units moves to `PARTIALLY_REFUNDED`,
            # and an order at `PARTIALLY_REFUNDED` whose every line has reached
            # `RETURNED_CREDITED` with returned units equal to ordered units moves
            # to `REFUNDED`. The ledger never drops below `PARTIALLY_REFUNDED` on
            # the strength of the requested units alone.
            if order["status"] != "PARTIALLY_REFUNDED":
                order["status"] = "PARTIALLY_REFUNDED"
            if (credited and order["status"] == "PARTIALLY_REFUNDED"
                    and len(credited) == len(lines)
                    and all(l.get("status") == "RETURNED_CREDITED" for l in lines)
                    and returned >= order["ordered_units"]):
                order["status"] = "REFUNDED"
        elif all(l.get("status") in ("EXEMPTED", "RETURNED_CREDITED",
                                     "EXCHANGED_REPLACED") for l in lines):
            order["status"] = "DONATION_SATISFIED"
    return order


def order_touched(product_id, season_id):
    """Recompute the liabilities and order roll-ups a line change touches."""
    recompute_product_liabilities(product_id, season_id)
    season = DB.season(season_id)
    if season:
        recompute_season(season)


# ===========================================================================
# Line obligation materialisation
# ===========================================================================

def materialize_line_obligations(line):
    variant = DB.product_line(line["donation_product_line_id"])
    if not variant or not variant.get("donation_eligible"):
        line["obligated_units"] = 0
        return line
    order = DB.order(line["sales_order_id"])
    product = DB.product(variant["donation_product_id"])
    if not product:
        line["obligated_units"] = 0
        return line
    if product.get("obligation_model") == "AT_SALE" and order.get("status") not in (
            "CREATED", "PAID", "DONATION_SATISFIED", "PARTIALLY_REFUNDED", "REFUNDED"):
        line["obligated_units"] = 0
        return line
    if product.get("obligation_model") == "AT_SALE" and order.get("status") == "CREATED":
        # PRD §3.5: a line's obligation "accrues ... immediately and
        # unconditionally" the moment it is added, at its quantity multiplied by
        # its variant's obligation units.  Payment re-materialises the same
        # figure, so a CREATED order's line must already carry it.
        line["obligated_units"] = (line.get("quantity") or 0) * (variant.get("obligation_units") or 0)
        return line
    line["obligated_units"] = (line.get("quantity") or 0) * (variant.get("obligation_units") or 0)
    return line


# ===========================================================================
# Product aggregates
# ===========================================================================

def recompute_product(product):
    product["design_weight_score"] = calc.product_attribute_weight(
        product.get("product_kind"), product.get("is_reusable"), product.get("design_channel")
    )
    # PRD §3.4: "`obligation_units_total` sums the obligation units across all of
    # the product's liability rows." The liability's writable figure is its
    # provisional count (falling back to the frozen snapshot once frozen).
    product["obligation_units_total"] = sum(
        (l.get("provisional_liability_units") if l.get("provisional_liability_units")
         is not None else (l.get("frozen_units") or 0)) or 0
        for l in DB.donation_liabilities.values()
        if l["donation_product_id"] == product["id"]
    )
    frozen = DB.frozen_season()
    product["active_season_code"] = frozen.get("season_code") if frozen else None

    retail_equivalent = 0
    for line in DB.sales_order_lines.values():
        variant = DB.product_line(line.get("donation_product_line_id"))
        if variant and variant.get("donation_product_id") == product["id"]:
            retail_equivalent += line.get("quantity") or 0
    product["impact_units_retail_equivalent"] = retail_equivalent
    return product


def recompute_product_line(variant):
    product = DB.product(variant["donation_product_id"])
    if not product:
        return variant
    variant["obligation_units"] = calc.obligation_units(product, bool(variant.get("donation_eligible")))
    variant["unit_obligation_cost_cents"] = calc.donation_unit_cost(product)
    variant["design_variant_code"] = calc.design_variant_code(
        bool(variant.get("donation_eligible")), product.get("design_channel")
    )
    return variant


# ===========================================================================
# Full reconciliation pass (used by the clock roll and by reads)
# ===========================================================================

def reconcile_all():
    for variant in DB.donation_product_lines.values():
        recompute_product_line(variant)
    for product in DB.donation_products.values():
        recompute_product(product)
    for order in DB.sales_orders.values():
        recompute_order(order)
    for liability in DB.donation_liabilities.values():
        recompute_liability(liability)
    for profile in DB.capacity_profiles.values():
        recompute_profile(profile)
    for partner in DB.giving_partners.values():
        recompute_partner(partner)
    for allocation in DB.donation_allocations.values():
        recompute_allocation(allocation)
    for season in DB.impact_seasons.values():
        recompute_season(season)