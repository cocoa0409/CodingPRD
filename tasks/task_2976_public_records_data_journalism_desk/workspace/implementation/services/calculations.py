"""Pinned calculations: fee waiver, cost allocation and disclosure risk."""
from fractions import Fraction

import db
from errors import ApiError
from services.money import exact, round_half_up

# ---- fee waiver constants (PRD section 3.3) -----------------------------
TIER_LOW = Fraction(1, 2)          # 0.50
TIER_MID = Fraction(3, 4)          # 0.75
TIER_HIGH = Fraction(9, 10)        # 0.90
BONUS_HIGH = Fraction(1, 10)       # 0.10
BONUS_MID = Fraction(1, 20)        # 0.05
WAIVER_PCT_CEILING = Fraction(19, 20)  # 0.95
TIER_BOUNDARY_LOW = 5000
TIER_BOUNDARY_HIGH = 20000
DE_MINIMIS_CENTS = 1500

# ---- cost allocation constants (PRD section 3.7) -----------------------
LABOR_RATE_CENTS_PER_HOUR = 6500

# ---- disclosure risk constants (PRD section 3.9) -----------------------
PUBLISH_RISK_CEILING = 60
AGGREGATE_SOURCE_BUMP = 10
COMPOSITE_SOURCE_PENALTY = 25
RISK_SCALE = 10
SIZE_BOUNDARY_SMALL = 1000
SIZE_BOUNDARY_LARGE = 100000
MULTIPLIER_SMALL = Fraction(1)
MULTIPLIER_MEDIUM = Fraction(5, 4)
MULTIPLIER_LARGE = Fraction(3, 2)


def compute_fee_determination(agency, waiver_requested, public_interest_score,
                              search_hours, billed_page_count):
    """The eight pinned steps of PRD section 3.3.  Returns a dict of fee fields."""
    # Step one
    search_fee_cents = round_half_up(exact(search_hours) * agency["search_fee_cents_per_hour"])
    # Step two -- both operands integers, no rounding arises
    duplication_fee_cents = billed_page_count * agency["page_fee_cents"]
    # Step three
    gross_fee_cents = search_fee_cents + duplication_fee_cents

    waiver_pct = None
    if not waiver_requested:
        # Step four: jump straight to step eight
        waiver_amount_cents = 0
    else:
        # Step four: tier from the gross fee, bonus from the public-interest score
        if gross_fee_cents <= TIER_BOUNDARY_LOW:
            tier = TIER_LOW
        elif gross_fee_cents <= TIER_BOUNDARY_HIGH:
            tier = TIER_MID
        else:
            tier = TIER_HIGH
        if public_interest_score >= 80:
            bonus = BONUS_HIGH
        elif public_interest_score >= 60:
            bonus = BONUS_MID
        else:
            bonus = Fraction(0)
        waiver_pct = min(WAIVER_PCT_CEILING, tier + bonus)
        # Step five
        raw_waiver_cents = round_half_up(gross_fee_cents * waiver_pct)
        # Step six
        capped_waiver_cents = min(raw_waiver_cents, agency["max_waiver_cents"])
        # Step seven -- de minimis
        if (gross_fee_cents - capped_waiver_cents) < DE_MINIMIS_CENTS:
            waiver_amount_cents = gross_fee_cents
        else:
            waiver_amount_cents = capped_waiver_cents
    # Step eight
    net_fee_cents = gross_fee_cents - waiver_amount_cents
    return {
        "search_fee_cents": search_fee_cents,
        "duplication_fee_cents": duplication_fee_cents,
        "gross_fee_cents": gross_fee_cents,
        "waiver_pct": None if waiver_pct is None else float(waiver_pct),
        "waiver_amount_cents": waiver_amount_cents,
        "net_fee_cents": net_fee_cents,
    }


def labor_cost_cents(labor_hours):
    """round_half_up(labor_hours * LABOR_RATE_CENTS_PER_HOUR)."""
    return round_half_up(exact(labor_hours) * LABOR_RATE_CENTS_PER_HOUR)


def allocable_datasets(investigation_id):
    """Every dataset on the investigation whose status is CLEAN_LOCKED,
    ordered by created_at ascending then name ascending."""
    rows = [
        d for d in db.all_of("datasets")
        if d.get("investigation_id") == investigation_id and d["status"] == "CLEAN_LOCKED"
    ]
    rows.sort(key=lambda d: (d["created_at"], d["name"]))
    return rows


def compute_cost_allocation(run, investigation_id):
    """Round-then-reconcile allocation of PRD section 3.7."""
    labor_cost = labor_cost_cents(run["labor_hours"])
    total_cost_cents = run["compute_cost_cents"] + labor_cost
    allocable = allocable_datasets(investigation_id)
    if not allocable:
        raise ApiError(
            "ERR_NO_ALLOCABLE_INPUTS",
            "The run's investigation has no CLEAN_LOCKED dataset to allocate against.",
        )
    total_records = sum(d["record_count"] for d in allocable)
    shares = []
    for dataset in allocable:
        if total_records == 0:
            shares.append(0)
        else:
            shares.append(round_half_up(Fraction(total_cost_cents * dataset["record_count"], total_records)))
    residual = total_cost_cents - sum(shares)
    shares[0] = shares[0] + residual
    return {
        "labor_cost_cents": labor_cost,
        "total_cost_cents": total_cost_cents,
        "allocable": allocable,
        "shares": shares,
    }


def unsuppressed_fields(dataset):
    if dataset is None:
        return []
    return [f for f in db.fields_of_dataset(dataset["id"]) if not f["suppression_applied"]]


def size_multiplier(record_count):
    if record_count < SIZE_BOUNDARY_SMALL:
        return MULTIPLIER_SMALL
    if record_count < SIZE_BOUNDARY_LARGE:
        return MULTIPLIER_MEDIUM
    return MULTIPLIER_LARGE


def disclosure_risk_scores(dataset):
    """Returns (aggregate_max_score, composite_weighted_score, any_source)."""
    fields = unsuppressed_fields(dataset)
    any_source = any(f["is_source_identifying"] for f in fields)

    if not fields:
        aggregate_max = 0
    else:
        highest = max(f["reidentification_risk"] for f in fields)
        aggregate_max = min(
            100, highest * RISK_SCALE + (AGGREGATE_SOURCE_BUMP if any_source else 0)
        )

    base = sum(f["reidentification_risk"] for f in fields)
    density = Fraction(base, max(1, len(fields)))
    record_count = dataset["record_count"] if dataset is not None else 0
    scaled = density * RISK_SCALE * size_multiplier(record_count)
    composite = min(
        100, round_half_up(scaled) + (COMPOSITE_SOURCE_PENALTY if any_source else 0)
    )
    return aggregate_max, composite, any_source


VARIANT_BY_MODE = {
    "FULL_DATA_RELEASE": "COMPOSITE_WEIGHTED",
    "AGGREGATES_ONLY": "AGGREGATE_MAX",
    "METHODOLOGY_ONLY": "NONE",
}


def applicable_risk(publication_mode, aggregate_max, composite_weighted):
    variant = VARIANT_BY_MODE[publication_mode]
    if variant == "COMPOSITE_WEIGHTED":
        return variant, composite_weighted
    if variant == "AGGREGATE_MAX":
        return variant, aggregate_max
    return variant, 0
