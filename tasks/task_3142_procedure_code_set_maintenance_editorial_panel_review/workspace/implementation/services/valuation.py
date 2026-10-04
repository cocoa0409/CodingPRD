"""Valuation arithmetic: RVU-to-dollar conversion, published work RVU and
errata proration.

Sources: PRD.md 2.9, 3.7, 3.8 and SCAFFOLD.yaml `code_value_dollar_split_proration`,
`ruc_global_valuation_to_code_value`, `errata_proration_recalculation`.
"""

from datetime import datetime, timezone

from money import Decimal, as_float, cents, dec, round_half_up
import store

NATIONAL_GPCI = Decimal("1.0000")
DEFAULT_CONVERSION_FACTOR = Decimal("32.99")

MAGNITUDE_LOW_WEIGHT = Decimal("0.35")
MAGNITUDE_BAND1_WEIGHT = Decimal("0.12")
MAGNITUDE_HIGH_WEIGHT = Decimal("0.06")
MAGNITUDE_LOW_CEILING_MINUTES = Decimal("30")
MAGNITUDE_BAND1_CEILING_MINUTES = Decimal("60")


def _gpci(value):
    """The specialty's three GPCIs, or a national 1.0000 across the board when
    the named specialty row does not exist (PRD.md 3.7)."""
    specialty_id = value.get("specialty_id")
    if specialty_id:
        society = store.societies.get(specialty_id)
        if society is not None:
            return (dec(society.get("gpci_work", NATIONAL_GPCI)),
                    dec(society.get("gpci_pe", NATIONAL_GPCI)),
                    dec(society.get("gpci_mp", NATIONAL_GPCI)))
    return (NATIONAL_GPCI, NATIONAL_GPCI, NATIONAL_GPCI)


def conversion_factor_for(value):
    factor = value.get("conversion_factor")
    if factor is None or factor == "":
        return DEFAULT_CONVERSION_FACTOR
    return dec(factor)


def recompute_code_value(value):
    """Recompute every derived payment field on a CodeValue row.

    Aggregate facility total: the adjusted work, facility practice-expense and
    malpractice components are summed, multiplied by the conversion factor and
    by 100, and the whole product is rounded once, half up, to a whole cent.

    Component facility total: each adjusted component is multiplied by the
    conversion factor and by 100 separately, each product rounded half up, and
    the three rounded figures summed.

    Nonfacility total: the sum of adjusted work, nonfacility practice expense
    and malpractice is multiplied by the conversion factor and by 100 and that
    single product is rounded half up.  `dollar_split_shortfall_cents` is the
    nonfacility rounded total minus the sum of the rounded facility components.
    """
    gpci_work, gpci_pe, gpci_mp = _gpci(value)
    factor = conversion_factor_for(value)

    adjusted_work = dec(value.get("work_rvu")) * gpci_work
    adjusted_facility_pe = dec(value.get("facility_pe_rvu")) * gpci_pe
    adjusted_nonfacility_pe = dec(value.get("nonfacility_pe_rvu")) * gpci_pe
    adjusted_mp = dec(value.get("mp_rvu")) * gpci_mp

    aggregate = cents((adjusted_work + adjusted_facility_pe + adjusted_mp) * factor * 100)
    component = (cents(adjusted_work * factor * 100)
                 + cents(adjusted_facility_pe * factor * 100)
                 + cents(adjusted_mp * factor * 100))
    nonfacility = cents(
        (adjusted_work + adjusted_nonfacility_pe + adjusted_mp) * factor * 100
    )

    variant = value.get("rounding_variant") or "AGGREGATE_ROUNDING"
    value["aggregate_round_total_cents"] = aggregate
    value["component_round_total_cents"] = component
    value["facility_payment_cents"] = component if variant == "COMPONENT_ROUNDING" else aggregate
    value["nonfacility_payment_cents"] = nonfacility
    value["dollar_split_shortfall_cents"] = nonfacility - component
    value["release_month"] = _release_month(value)
    return value


def _release_month(value):
    """`release_month` records the calendar month used as the numerator basis
    when a partial-year figure must be prorated (PRD.md 2.9)."""
    effective = value.get("effective_date")
    if effective is None:
        return None
    return effective.month


def magnitude_weight(survey_median_minutes):
    """Tiered magnitude weighting: 0.35 for the low band, 0.12 for the first
    band above it and 0.06 for the high band (PRD.md 3.7)."""
    minutes = dec(survey_median_minutes)
    if minutes <= MAGNITUDE_LOW_CEILING_MINUTES:
        return MAGNITUDE_LOW_WEIGHT
    if minutes <= MAGNITUDE_BAND1_CEILING_MINUTES:
        return MAGNITUDE_BAND1_WEIGHT
    return MAGNITUDE_HIGH_WEIGHT


def recompute_recommended_work_rvu(valuation):
    """RECOMMENDED publishes `work_rvu` unchanged; DEEMED_NOT_RECOMMENDED
    publishes the reference-committee median, i.e. the magnitude weight
    appropriate to `survey_median_minutes` multiplied by 1.0000, rounded half
    up to 2 decimal places."""
    if valuation.get("recommendation_status") == "RECOMMENDED":
        published = dec(valuation.get("work_rvu"))
    else:
        published = magnitude_weight(valuation.get("survey_median_minutes")) * Decimal("1.0000")
    valuation["recommended_work_rvu"] = as_float(round_half_up(published, 2))
    return valuation["recommended_work_rvu"]


def valuation_effective_date(cycle_year):
    """January 1 of the release year following the cycle year."""
    return datetime(int(cycle_year) + 1, 1, 1, tzinfo=timezone.utc)


def _cycle_effective_date(release_id):
    """January 1 of a cycle's own release year, or None without a cycle."""
    cycle = store.release_cycles.get(release_id) if release_id else None
    if cycle is not None and cycle.get("year"):
        return datetime(int(cycle["year"]), 1, 1, tzinfo=timezone.utc)
    return None


def upsert_code_value_for(code, components, release_id=None, change_id=None,
                          specialty_id=None, conversion_factor=None,
                          rounding_variant=None, value_status=None,
                          effective_date=None):
    """Find or create the CodeValue row for a descriptor and stamp components.

    PRD.md 3.7: publishing a recommendation "upserts a CodeValue row for the
    valuation's code", copying the four components, and recomputes its payment
    figures.
    """
    existing = None
    for candidate in store.code_values.values():
        if candidate.get("code") == code and candidate.get("release_id") == release_id:
            existing = candidate
            break
    if existing is None:
        existing = store.create(store.code_values, {
            "code": code,
            "change_id": change_id,
            "release_id": release_id,
            "work_rvu": 0.0,
            "facility_pe_rvu": 0.0,
            "nonfacility_pe_rvu": 0.0,
            "mp_rvu": 0.0,
            "conversion_factor": float(DEFAULT_CONVERSION_FACTOR),
            "specialty_id": specialty_id,
            "rounding_variant": rounding_variant or "AGGREGATE_ROUNDING",
            "facility_payment_cents": 0,
            "nonfacility_payment_cents": 0,
            "component_round_total_cents": 0,
            "aggregate_round_total_cents": 0,
            "dollar_split_shortfall_cents": 0,
            "release_month": None,
            "effective_date": effective_date if effective_date is not None
            else _cycle_effective_date(release_id),
            "value_status": "DRAFT",
            "superseded_by_code_value_id": None,
        })
    else:
        store.bump(existing)
    for name, val in components.items():
        existing[name] = val
    if release_id is not None:
        existing["release_id"] = release_id
    if change_id is not None:
        existing["change_id"] = change_id
    if specialty_id is not None:
        existing["specialty_id"] = specialty_id
    if conversion_factor is not None:
        existing["conversion_factor"] = conversion_factor
    if rounding_variant is not None:
        existing["rounding_variant"] = rounding_variant
    if value_status is not None:
        existing["value_status"] = value_status
    if effective_date is not None:
        existing["effective_date"] = effective_date
    recompute_code_value(existing)
    return existing


def release_year_of(code_value):
    """The release year used by the errata proration denominator.

    A code value bound to a cycle takes that cycle's year.  A value created
    directly carries its own effective date as the basis, which is January 1 of
    the release year.
    """
    cycle = store.release_cycles.get(code_value.get("release_id"))
    if cycle is not None and cycle.get("year"):
        return int(cycle["year"])
    effective = code_value.get("effective_date")
    if effective is not None:
        return effective.year
    return None


def year_end_for(release_year):
    return datetime(int(release_year), 12, 31, tzinfo=timezone.utc)


def errata_proration(notice, code_value=None):
    """Recompute the prorated corrected facility payment and its day counts.

    Denominator: days from the code value's `effective_date` through December 31
    of the release year, inclusive of both endpoints.
    Numerator: days from the notice's `errata_effective_date` through the same
    December 31, inclusive of both endpoints.
    Where the two effective dates are equal no proration occurs at all.
    """
    if code_value is None:
        code_value = store.code_values.get(notice.get("code_value_id"))
    if code_value is None:
        return notice

    release_year = release_year_of(code_value)
    value_effective = code_value.get("effective_date")
    notice_effective = notice.get("errata_effective_date")
    prior = dec(notice.get("prior_facility_payment_cents"))

    if release_year is None or value_effective is None or notice_effective is None:
        notice["corrected_facility_payment_cents"] = int(cents(prior))
        return notice

    year_end = year_end_for(release_year)
    denominator = (year_end - value_effective).days + 1
    numerator = (year_end - notice_effective).days + 1
    notice["proration_denominator_days"] = denominator
    notice["proration_numerator_days"] = numerator

    if notice_effective == value_effective:
        notice["corrected_facility_payment_cents"] = int(cents(prior))
    else:
        if denominator == 0:
            notice["corrected_facility_payment_cents"] = int(cents(prior))
        else:
            notice["corrected_facility_payment_cents"] = int(cents(
                prior * dec(numerator) / dec(denominator)
            ))
    return notice