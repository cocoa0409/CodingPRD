"""The seven pinned calculations (PRD section 2.9 and section 3).

Every monetary result is an integer number of cents produced with Decimal
arithmetic and half-up rounding.  The single non-half-up operator in the whole
system is the ceiling in the inventory-retention obligation.
"""

from decimal import Decimal, ROUND_CEILING

import db
from errors import ApiError
from services import lookups

MICROS_PER_CENT = Decimal(10000)

RECOUPABILITY_BY_CATEGORY = {
    "DIGITAL_ADS": "FULLY_RECOUPABLE",
    "RADIO_PROMO": "FULLY_RECOUPABLE",
    "VIDEO_PRODUCTION": "HALF_RECOUPABLE",
    "TOUR_SUPPORT": "HALF_RECOUPABLE",
    "PUBLICITY": "NON_RECOUPABLE",
}

RECOUPABILITY_FACTOR = {
    "FULLY_RECOUPABLE": Decimal("1.0000"),
    "HALF_RECOUPABLE": Decimal("0.5000"),
    "NON_RECOUPABLE": Decimal("0.0000"),
}

MARKETING_CAP_PCT = Decimal("0.3000")
MATERIALITY_PCT = Decimal("0.05")
INVENTORY_RETENTION_PCT = Decimal("0.0500")
RESERVE_TIER_HIGH = Decimal("0.2500")
RESERVE_TIER_LOW = Decimal("0.1000")
RESERVE_BUMP_HIGH = Decimal("0.1500")
RESERVE_BUMP_LOW = Decimal("0.0500")
RESERVE_CEILING = Decimal("0.5000")

ATTRIBUTABLE_RELEASE_STATUSES = ("PLANNED", "RELEASED", "REVERSION_PENDING")
PHYSICAL_ACCOUNTABLE_RUN_STATUSES = ("SHIPPED", "RECONCILED")


# ---------------------------------------------------------------------
# 1. dsp_line_revenue
# ---------------------------------------------------------------------

def resolve_rate_card(dsp_code, territory_code, tier, period_end):
    """Half-open effective window, newest effective_from wins, creation order
    breaks ties."""
    candidates = []
    for card in db.store.rate_cards.values():
        if card["dsp_code"] != dsp_code:
            continue
        if card["territory_code"] != territory_code:
            continue
        if card["tier"] != tier:
            continue
        effective_from = db.parse_date(card["effective_from"])
        if effective_from > period_end:
            continue
        effective_to = db.parse_date(card["effective_to"]) if card["effective_to"] else None
        if effective_to is not None and not (effective_to > period_end):
            continue
        candidates.append(card)
    if not candidates:
        return None
    candidates.sort(
        key=lambda c: (-db.parse_date(c["effective_from"]).toordinal(), c["_seq"])
    )
    return candidates[0]


def price_report_lines(report, lines):
    """Price every line or reject the whole submission."""
    period_end = db.parse_date(report["period_end"])
    priced = []
    for line in lines:
        card = resolve_rate_card(
            report["dsp_code"], line["territory_code"], line["tier"], period_end
        )
        if card is None:
            raise ApiError("ERR_RATE_CARD_NOT_FOUND")
        rate = card["rate_micros_per_stream"]
        revenue = db.round_half_up(
            Decimal(line["stream_count"]) * Decimal(rate) / MICROS_PER_CENT
        )
        priced.append({"line": line, "rate": rate, "revenue": revenue})
    gross = sum(item["revenue"] for item in priced)
    return priced, gross


# ---------------------------------------------------------------------
# 2. deal_net_receipts
# ---------------------------------------------------------------------

def _recoverable_costs(deal, report):
    period_start = db.parse_date(report["period_start"])
    period_end = db.parse_date(report["period_end"])
    cutoff = db.parse_instant(period_start.isoformat() + "T00:00:00.000Z")
    total = 0
    for spend in lookups.spends_of_deal(deal["id"]):
        if spend["status"] != "SETTLED":
            continue
        if not spend.get("approved_at"):
            continue
        approved_at = db.parse_instant(spend["approved_at"])
        if approved_at < cutoff:
            total += spend.get("settled_amount_cents") or 0
    for run in lookups.runs_of_deal(deal["id"]):
        if run["status"] not in PHYSICAL_ACCOUNTABLE_RUN_STATUSES:
            continue
        window_end = db.parse_date(run["window_end"])
        if window_end <= period_end:
            total += run.get("manufacturing_cost_cents") or 0
    return total


def _service_months(report):
    start = db.parse_date(report["period_start"])
    end = db.parse_date(report["period_end"])
    return (end.year - start.year) * 12 + (end.month - start.month) + 1


def deal_net_receipts(deal, report, gross):
    deal_type = deal["deal_type"]
    if deal_type == "DISTRIBUTION_FEE":
        raw = db.round_half_up(Decimal(gross) * deal["distribution_fee_pct"])
    elif deal_type == "PROFIT_SHARE":
        recoverable = _recoverable_costs(deal, report)
        profit_base = max(0, gross - recoverable)
        label_share = db.round_half_up(
            Decimal(profit_base) * deal["profit_share_label_pct"]
        )
        raw = gross - label_share
    else:
        months = _service_months(report)
        raw = db.round_half_up(Decimal(gross) * deal["services_fee_pct"]) \
            + (deal["services_monthly_fee_cents"] or 0) * months
    distributor_share = min(gross, max(0, raw))
    net_receipts = gross - distributor_share
    return distributor_share, net_receipts


def allocate_distributor_share(distributor_share, priced):
    """Largest-remainder split of the distributor's share across lines."""
    weights = [item["revenue"] for item in priced]
    tiebreaks = [item["line"]["_seq"] for item in priced]
    return db.largest_remainder(distributor_share, weights, tiebreaks)


# ---------------------------------------------------------------------
# 3. advance_recoupment_waterfall
# ---------------------------------------------------------------------

def advance_waterfall(deal, pool, release_pools):
    """Return (applied_total, {release_id: applied_cents})."""
    eligible = [
        r for r in lookups.releases_of_deal(deal["id"])
        if r["status"] in ATTRIBUTABLE_RELEASE_STATUSES
    ]
    applied = {}
    if deal["cross_collateralized"]:
        applied_total = min(pool, deal.get("unrecouped_advance_cents") or 0)
        weights = [release_pools.get(r["id"], 0) for r in eligible]
        tiebreaks = [r["_seq"] for r in eligible]
        split = db.largest_remainder(applied_total, weights, tiebreaks)
        for index, release in enumerate(eligible):
            applied[release["id"]] = split[index]
    else:
        applied_total = 0
        for release in eligible:
            release_unrecouped = max(
                0,
                (release.get("advance_share_cents") or 0)
                - (release.get("release_advance_recouped_cents") or 0),
            )
            amount = min(release_pools.get(release["id"], 0), release_unrecouped)
            applied[release["id"]] = amount
            applied_total += amount
    return applied_total, applied


# ---------------------------------------------------------------------
# 4. artist_royalty_rate_selection
# ---------------------------------------------------------------------

def select_royalty_rate(agreement, deal):
    if deal is not None and deal.get("recoupment_status") == "RECOUPED":
        return agreement["escalated_royalty_rate_pct"]
    return agreement["royalty_rate_pct"]


def reselect_rates_for_deal(deal, bump_versions=True):
    """Re-run the selection for every accountable agreement on the deal."""
    touched = []
    for agreement in lookups.agreements_of_deal(deal["id"]):
        if agreement["status"] not in ("ACTIVE", "AMENDMENT_PENDING", "POST_TERM"):
            continue
        agreement["active_royalty_rate_pct"] = select_royalty_rate(agreement, deal)
        if bump_versions:
            db.touch(agreement)
        touched.append(agreement)
    return touched


# ---------------------------------------------------------------------
# 5. returns_reserve_obligation
# ---------------------------------------------------------------------

def recompute_reserve(run):
    distributor = db.store.distributors.get(run["distributor_id"])
    base_pct = run.get("returns_reserve_pct")
    if base_pct is None:
        base_pct = distributor["default_returns_reserve_pct"] if distributor \
            else Decimal("0.0000")
    shipped = run.get("units_shipped") or 0
    returned = run.get("units_returned") or 0
    if shipped == 0:
        returns_rate = Decimal("0.0000")
    else:
        returns_rate = db.round_pct_4(Decimal(returned) / Decimal(shipped))
    if returns_rate >= RESERVE_TIER_HIGH:
        effective = base_pct + RESERVE_BUMP_HIGH
    elif returns_rate >= RESERVE_TIER_LOW:
        effective = base_pct + RESERVE_BUMP_LOW
    else:
        effective = base_pct
    if effective > RESERVE_CEILING:
        effective = RESERVE_CEILING
    effective = db.round_pct_4(effective)
    price = run.get("wholesale_unit_price_cents") or 0
    initial = db.round_half_up(Decimal(shipped) * Decimal(price) * effective)
    held_before = run.get("reserve_held_cents") or 0
    liquidated = run.get("reserve_liquidated_cents") or 0
    delta = initial - (held_before + liquidated)
    run["returns_rate"] = returns_rate
    run["effective_reserve_pct"] = effective
    run["reserve_initial_cents"] = initial
    run["reserve_held_cents"] = max(0, held_before + delta)
    manufacturing = run.get("manufacturing_cost_cents") or 0
    run["physical_net_receipts_cents"] = max(
        0, (shipped - returned) * price - manufacturing
    )
    return run


def minimum_retained_inventory(units_shipped):
    return int(
        (Decimal(units_shipped) * INVENTORY_RETENTION_PCT).to_integral_value(
            rounding=ROUND_CEILING
        )
    )


# ---------------------------------------------------------------------
# 6. recoupable_marketing_cap
# ---------------------------------------------------------------------

def marketing_recoupable(release, basis_variant, period_net_receipts,
                         marketing_recoup_share_pct):
    cap = db.round_half_up(Decimal(period_net_receipts) * MARKETING_CAP_PCT)
    raw = 0
    for spend in lookups.spends_of_release(release["id"]):
        if basis_variant == "PROVISIONAL":
            if spend["status"] not in ("APPROVED", "SETTLED"):
                continue
            basis = spend.get("amount_cents") or 0
        else:
            if spend["status"] != "SETTLED":
                continue
            basis = spend.get("settled_amount_cents") or 0
        factor = RECOUPABILITY_FACTOR[spend["recoupability"]]
        raw += db.round_half_up(Decimal(basis) * factor)
    recoupable = min(raw, cap)
    already = release.get("recoupable_marketing_applied_cents") or 0
    artist_share = max(
        0,
        db.round_half_up(Decimal(recoupable) * marketing_recoup_share_pct) - already,
    )
    return {
        "marketing_cap_cents": cap,
        "raw_marketing_cents": raw,
        "recoupable_marketing_cents": recoupable,
        "artist_marketing_share_cents": artist_share,
    }


# ---------------------------------------------------------------------
# 7. artist_statement_net_payable
# ---------------------------------------------------------------------

def statement_figures(statement, agreement, release, deal):
    period_start = db.parse_date(statement["period_start"])
    period_end = db.parse_date(statement["period_end"])
    rate = agreement["active_royalty_rate_pct"]

    digital = 0
    for line in lookups.lines_of_release(release["id"]):
        report = db.store.reports.get(line["report_id"])
        if report is None or report["status"] != "ACCEPTED":
            continue
        report_start = db.parse_date(report["period_start"])
        report_end = db.parse_date(report["period_end"])
        if report_start >= period_start and report_end <= period_end:
            digital += line.get("net_receipts_cents") or 0

    physical = 0
    reserve_basis = 0
    for run in lookups.runs_of_release(release["id"]):
        if run["status"] not in PHYSICAL_ACCOUNTABLE_RUN_STATUSES:
            continue
        window_end = db.parse_date(run["window_end"])
        if period_start <= window_end <= period_end:
            physical += run.get("physical_net_receipts_cents") or 0
        if statement["basis_variant"] == "PROVISIONAL":
            reserve_basis += run.get("reserve_initial_cents") or 0
        else:
            reserve_basis += run.get("reserve_held_cents") or 0

    period_net = digital + physical
    gross = db.round_half_up(Decimal(period_net) * rate)

    marketing = marketing_recoupable(
        release, statement["basis_variant"], period_net,
        agreement["marketing_recoup_share_pct"],
    )

    remaining = gross
    advance_applied = min(remaining, agreement.get("unrecouped_artist_advance_cents") or 0)
    remaining -= advance_applied
    recording_applied = min(remaining, agreement.get("unrecouped_recording_cents") or 0)
    remaining -= recording_applied
    marketing_applied = min(remaining, marketing["artist_marketing_share_cents"])
    remaining -= marketing_applied

    reserve_withheld = db.round_half_up(Decimal(reserve_basis) * rate)
    net_payable = max(0, remaining - reserve_withheld)

    return {
        "applied_royalty_rate_pct": rate,
        "digital_royalty_base_cents": digital,
        "physical_royalty_base_cents": physical,
        "gross_royalty_cents": gross,
        # PRD 3.8: "The cap, marketing_cap_cents, is thirty percent of that
        # figure, rounded half up."
        "marketing_cap_cents": marketing["marketing_cap_cents"],
        "advance_applied_cents": advance_applied,
        "recording_applied_cents": recording_applied,
        "marketing_applied_cents": marketing_applied,
        "reserve_withheld_cents": reserve_withheld,
        "net_payable_cents": net_payable,
    }


def materiality_threshold(net_payable_cents):
    return db.round_half_up(Decimal(net_payable_cents or 0) * MATERIALITY_PCT)
