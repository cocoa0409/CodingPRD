"""Every derived quantity in the system, and the constants they read."""
import datetime
from decimal import Decimal

import store
import util
from errors import ApiError

# ------------------------------------------------------------- constants ----

LISTING_RANK = {"CANDIDATE": 0, "PROPOSED": 1, "THREATENED": 2, "ENDANGERED": 3}
LISTING_STATUSES = ("ENDANGERED", "THREATENED", "PROPOSED", "CANDIDATE")
TAKE_UNITS = ("INDIVIDUALS", "ACRES", "NESTS")
DESIGNATION_STATUSES = ("PROPOSED", "FINAL")
ACTION_TYPES = ("FEDERAL_FUNDED", "FEDERAL_PERMITTED", "NON_FEDERAL")
METHODS = ("DATABASE_QUERY", "FIELD_SURVEY")
DETECTION_RESULTS = ("DETECTED", "NOT_DETECTED", "INCONCLUSIVE")
MECHANISMS = ("CONSERVATION_BANK_CREDIT", "IN_LIEU_FEE", "PERMITTEE_RESPONSIBLE")
INSTRUMENT_TYPES = (
    "IRREVOCABLE_LETTER_OF_CREDIT",
    "ESCROW_ACCOUNT",
    "ENDOWMENT_TRANSFER",
    "PERFORMANCE_BOND",
)
CIRCUMSTANCE_TYPES = ("CHANGED", "UNFORESEEN")
PLAN_DECISIONS = ("APPROVE", "RETURN_FOR_REVISION")
REPORT_DECISIONS = ("ACCEPT", "REJECT")

CANDIDATE_STATUSES = ("PRESENT", "PRESUMED_PRESENT")

NO_EFFECT_OVERLAP_PCT_MAX = Decimal("0.00")
NLAA_OVERLAP_PCT_MAX = Decimal("5.00")

MITIGATION_RATIO = {
    "ENDANGERED": Decimal("3.0"),
    "THREATENED": Decimal("2.0"),
    "PROPOSED": Decimal("1.5"),
    "CANDIDATE": Decimal("1.0"),
}
CRITICAL_HABITAT_UPLIFT = Decimal("1.5")
NO_UPLIFT = Decimal("1.0")

IN_LIEU_BASE_RATE_CENTS_PER_UNIT = Decimal(182500)
PERMITTEE_RESPONSIBLE_COST_CENTS_PER_UNIT = Decimal(210000)
ILF_ADMIN_TIER_1_MAX = 5000000
ILF_ADMIN_TIER_2_MAX = 20000000
ILF_ADMIN_TIER_1_PCT = Decimal("0.150")
ILF_ADMIN_TIER_2_PCT = Decimal("0.115")
ILF_ADMIN_TIER_3_PCT = Decimal("0.080")
NO_ADMIN_FEE_PCT = Decimal("0.000")

ANNUAL_MGMT_COST_PER_UNIT_CENTS = Decimal(4175)
CAPITALIZATION_YEARS = Decimal(30)
MECHANISM_FACTOR = {
    "CONSERVATION_BANK_CREDIT": Decimal("0.60"),
    "IN_LIEU_FEE": Decimal("0.85"),
    "PERMITTEE_RESPONSIBLE": Decimal("1.00"),
}
CHANGED_CIRCUMSTANCE_RESERVE_PCT = Decimal("0.12")

JEOPARDY_FRACTION_THRESHOLD = Decimal("0.0500")
REINITIATION_TRIGGER_PCT = Decimal("0.90")

FORMAL_CONSULTATION_DAYS = 135
INFORMAL_CONSULTATION_DAYS = 60
MAX_INFO_REQUESTS = 2

REPORT_DUE_DAYS = 45
SURVEY_DISTURBANCE_BUFFER_DAYS = 3
UNFORESEEN_PERMITTEE_SHARE_PCT = Decimal("0.05")

BASE_SCORE = Decimal(100)
W_LATE_REPORT = Decimal(6)
W_REJECTED_REPORT = Decimal(11)
W_OPEN_REINITIATION = Decimal(18)
W_UNRESPONDED_CIRCUMSTANCE = Decimal(9)
DECAY_HALVING_DAYS = 180
DECAY_FACTOR = Decimal("0.5")
ROLLING_WINDOW_DAYS = 365
SCORE_FLOOR = Decimal(0)

PERMIT_NUMBER_PREFIX = "ITP-"
PERMIT_NUMBER_WIDTH = 6


# --------------------------------------------------------- candidate sets ---


def candidates(action):
    """The action's candidate presence determinations: PRESENT or
    PRESUMED_PRESENT, in created_at ascending order."""
    rows = [
        row
        for row in store.values("determinations")
        if row["project_action_id"] == action["id"]
        and row["presence_status"] in CANDIDATE_STATUSES
    ]
    return store.ordered(rows)


def species_of(row):
    return store.get("species", row["species_id"])


# ------------------------------------------------------ presence status -----


def month_in_season(month, start_month, end_month):
    if month is None:
        return False
    if start_month <= end_month:
        return start_month <= month <= end_month
    # A season that wraps the year boundary (e.g. November through February).
    return month >= start_month or month <= end_month


def survey_in_season(method, window_start, window_end, species):
    if method != "FIELD_SURVEY":
        return False
    if window_start is None or window_end is None:
        return False
    start_ok = month_in_season(
        window_start.month,
        species["survey_season_start_month"],
        species["survey_season_end_month"],
    )
    end_ok = month_in_season(
        window_end.month,
        species["survey_season_start_month"],
        species["survey_season_end_month"],
    )
    return bool(start_ok and end_ok)


def presence_status(method, detection_result, in_season):
    if method == "DATABASE_QUERY":
        if detection_result == "NOT_DETECTED":
            return "PRESUMED_ABSENT"
        # DETECTED and INCONCLUSIVE alike are only ever presumptive.
        return "PRESUMED_PRESENT"
    if detection_result == "DETECTED":
        return "PRESENT"
    if detection_result == "INCONCLUSIVE":
        return "PRESUMED_PRESENT"
    # A negative field survey only clears the species when it was detectable.
    return "ABSENT" if in_season else "PRESUMED_PRESENT"


# --------------------------------------------------- effect determination ---


def effect_determination(action):
    rows = candidates(action)
    if not rows:
        return "NO_EFFECT", util.q2(0), util.q2(0)

    total = util.ZERO
    for row in rows:
        total = total + util.to_dec(row["habitat_overlap_acres"])
    total_overlap_acres = util.q2(total)
    overlap_pct = util.q2(
        total_overlap_acres * Decimal(100) / util.to_dec(action["footprint_acres"])
    )

    max_rank = max(LISTING_RANK[species_of(row)["listing_status"]] for row in rows)
    confirmed = any(row["presence_status"] == "PRESENT" for row in rows)

    if max_rank <= 1 and overlap_pct <= NO_EFFECT_OVERLAP_PCT_MAX:
        outcome = "NO_EFFECT"
    elif max_rank <= 1:
        outcome = "NLAA"
    elif overlap_pct <= NLAA_OVERLAP_PCT_MAX and not confirmed:
        outcome = "NLAA"
    elif overlap_pct <= NLAA_OVERLAP_PCT_MAX and confirmed and max_rank == 2:
        outcome = "NLAA"
    else:
        outcome = "LAA"
    return outcome, total_overlap_acres, overlap_pct


# --------------------------------------- incidental take authorization ------


def primary_species(action):
    """Highest listing rank, then smallest recovery_unit_population, then
    earliest species created_at.  Fully pinned (PRD 3.5)."""
    rows = candidates(action)
    if not rows:
        return None
    pool = {}
    for row in rows:
        species = species_of(row)
        pool[species["id"]] = species
    ranked = sorted(
        pool.values(),
        key=lambda s: (
            -LISTING_RANK[s["listing_status"]],
            s["recovery_unit_population"],
            s["created_at"],
            s["_seq"],
        ),
    )
    return ranked[0]


def incidental_take(action):
    """Returns the take statement figures, or None when there is no candidate
    set to compute them from."""
    species = primary_species(action)
    if species is None:
        return None
    rows = [r for r in candidates(action) if r["species_id"] == species["id"]]
    exposed = util.ZERO
    for row in rows:
        exposed = exposed + util.to_dec(row["habitat_overlap_acres"])
    exposed_acres = util.q2(exposed)

    take_unit = species["take_authorization_unit"]
    if take_unit == "ACRES":
        raw_take = exposed_acres
    else:
        raw_take = exposed_acres * util.to_dec(species["take_density_per_acre"])
    authorized = util.q2(raw_take)

    fraction = util.q4(authorized / Decimal(species["recovery_unit_population"]))
    trigger = util.q2(authorized * REINITIATION_TRIGGER_PCT)
    return {
        "species": species,
        "exposed_acres": exposed_acres,
        "take_unit": take_unit,
        "authorized_take_units": authorized,
        "jeopardy_fraction": fraction,
        "reinitiation_trigger_units": trigger,
    }


# ------------------------------------------------ mitigation requirement ----


def _listing_ratio(row):
    return MITIGATION_RATIO[species_of(row)["listing_status"]]


def _uplift(row):
    unit = store.get("habitat_units", row.get("critical_habitat_unit_id"))
    if unit is not None and unit["designation_status"] == "FINAL":
        return CRITICAL_HABITAT_UPLIFT
    return NO_UPLIFT


def preliminary_mitigation_units(action, covered_acres):
    """Coarse: the single largest listing ratio in the candidate set applied to
    the plan's whole covered_acres.  Ignores uplift and per-row acreage."""
    rows = candidates(action)
    if not rows:
        raise ApiError("ERR_NO_PRESENCE_DETERMINATIONS")
    largest = max(_listing_ratio(row) for row in rows)
    return util.q2(util.to_dec(covered_acres) * largest)


def final_mitigation_units(action):
    """Row by row: round each product to two places, then sum the rounded
    figures.  The per-row order is normative."""
    rows = candidates(action)
    if not rows:
        raise ApiError("ERR_NO_PRESENCE_DETERMINATIONS")
    total = util.ZERO
    for row in rows:
        product = (
            util.to_dec(row["habitat_overlap_acres"])
            * _listing_ratio(row)
            * _uplift(row)
        )
        total = total + util.q2(product)
    return util.q2(total)


# ------------------------------------------------------ commitment costs ----


def commitment_cost(mechanism, units, bank):
    units = util.to_dec(units)
    if mechanism == "CONSERVATION_BANK_CREDIT":
        base = util.rhu_int(units * Decimal(bank["credit_price_cents"]))
    elif mechanism == "IN_LIEU_FEE":
        base = util.rhu_int(units * IN_LIEU_BASE_RATE_CENTS_PER_UNIT)
    else:
        base = util.rhu_int(units * PERMITTEE_RESPONSIBLE_COST_CENTS_PER_UNIT)

    # The tier table is mechanism-gated, not amount-gated.
    if mechanism == "IN_LIEU_FEE":
        if base < ILF_ADMIN_TIER_1_MAX:
            pct = ILF_ADMIN_TIER_1_PCT
        elif base < ILF_ADMIN_TIER_2_MAX:
            pct = ILF_ADMIN_TIER_2_PCT
        else:
            pct = ILF_ADMIN_TIER_3_PCT
    else:
        pct = NO_ADMIN_FEE_PCT

    admin = util.rhu_int(Decimal(base) * pct)
    return base, util.rhu(pct, 3), admin, base + admin


def endowment_contribution(commitment):
    return util.rhu_int(
        util.to_dec(commitment["units"])
        * ANNUAL_MGMT_COST_PER_UNIT_CENTS
        * CAPITALIZATION_YEARS
        * MECHANISM_FACTOR[commitment["mechanism"]]
    )


def plan_commitments(plan, statuses=None):
    rows = [
        row
        for row in store.values("commitments")
        if row["hcp_id"] == plan["id"]
        and (statuses is None or row["status"] in statuses)
    ]
    return store.ordered(rows)


def recompute_endowment(plan):
    """Round each contribution, then add.  The reserve is a percentage of the
    already-rounded base."""
    contributing = plan_commitments(plan, ("RESERVED", "SECURED"))
    base = 0
    for commitment in contributing:
        cents = endowment_contribution(commitment)
        commitment["endowment_contribution_cents"] = cents
        base = base + cents
    plan["endowment_base_cents"] = base
    reserve = util.rhu_int(Decimal(base) * CHANGED_CIRCUMSTANCE_RESERVE_PCT)
    plan["changed_circumstance_reserve_cents"] = reserve
    plan["endowment_required_cents"] = base + reserve
    refresh_reserve_remaining(plan)


def refresh_reserve_remaining(plan):
    remaining = (
        plan["changed_circumstance_reserve_cents"] - plan["reserve_drawn_cents"]
    )
    plan["reserve_remaining_cents"] = remaining if remaining > 0 else 0


def recompute_secured_units(plan):
    total = util.ZERO
    for commitment in plan_commitments(plan, ("RESERVED", "SECURED")):
        total = total + util.to_dec(commitment["units"])
    plan["secured_mitigation_units"] = util.q2(total)


def recompute_funding(plan):
    """The decision is made on exact integer cents; funded_ratio is reporting
    only (PRD 3.7)."""
    required = plan["endowment_required_cents"]
    secured = plan["endowment_secured_cents"]
    if required == 0:
        plan["funded_ratio"] = util.q4(0)
        plan["funding_status"] = "UNFUNDED"
        return
    plan["funded_ratio"] = util.q4(Decimal(secured) / Decimal(required))
    if secured >= required:
        plan["funding_status"] = "FULLY_ASSURED"
    elif 2 * secured >= required:
        plan["funding_status"] = "PARTIALLY_ASSURED"
    else:
        plan["funding_status"] = "UNFUNDED"


# --------------------------------------------------------------- clocks -----


def consultation_deadline(consultation):
    days = consultation["statutory_days"] + consultation["tolled_days"]
    return consultation["clock_started_at"] + datetime.timedelta(days=days)


def refresh_deadline(consultation):
    consultation["deadline_at"] = consultation_deadline(consultation)


def permit_number():
    ordinal = len(store.values("permits")) + 1
    return PERMIT_NUMBER_PREFIX + str(ordinal).zfill(PERMIT_NUMBER_WIDTH)


# ---------------------------------------------- proponent compliance --------


def proponent_actions(proponent):
    rows = [
        row
        for row in store.values("actions")
        if row["proponent_id"] == proponent["id"]
    ]
    return store.ordered(rows)


def proponent_plans(proponent):
    action_ids = set(row["id"] for row in proponent_actions(proponent))
    rows = [
        row
        for row in store.values("plans")
        if row["project_action_id"] in action_ids
    ]
    return store.ordered(rows)


def proponent_consultations(proponent):
    action_ids = set(row["id"] for row in proponent_actions(proponent))
    rows = [
        row
        for row in store.values("consultations")
        if row["project_action_id"] in action_ids
    ]
    return store.ordered(rows)


def proponent_reports(proponent):
    plan_ids = set(row["id"] for row in proponent_plans(proponent))
    permit_ids = set(
        row["id"] for row in store.values("permits") if row["hcp_id"] in plan_ids
    )
    rows = [
        row for row in store.values("reports") if row["permit_id"] in permit_ids
    ]
    return store.ordered(rows)


def proponent_events(proponent):
    plan_ids = set(row["id"] for row in proponent_plans(proponent))
    rows = [
        row for row in store.values("events") if row["hcp_id"] in plan_ids
    ]
    return store.ordered(rows)


def open_reinitiation_count(proponent):
    return sum(
        1
        for row in proponent_consultations(proponent)
        if row["status"] == "REINITIATION_REQUIRED"
    )


def compliance_standing(proponent):
    """Re-derived against the logical clock on every read of the proponent
    (PRD 3.2).  Returns (score, variant)."""
    now = store.now()
    window_start = now - datetime.timedelta(days=ROLLING_WINDOW_DAYS)

    reports = proponent_reports(proponent)
    variant = "LIFETIME"
    for report in reports:
        period_end = util.at_midnight(report["period_end"])
        if window_start <= period_end <= now:
            variant = "ROLLING_12_MONTH"
            break

    events = []
    for report in reports:
        if report["status"] == "ACCEPTED" and report["is_late"]:
            events.append((W_LATE_REPORT, report["submitted_at"]))
        if report["status"] == "REJECTED":
            events.append((W_REJECTED_REPORT, report["adjudicated_at"]))
    for consultation in proponent_consultations(proponent):
        if consultation["status"] == "REINITIATION_REQUIRED":
            events.append(
                (W_OPEN_REINITIATION, consultation["reinitiation_triggered_at"])
            )
    for event in proponent_events(proponent):
        if event["status"] == "RESPONSE_REQUIRED":
            events.append((W_UNRESPONDED_CIRCUMSTANCE, event["reported_at"]))

    if variant == "ROLLING_12_MONTH":
        events = [
            (weight, when)
            for (weight, when) in events
            if when is not None and window_start <= when <= now
        ]

    # Halved weights stay fractional inside the sum; only the total is rounded.
    penalty = util.ZERO
    for weight, when in events:
        if when is None:
            continue
        age_days = util.whole_days_between(when, now)
        if age_days > DECAY_HALVING_DAYS:
            penalty = penalty + weight * DECAY_FACTOR
        else:
            penalty = penalty + weight
    score = util.q2(BASE_SCORE - penalty)
    if score < SCORE_FLOOR:
        score = util.q2(SCORE_FLOOR)
    return score, variant


def refresh_compliance(proponent):
    """The score and the variant are persisted quietly -- this is not a
    mutation, so version and updated_at are deliberately left alone."""
    if proponent is None:
        return
    score, variant = compliance_standing(proponent)
    proponent["compliance_standing_score"] = score
    proponent["compliance_variant_applied"] = variant
    proponent["open_reinitiation_count"] = open_reinitiation_count(proponent)


def proponent_of_action(action):
    return store.get("proponents", action["proponent_id"])
