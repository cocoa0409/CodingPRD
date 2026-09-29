"""Arithmetic corners of the aviation underwriting API.

Every expected figure in this module is re-derived from the PRD's own formulas
through the pure helpers in `test_helpers/constants.py`, so a response is never
compared against itself.  The rounding direction is load-bearing throughout:
divisions discard the fraction unless the PRD names the calculation as one that
rounds up, and the rounding is applied after each division rather than once at
the end.
"""

from test_helpers import (
    AdjustmentStatus,
    CoverageDecision,
    CoverageStatus,
    EndorsementStatus,
    EndorsementType,
    LicenseType,
    PerilsScope,
    PilotBand,
    PolicyType,
    SettlementBasis,
    TerritorialLimit,
    TxnBasis,
    TxnType,
    UseClass,
    assert_ledger_row,
    assert_no_ledger_row_of_type,
    rows_of_type,
    validate_list,
    validate_unpaginated,
)
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users


# ----------------------------------------------------------------------
# The war risk premium: peril tier first, territory factor second
# ----------------------------------------------------------------------
WAR_LINE_CENTS = 400000000
WAR_MARKET_AGGREGATE_CENTS = 3000000000


def _war_placements(api, plan):
    """Open one market and cede an identical line from one policy per plan entry.

    `plan` is a sequence of (territorial_limit_code, perils_scope) pairs.  Each
    entry gets its own freshly created policy, so every placement is the first
    write on its own policy and the expected version is always the initial one.
    """
    fx.advance_clock(api, f.CLOCK_BEFORE_INCEPTION)
    operator = fx.make_operator(api)
    market = fx.make_war_market(
        api, f.war_market_payload(aggregate_line_cents=WAR_MARKET_AGGREGATE_CENTS)
    )
    placements = []
    policies = []
    for territorial_limit_code, perils_scope in plan:
        policy = fx.make_policy(
            api, operator["id"], territorial_limit_code=territorial_limit_code
        )
        policies.append(policy)
        placements.append(
            fx.make_war_placement(
                api,
                policy["id"],
                market["id"],
                policy["version"],
                war_hull_line_cents=WAR_LINE_CENTS,
                perils_scope=perils_scope,
                coverage_from=f.POLICY_EFFECTIVE_FROM,
                coverage_to=f.POLICY_EFFECTIVE_TO,
            )
        )
    return market, policies, placements


def test_war_premium_takes_the_peril_rate_of_the_scope_it_places(api):
    """PRD §3.7: "Multiply `war_hull_line_cents` by the perils rate — 1,500 parts
    per million for `WAR_ONLY`, 2,400 for `WAR_HIJACK` and 3,600 for
    `WAR_HIJACK_TERRORISM` — divide by 1,000,000 and discard the fraction."

    Design: Corner/calculations/corner_war_premium_peril_tiers_then_territory_factor
    """
    plan = [
        (TerritorialLimit.WORLDWIDE, PerilsScope.WAR_ONLY),
        (TerritorialLimit.WORLDWIDE, PerilsScope.WAR_HIJACK),
        (TerritorialLimit.WORLDWIDE, PerilsScope.WAR_HIJACK_TERRORISM),
    ]
    market, policies, placements = _war_placements(api, plan)

    for (territory, scope), policy, placement in zip(plan, policies, placements):
        expected = c.war_premium_cents(WAR_LINE_CENTS, scope, territory)
        assert placement["perils_scope"] == scope
        assert placement["premium_cents"] == expected, (
            f"{scope} on an identical {WAR_LINE_CENTS} line: "
            f"expected {expected}, got {placement['premium_cents']}"
        )
        rows, meta = validate_list(
            api.list_premium_transactions(
                headers=users.UNDERWRITER,
                params={"policy_id": policy["id"], "limit": 100},
            )
        )
        assert meta["total_count"] == 1
        assert_ledger_row(
            rows[0],
            txn_type=TxnType.WAR_RISK_PREMIUM,
            amount_cents=expected,
            policy_id=policy["id"],
        )
        assert fx.fetch_policy(api, policy["id"])["written_premium_cents"] == expected

    # The three tiers are strictly increasing on the same ceded line.
    assert (
        placements[0]["premium_cents"]
        < placements[1]["premium_cents"]
        < placements[2]["premium_cents"]
    )


def test_war_premium_territory_step_rounds_up_and_commits_the_market_line(api):
    """PRD §3.7: "Then multiply that base by the policy's territory factor —
    1,000,000 for `DOMESTIC`, 1,080,000 for `CONTINENTAL`, 1,250,000 for
    `WORLDWIDE` — divide by 1,000,000 and round **up** to the next whole cent."

    Design: Corner/calculations/corner_war_premium_peril_tiers_then_territory_factor
    """
    plan = [
        (TerritorialLimit.WORLDWIDE, PerilsScope.WAR_ONLY),
        (TerritorialLimit.WORLDWIDE, PerilsScope.WAR_HIJACK),
        (TerritorialLimit.WORLDWIDE, PerilsScope.WAR_HIJACK_TERRORISM),
        (TerritorialLimit.DOMESTIC, PerilsScope.WAR_HIJACK),
    ]
    market, policies, placements = _war_placements(api, plan)

    worldwide_hijack = placements[1]["premium_cents"]
    domestic_hijack = placements[3]["premium_cents"]
    peril_base = c.floor_ppm(WAR_LINE_CENTS, c.PERIL_RATE_PPM[PerilsScope.WAR_HIJACK])
    assert domestic_hijack == c.ceil_ppm(
        peril_base, c.TERRITORY_FACTOR_PPM[TerritorialLimit.DOMESTIC]
    )
    assert worldwide_hijack == c.ceil_ppm(
        peril_base, c.TERRITORY_FACTOR_PPM[TerritorialLimit.WORLDWIDE]
    )
    assert worldwide_hijack > domestic_hijack, (
        "the same scope on the same line must cost more worldwide than domestically"
    )

    committed = len(plan) * WAR_LINE_CENTS
    fresh_market = fx.fetch_war_market(api, market["id"])
    assert fresh_market["committed_line_cents"] == committed
    assert (
        fresh_market["available_line_cents"] == WAR_MARKET_AGGREGATE_CENTS - committed
    )


# ----------------------------------------------------------------------
# Straight-line depreciation with a hard residual floor
# ----------------------------------------------------------------------
DEP_NEW_VALUE_CENTS = 40000000
DEP_MANUFACTURE_YEARS = (2012, 2011, 2005)
CLOCK_NEXT_CALENDAR_YEAR = "2027-01-01T00:00:00Z"


def _three_ageing_airframes(api):
    """One airframe still decaying and two already resting on the residual floor."""
    fx.advance_clock(api, f.CLOCK_BEFORE_INCEPTION)
    return [
        fx.make_aircraft(
            api,
            f.single_piston_aircraft_payload(
                registration_mark=f.unique_registration_mark(),
                manufacture_year=year,
                hull_new_value_cents=DEP_NEW_VALUE_CENTS,
            ),
        )
        for year in DEP_MANUFACTURE_YEARS
    ]


def test_depreciation_stops_at_the_forty_per_cent_residual_floor(api):
    """PRD §3.1: "Forty per cent of new value is the floor: an airframe fifteen
    years old and an airframe forty years old both retain forty per cent."

    Design: Corner/calculations/corner_depreciation_residual_floor_absorbs_further_ageing
    """
    airframes = _three_ageing_airframes(api)
    reference_year = c.calendar_year_of(f.CLOCK_BEFORE_INCEPTION)

    reported = []
    for airframe, manufacture_year in zip(airframes, DEP_MANUFACTURE_YEARS):
        expected = c.depreciated_value_cents(
            DEP_NEW_VALUE_CENTS, manufacture_year, reference_year
        )
        fresh = fx.fetch_aircraft(api, airframe["id"])
        assert fresh["current_depreciated_value_cents"] == expected, (
            f"a {manufacture_year} airframe read in {reference_year}: "
            f"expected {expected}, got {fresh['current_depreciated_value_cents']}"
        )
        reported.append(fresh["current_depreciated_value_cents"])

    floor_value = c.floor_ppm(DEP_NEW_VALUE_CENTS, c.RESIDUAL_FLOOR_PPM)
    assert reported[0] > floor_value, "a fourteen-year-old airframe is still decaying"
    assert reported[1] == floor_value
    assert reported[2] == floor_value, (
        "further ageing beyond the floor erodes nothing more, so the fifteen-year-old "
        "and the twenty-one-year-old airframe report the same residual"
    )


def test_depreciated_value_is_re_derived_against_the_clock_year(api):
    """PRD §3.1: "For the value reported on a read, the reference year is the
    calendar year of the current logical clock."

    Design: Corner/calculations/corner_depreciation_residual_floor_absorbs_further_ageing
    """
    airframes = _three_ageing_airframes(api)
    before = [
        fx.fetch_aircraft(api, airframe["id"])["current_depreciated_value_cents"]
        for airframe in airframes
    ]

    fx.advance_clock(api, CLOCK_NEXT_CALENDAR_YEAR)
    later_year = c.calendar_year_of(CLOCK_NEXT_CALENDAR_YEAR)
    after = [
        fx.fetch_aircraft(api, airframe["id"])["current_depreciated_value_cents"]
        for airframe in airframes
    ]

    for index, manufacture_year in enumerate(DEP_MANUFACTURE_YEARS):
        expected = c.depreciated_value_cents(
            DEP_NEW_VALUE_CENTS, manufacture_year, later_year
        )
        assert after[index] == expected, (
            f"a {manufacture_year} airframe read in {later_year}: "
            f"expected {expected}, got {after[index]}"
        )

    floor_value = c.floor_ppm(DEP_NEW_VALUE_CENTS, c.RESIDUAL_FLOOR_PPM)
    assert after[0] < before[0], "one more calendar year of age erodes four per cent"
    assert after[0] == floor_value, "the newest airframe has now reached the floor too"
    assert after[1] == before[1] == floor_value
    assert after[2] == before[2] == floor_value


# ----------------------------------------------------------------------
# The recurrency penalty is evaluated against the clock, not frozen
# ----------------------------------------------------------------------
POLICY_BASE_RATE_PPM = 18000
RECURRENCY_PILOT = {
    "pilot_name": "Dana Reyes",
    "license_type": LicenseType.CPL,
    "total_logged_hours": 1200,
    "hours_on_type": 80,
    "instrument_rated": False,
    "last_training_completed_at": "2026-06-01T00:00:00Z",
    # Deliberately distant, so the medical never becomes the reason a hull is refused.
    "medical_expires_at": "2029-06-30T00:00:00Z",
}
CLOCK_PAST_RECURRENCY_HORIZON = "2027-06-05T00:00:00Z"
LATER_TERM_FROM = "2027-07-01T00:00:00Z"
LATER_TERM_TO = "2028-07-01T00:00:00Z"


def _logged_score_at(clock_utc):
    """The logged-hours qualification score this pilot record earns at a clock."""
    return c.qualification_score(
        RECURRENCY_PILOT["total_logged_hours"],
        RECURRENCY_PILOT["hours_on_type"],
        RECURRENCY_PILOT["instrument_rated"],
        RECURRENCY_PILOT["license_type"],
        RECURRENCY_PILOT["last_training_completed_at"],
        clock_utc,
    )


def test_recurrency_penalty_re_scores_the_same_pilot_when_the_clock_advances(api):
    """PRD §3.2: "Because the recurrency penalty is evaluated against the clock at
    the moment of computation rather than frozen at registration, the same
    untouched pilot record legitimately scores 200 points lower once the clock has
    been advanced past their recurrency horizon."

    Design: Corner/calculations/corner_recurrency_penalty_re_scores_the_pilot_on_the_clock
    """
    fx.advance_clock(api, f.CLOCK_BEFORE_INCEPTION)
    pilot = fx.make_pilot(api, f.pilot_payload(**RECURRENCY_PILOT))

    before = fx.fetch_pilot(api, pilot["id"])
    expected_before = _logged_score_at(f.CLOCK_BEFORE_INCEPTION)
    assert before["qualification_score_logged"] == expected_before
    assert before["rating_band_logged"] == c.band_for_score(expected_before)
    assert (
        c.whole_days_between(
            RECURRENCY_PILOT["last_training_completed_at"], f.CLOCK_BEFORE_INCEPTION
        )
        <= c.RECURRENCY_GRACE_DAYS
    )

    fx.advance_clock(api, CLOCK_PAST_RECURRENCY_HORIZON)
    after = fx.fetch_pilot(api, pilot["id"])
    expected_after = _logged_score_at(CLOCK_PAST_RECURRENCY_HORIZON)
    assert (
        c.whole_days_between(
            RECURRENCY_PILOT["last_training_completed_at"],
            CLOCK_PAST_RECURRENCY_HORIZON,
        )
        > c.RECURRENCY_GRACE_DAYS
    )
    assert after["qualification_score_logged"] == expected_after
    assert after["rating_band_logged"] == c.band_for_score(expected_after)
    assert expected_after == expected_before - c.RECURRENCY_PENALTY_POINTS
    assert after["rating_band_logged"] != before["rating_band_logged"]

    # Nothing about the stored record moved; only the clock did.
    assert after["total_logged_hours"] == RECURRENCY_PILOT["total_logged_hours"]
    assert after["hours_on_type"] == RECURRENCY_PILOT["hours_on_type"]
    assert after["last_training_completed_at"] == before["last_training_completed_at"]
    assert after["version"] == before["version"]


def test_a_hull_written_after_the_recurrency_horizon_rates_on_the_lower_band(api):
    """PRD §3.4: "Third apply the pilot-band factor to that result: multiply by
    900,000 for `BAND_A`, 1,000,000 for `BAND_B`, 1,250,000 for `BAND_C` or
    1,600,000 for `BAND_D`, divide by 1,000,000, and discard the fraction."

    Design: Corner/calculations/corner_recurrency_penalty_re_scores_the_pilot_on_the_clock
    """
    fx.advance_clock(api, f.CLOCK_BEFORE_INCEPTION)
    operator = fx.make_operator(api)
    twin = fx.make_aircraft(api)
    turboprop = fx.make_aircraft(
        api,
        f.turboprop_aircraft_payload(
            registration_mark=f.unique_registration_mark(),
            hull_new_value_cents=48000000,
        ),
    )
    pilot = fx.make_pilot(api, f.pilot_payload(**RECURRENCY_PILOT))
    first_policy = fx.make_policy(
        api, operator["id"], base_hull_rate_ppm=POLICY_BASE_RATE_PPM
    )
    first_schedule = fx.make_schedule(
        api, first_policy["id"], twin["id"], pilot["id"], agreed_value_cents=45000000
    )
    fx.bind_policy(api, first_policy["id"])

    band_before = c.band_for_score(_logged_score_at(f.CLOCK_BEFORE_INCEPTION))
    rate_before = c.rate_ppm_for(
        POLICY_BASE_RATE_PPM,
        UseClass.INSTRUCTIONAL,
        TerritorialLimit.WORLDWIDE,
        band_before,
    )
    premium_before = c.annual_premium_cents(
        45000000, rate_before, PolicyType.FLEET, 1
    )
    assert first_schedule["rated_pilot_band"] == band_before
    assert first_schedule["rate_ppm"] == rate_before
    assert first_schedule["hull_premium_cents"] == premium_before

    fx.advance_clock(api, CLOCK_PAST_RECURRENCY_HORIZON)
    later_policy = fx.make_policy(
        api,
        operator["id"],
        base_hull_rate_ppm=POLICY_BASE_RATE_PPM,
        effective_from=LATER_TERM_FROM,
        effective_to=LATER_TERM_TO,
    )
    later_schedule = fx.make_schedule(
        api,
        later_policy["id"],
        turboprop["id"],
        pilot["id"],
        agreed_value_cents=30000000,
        effective_from=LATER_TERM_FROM,
        effective_to=LATER_TERM_TO,
    )

    band_after = c.band_for_score(_logged_score_at(CLOCK_PAST_RECURRENCY_HORIZON))
    rate_after = c.rate_ppm_for(
        POLICY_BASE_RATE_PPM,
        UseClass.INSTRUCTIONAL,
        TerritorialLimit.WORLDWIDE,
        band_after,
    )
    assert later_schedule["rated_pilot_band"] == band_after
    assert later_schedule["rate_ppm"] == rate_after
    assert later_schedule["hull_premium_cents"] == c.annual_premium_cents(
        30000000, rate_after, PolicyType.FLEET, 1
    )
    assert rate_after > rate_before, "the penalised band carries the heavier factor"

    # The bound hull written before the advance is not retroactively re-rated.
    frozen = fx.fetch_schedule(api, first_schedule["id"])
    assert frozen["rated_pilot_band"] == band_before
    assert frozen["rate_ppm"] == rate_before
    assert frozen["hull_premium_cents"] == premium_before
    assert (
        fx.fetch_policy(api, first_policy["id"])["written_premium_cents"]
        == premium_before
    )


# ----------------------------------------------------------------------
# The reserve aggregate counts one input set, the paid aggregate another
# ----------------------------------------------------------------------
RESERVE_CENTS = 20000000
REPAIR_ESTIMATE_CENTS = 12000000
HULL_DEDUCTIBLE_PPM = 15000
SURVEY_INSTANT = "2026-10-25T00:00:00Z"


def _policy_carrying_three_claims(api):
    """One hull bearing an investigating, a denied and a reserved claim."""
    book = fx.bound_policy_with_hull(
        api, hull_deductible_ppm=HULL_DEDUCTIBLE_PPM
    )
    fx.advance_clock(api, f.CLOCK_LATE_TERM)

    investigating = fx.make_claim(
        api,
        book["policy_id"],
        book["schedule_id"],
        loss_date="2026-10-10T00:00:00Z",
        loss_description="Nosewheel shimmy damage",
    )
    fx.investigate_claim(api, investigating["id"])

    denied = fx.make_claim(
        api,
        book["policy_id"],
        book["schedule_id"],
        loss_date="2026-10-15T00:00:00Z",
        loss_description="Hangar rash, disputed",
    )
    fx.investigate_claim(api, denied["id"])
    denied = fx.decide_coverage(
        api, denied["id"], decision=CoverageDecision.DENIED
    )

    reserved = fx.make_claim(
        api,
        book["policy_id"],
        book["schedule_id"],
        loss_date="2026-10-20T00:00:00Z",
        loss_description="Hail damage to wing skins",
    )
    fx.investigate_claim(api, reserved["id"])
    fx.make_damage_assessment(
        api,
        reserved["id"],
        repair_cost_estimate_cents=REPAIR_ESTIMATE_CENTS,
        assessed_at=SURVEY_INSTANT,
    )
    reserved = fx.decide_coverage(
        api,
        reserved["id"],
        decision=CoverageDecision.COVERED,
        reserve_cents=RESERVE_CENTS,
    )

    book.update(
        {
            "investigating_claim_id": investigating["id"],
            "denied_claim_id": denied["id"],
            "reserved_claim_id": reserved["id"],
        }
    )
    return book


def test_outstanding_reserve_counts_only_the_reserved_claim(api):
    """PRD §2.9: "`outstanding_reserve_cents` is the sum of `reserve_cents` over the
    claims on the policy whose `adjustment_status` is `RESERVED`, and no other
    claims."

    Design: Corner/calculations/corner_outstanding_reserve_counts_only_reserved_claims
    """
    book = _policy_carrying_three_claims(api)

    policy = fx.fetch_policy(api, book["policy_id"])
    assert policy["outstanding_reserve_cents"] == RESERVE_CENTS, (
        "only the reserved claim contributes; the investigating and denied claims "
        "carry no reserve"
    )
    assert policy["paid_hull_cents"] == 0, "a reserved claim is not yet a paid claim"

    rows, meta = validate_list(
        api.list_claims(
            headers=users.UNDERWRITER,
            params={"policy_id": book["policy_id"], "limit": 100},
        )
    )
    assert meta["total_count"] == 3
    statuses = {row["id"]: row["adjustment_status"] for row in rows}
    assert statuses[book["investigating_claim_id"]] == AdjustmentStatus.INVESTIGATING
    assert statuses[book["denied_claim_id"]] == AdjustmentStatus.DENIED
    assert statuses[book["reserved_claim_id"]] == AdjustmentStatus.RESERVED
    reserves = {row["id"]: row["reserve_cents"] for row in rows}
    assert reserves[book["reserved_claim_id"]] == RESERVE_CENTS


def test_a_settled_partial_repair_moves_out_of_the_reserve_aggregate(api):
    """PRD §2.9: "`paid_hull_cents` is the sum of `settlement_amount_cents` over the
    claims on the policy whose `adjustment_status` is `SETTLED` and whose
    `loss_type` is either `HULL_DAMAGE` or `TOTAL_LOSS`."

    Design: Corner/calculations/corner_outstanding_reserve_counts_only_reserved_claims
    """
    book = _policy_carrying_three_claims(api)

    settled = fx.settle_claim(
        api, book["reserved_claim_id"], SettlementBasis.PARTIAL_REPAIR
    )
    expected_deductible = c.deductible_cents(
        REPAIR_ESTIMATE_CENTS, HULL_DEDUCTIBLE_PPM
    )
    expected_settlement = REPAIR_ESTIMATE_CENTS - expected_deductible
    assert settled["adjustment_status"] == AdjustmentStatus.SETTLED
    assert expected_deductible == c.MINIMUM_DEDUCTIBLE_CENTS, (
        "on this small a gross the flat minimum beats the percentage deductible"
    )
    assert settled["deductible_applied_cents"] == expected_deductible
    assert settled["settlement_amount_cents"] == expected_settlement

    policy = fx.fetch_policy(api, book["policy_id"])
    assert policy["outstanding_reserve_cents"] == 0, (
        "the claim left the reserved input set in the same request"
    )
    assert policy["paid_hull_cents"] == expected_settlement

    schedule = fx.fetch_schedule(api, book["schedule_id"])
    assert schedule["coverage_status"] == CoverageStatus.ACTIVE

    rows, meta = validate_list(
        api.list_premium_transactions(
            headers=users.UNDERWRITER,
            params={"policy_id": book["policy_id"], "limit": 100},
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["txn_type"] == TxnType.INITIAL_PREMIUM
    assert_no_ledger_row_of_type(rows, TxnType.SETTLEMENT_RETURN)

    assert (
        fx.fetch_claim(api, book["investigating_claim_id"])["adjustment_status"]
        == AdjustmentStatus.INVESTIGATING
    )
    assert (
        fx.fetch_claim(api, book["denied_claim_id"])["adjustment_status"]
        == AdjustmentStatus.DENIED
    )


# ----------------------------------------------------------------------
# The removal return floors twice, in a pinned order
# ----------------------------------------------------------------------
SHORT_RATE_AGREED_VALUE_CENTS = 30000000
REMOVAL_EFFECTIVE_DATE = f.CLOCK_LATE_TERM
ATPL_PILOT = {
    "pilot_name": "Morgan Vale",
    "license_type": LicenseType.ATPL,
    "total_logged_hours": 3000,
    "hours_on_type": 300,
    "instrument_rated": False,
    "last_training_completed_at": "2026-07-01T00:00:00Z",
    "medical_expires_at": "2028-01-31T00:00:00Z",
}


def _atpl_band_at(clock_utc):
    """The rating band the airline transport pilot record earns at a clock."""
    return c.band_for_score(
        c.qualification_score(
            ATPL_PILOT["total_logged_hours"],
            ATPL_PILOT["hours_on_type"],
            ATPL_PILOT["instrument_rated"],
            ATPL_PILOT["license_type"],
            ATPL_PILOT["last_training_completed_at"],
            clock_utc,
        )
    )


def _private_hull_with_quoted_removal(api):
    """A bound private hull and a quoted endorsement striking it off mid-term."""
    fx.advance_clock(api, f.CLOCK_BEFORE_INCEPTION)
    operator = fx.make_operator(api)
    airframe = fx.make_aircraft(
        api,
        f.single_piston_aircraft_payload(
            registration_mark=f.unique_registration_mark()
        ),
    )
    pilot = fx.make_pilot(api, f.pilot_payload(**ATPL_PILOT))
    policy = fx.make_policy(
        api,
        operator["id"],
        base_hull_rate_ppm=POLICY_BASE_RATE_PPM,
        permitted_use_classes=[UseClass.PRIVATE, UseClass.BUSINESS],
    )
    schedule = fx.make_schedule(
        api,
        policy["id"],
        airframe["id"],
        pilot["id"],
        use_class=UseClass.PRIVATE,
        agreed_value_cents=SHORT_RATE_AGREED_VALUE_CENTS,
    )
    fx.bind_policy(api, policy["id"])
    endorsement = fx.quoted_endorsement(
        api,
        f.remove_aircraft_endorsement_payload(
            policy["id"], schedule["id"], effective_date=REMOVAL_EFFECTIVE_DATE
        ),
    )
    return {
        "policy_id": policy["id"],
        "schedule_id": schedule["id"],
        "schedule": schedule,
        "endorsement": endorsement,
        "endorsement_id": endorsement["id"],
    }


def _short_rate_return_cents(annual_cents):
    """The unearned premium after the pro-rata floor, then the short-rate floor."""
    unexpired = c.whole_days_between(REMOVAL_EFFECTIVE_DATE, f.POLICY_EFFECTIVE_TO)
    unearned = c.pro_rata_return_cents(annual_cents, unexpired, f.POLICY_TERM_DAYS)
    return c.floor_ppm(unearned, c.REMOVE_AIRCRAFT_RETURN_PPM)


def test_removal_return_floors_the_pro_rata_step_before_the_short_rate_step(api):
    """PRD §3.6: "Applying the ninety per cent factor to the un-rounded pro-rata
    amount, or rounding only once, gives a different figure and is not the specified
    behaviour."

    Design: Corner/calculations/corner_short_rate_return_uses_two_stage_flooring
    """
    book = _private_hull_with_quoted_removal(api)

    expected_rate = c.rate_ppm_for(
        POLICY_BASE_RATE_PPM,
        UseClass.PRIVATE,
        TerritorialLimit.WORLDWIDE,
        _atpl_band_at(f.CLOCK_BEFORE_INCEPTION),
    )
    expected_annual = c.annual_premium_cents(
        SHORT_RATE_AGREED_VALUE_CENTS, expected_rate, PolicyType.FLEET, 1
    )
    assert book["schedule"]["rate_ppm"] == expected_rate
    assert book["schedule"]["hull_premium_cents"] == expected_annual

    expected_delta = -_short_rate_return_cents(expected_annual)
    unexpired = c.whole_days_between(REMOVAL_EFFECTIVE_DATE, f.POLICY_EFFECTIVE_TO)
    collapsed = -(
        (expected_annual * unexpired * c.REMOVE_AIRCRAFT_RETURN_PPM)
        // (f.POLICY_TERM_DAYS * c.PPM)
    )
    assert book["endorsement"]["status"] == EndorsementStatus.QUOTED
    assert book["endorsement"]["quoted_premium_delta_cents"] == expected_delta, (
        f"expected the twice-floored return {expected_delta}, got "
        f"{book['endorsement']['quoted_premium_delta_cents']}"
    )
    assert expected_delta != collapsed, (
        "these inputs must distinguish the two-stage rounding from the collapsed one"
    )


def test_binding_a_removal_posts_the_twice_floored_return_to_the_ledger(api):
    """PRD §3.6: "The delta is the negation of that twice-rounded result."

    Design: Corner/calculations/corner_short_rate_return_uses_two_stage_flooring
    """
    book = _private_hull_with_quoted_removal(api)
    expected_annual = book["schedule"]["hull_premium_cents"]
    expected_delta = -_short_rate_return_cents(expected_annual)

    bound = fx.bind_endorsement(api, book["endorsement_id"])
    assert bound["status"] == EndorsementStatus.BOUND
    assert bound["premium_delta_cents"] == expected_delta

    schedule = fx.fetch_schedule(api, book["schedule_id"])
    assert schedule["coverage_status"] == CoverageStatus.REMOVED

    policy = fx.fetch_policy(api, book["policy_id"])
    assert policy["live_schedule_count"] == 0
    assert policy["total_hull_sum_insured_cents"] == 0
    assert policy["written_premium_cents"] == expected_annual + expected_delta

    rows, meta = validate_list(
        api.list_premium_transactions(
            headers=users.UNDERWRITER,
            params={"policy_id": book["policy_id"], "limit": 100},
        )
    )
    assert meta["total_count"] == 2
    assert_ledger_row(
        rows[0],
        txn_type=TxnType.INITIAL_PREMIUM,
        amount_cents=expected_annual,
        basis=TxnBasis.ANNUAL,
    )
    assert_ledger_row(
        rows[1],
        txn_type=TxnType.ENDORSEMENT_PREMIUM,
        amount_cents=expected_delta,
        basis=TxnBasis.PRO_RATA,
        endorsement_id=book["endorsement_id"],
        effective_date=REMOVAL_EFFECTIVE_DATE,
    )


# ----------------------------------------------------------------------
# The rate corridor bites at both ends
# ----------------------------------------------------------------------
LOW_BASE_RATE_PPM = 8
HIGH_BASE_RATE_PPM = 30000
CLAMP_AGREED_VALUE_CENTS = 30000000
PPL_PILOT = {
    "pilot_name": "Robin Ashby",
    "license_type": LicenseType.PPL,
    "total_logged_hours": 600,
    "hours_on_type": 60,
    "instrument_rated": False,
    "last_training_completed_at": "2026-07-15T00:00:00Z",
    "medical_expires_at": "2028-05-31T00:00:00Z",
}


def _unclamped_chain_ppm(base_rate_ppm, use_class, territorial_limit_code, band):
    """The three pinned multiplications, each floored, with no corridor applied."""
    after_use_class = c.floor_ppm(base_rate_ppm, c.USE_CLASS_FACTOR_PPM[use_class])
    after_territory = c.floor_ppm(
        after_use_class, c.TERRITORY_FACTOR_PPM[territorial_limit_code]
    )
    return c.floor_ppm(after_territory, c.BAND_FACTOR_PPM[band])


def _rated_hull(api, base_rate_ppm, territorial_limit_code, use_class, pilot_fields):
    """One hull rated on a policy whose base rate drives the chain out of corridor."""
    fx.advance_clock(api, f.CLOCK_BEFORE_INCEPTION)
    operator = fx.make_operator(api)
    airframe = fx.make_aircraft(
        api,
        f.single_piston_aircraft_payload(
            registration_mark=f.unique_registration_mark()
        ),
    )
    pilot = fx.make_pilot(api, f.pilot_payload(**pilot_fields))
    policy = fx.make_policy(
        api,
        operator["id"],
        base_hull_rate_ppm=base_rate_ppm,
        territorial_limit_code=territorial_limit_code,
        permitted_use_classes=[use_class],
    )
    schedule = validate_unpaginated(
        api.create_schedule(
            f.schedule_payload(
                policy["id"],
                airframe["id"],
                pilot["id"],
                use_class=use_class,
                agreed_value_cents=CLAMP_AGREED_VALUE_CENTS,
            ),
            headers=users.UNDERWRITER,
        ),
        expected_status=201,
    )
    return pilot, policy, schedule


def test_a_rate_chain_falling_below_the_corridor_is_lifted_to_the_floor(api):
    """PRD §3.4: "Finally clamp the figure into the underwriting corridor: raise it
    to 8,000 parts per million if it has fallen below that, and lower it to 60,000
    parts per million if it has risen above that."

    Design: Corner/calculations/corner_rate_ppm_clamped_at_both_declared_bounds
    """
    pilot, policy, schedule = _rated_hull(
        api,
        LOW_BASE_RATE_PPM,
        TerritorialLimit.DOMESTIC,
        UseClass.PRIVATE,
        ATPL_PILOT,
    )
    assert pilot["rating_band_logged"] == PilotBand.BAND_A

    unclamped = _unclamped_chain_ppm(
        LOW_BASE_RATE_PPM,
        UseClass.PRIVATE,
        TerritorialLimit.DOMESTIC,
        PilotBand.BAND_A,
    )
    assert unclamped < c.RATE_FLOOR_PPM, (
        "these inputs must drive the raw chain below the corridor floor"
    )
    assert schedule["rate_ppm"] == c.RATE_FLOOR_PPM, (
        f"a raw chain of {unclamped} must be lifted to {c.RATE_FLOOR_PPM}, "
        f"got {schedule['rate_ppm']}"
    )

    expected_premium = c.annual_premium_cents(
        CLAMP_AGREED_VALUE_CENTS, c.RATE_FLOOR_PPM, PolicyType.FLEET, 1
    )
    assert schedule["hull_premium_cents"] == expected_premium
    assert schedule["hull_premium_cents"] != c.floor_ppm(
        CLAMP_AGREED_VALUE_CENTS, unclamped
    )


def test_a_rate_chain_rising_above_the_corridor_is_cut_to_the_ceiling(api):
    """PRD §3.4: "Finally clamp the figure into the underwriting corridor: raise it
    to 8,000 parts per million if it has fallen below that, and lower it to 60,000
    parts per million if it has risen above that."

    Design: Corner/calculations/corner_rate_ppm_clamped_at_both_declared_bounds
    """
    pilot, policy, schedule = _rated_hull(
        api,
        HIGH_BASE_RATE_PPM,
        TerritorialLimit.WORLDWIDE,
        UseClass.INSTRUCTIONAL,
        PPL_PILOT,
    )
    assert pilot["rating_band_logged"] == PilotBand.BAND_D

    unclamped = _unclamped_chain_ppm(
        HIGH_BASE_RATE_PPM,
        UseClass.INSTRUCTIONAL,
        TerritorialLimit.WORLDWIDE,
        PilotBand.BAND_D,
    )
    assert unclamped > c.RATE_CEILING_PPM, (
        "these inputs must drive the raw chain above the corridor ceiling"
    )
    assert schedule["rate_ppm"] == c.RATE_CEILING_PPM, (
        f"a raw chain of {unclamped} must be cut to {c.RATE_CEILING_PPM}, "
        f"got {schedule['rate_ppm']}"
    )

    expected_premium = c.annual_premium_cents(
        CLAMP_AGREED_VALUE_CENTS, c.RATE_CEILING_PPM, PolicyType.FLEET, 1
    )
    assert schedule["hull_premium_cents"] == expected_premium
    assert schedule["hull_premium_cents"] != c.floor_ppm(
        CLAMP_AGREED_VALUE_CENTS, unclamped
    )
    assert (
        schedule["warranted_min_total_hours"]
        == c.WARRANTY_MIN_TOTAL_HOURS[UseClass.INSTRUCTIONAL]
    )
    assert (
        schedule["warranted_min_hours_on_type"]
        == c.WARRANTY_MIN_ON_TYPE_HOURS[UseClass.INSTRUCTIONAL]
    )


# ----------------------------------------------------------------------
# Exactly one exposure branch runs, and it is the one named
# ----------------------------------------------------------------------
EXPOSURE_TYPES = (
    EndorsementType.NON_OWNED_EXPOSURE,
    EndorsementType.RENTER_EXPOSURE,
    EndorsementType.FLYING_CLUB_EXPOSURE,
)
EXPOSURE_MEMBER_COUNT = 12
EXPOSURE_PER_SEAT_LIMIT_CENTS = 50000000
EXPOSURE_EFFECTIVE_DATE = f.CLOCK_LATE_TERM


def _expected_exposure_delta(endorsement_type):
    """The apportioned charge for one exposure structure, floored then rounded up."""
    base_annual = c.floor_ppm(
        EXPOSURE_MEMBER_COUNT * EXPOSURE_PER_SEAT_LIMIT_CENTS,
        c.EXPOSURE_RATE_PPM[endorsement_type],
    )
    unexpired = c.whole_days_between(EXPOSURE_EFFECTIVE_DATE, f.POLICY_EFFECTIVE_TO)
    return c.pro_rata_charge_cents(base_annual, unexpired, f.POLICY_TERM_DAYS)


def _quoted_exposure_endorsements(api):
    """One quoted endorsement per exposure structure on the same bound policy."""
    book = fx.bound_policy_with_hull(api)
    book["quotes"] = {
        endorsement_type: fx.quoted_endorsement(
            api,
            f.exposure_endorsement_payload(
                book["policy_id"],
                endorsement_type,
                exposure_member_count=EXPOSURE_MEMBER_COUNT,
                per_seat_limit_cents=EXPOSURE_PER_SEAT_LIMIT_CENTS,
                effective_date=EXPOSURE_EFFECTIVE_DATE,
            ),
        )
        for endorsement_type in EXPOSURE_TYPES
    }
    return book


def test_each_exposure_structure_is_priced_on_its_own_rate_alone(api):
    """PRD §3.6: "For the three exposure structures, a base annual figure is built
    first: multiply `exposure_member_count` by `per_seat_limit_cents`, multiply that
    product by the rate for the type — 900 parts per million for
    `NON_OWNED_EXPOSURE`, 1,400 for `RENTER_EXPOSURE` and 1,100 for
    `FLYING_CLUB_EXPOSURE` — divide by 1,000,000 and discard the fraction; then
    apportion that base over the unexpired days against `term_days` and round up."

    Design: Corner/calculations/corner_exposure_endorsement_branch_selection_is_exclusive
    """
    book = _quoted_exposure_endorsements(api)
    expected = {t: _expected_exposure_delta(t) for t in EXPOSURE_TYPES}
    assert len(set(expected.values())) == len(EXPOSURE_TYPES), (
        "these inputs must give each exposure structure a distinct charge"
    )

    for endorsement_type, endorsement in book["quotes"].items():
        assert endorsement["endorsement_type"] == endorsement_type
        assert endorsement["status"] == EndorsementStatus.QUOTED
        assert endorsement["quote_round"] == 1
        assert endorsement["quoted_premium_delta_cents"] == expected[endorsement_type], (
            f"{endorsement_type} must price on its own rate: expected "
            f"{expected[endorsement_type]}, got "
            f"{endorsement['quoted_premium_delta_cents']}"
        )
        others = [
            value
            for other, value in expected.items()
            if other != endorsement_type
        ]
        assert endorsement["quoted_premium_delta_cents"] not in others, (
            f"{endorsement_type} must not borrow another structure's rate"
        )
        assert endorsement["exposure_member_count"] == EXPOSURE_MEMBER_COUNT
        assert endorsement["per_seat_limit_cents"] == EXPOSURE_PER_SEAT_LIMIT_CENTS
        assert endorsement["premium_delta_cents"] is None


def test_binding_an_exposure_structure_charges_premium_but_moves_no_hull(api):
    """PRD §3.6: "The three exposure types have no structural effect beyond their
    premium."

    Design: Corner/calculations/corner_exposure_endorsement_branch_selection_is_exclusive
    """
    book = _quoted_exposure_endorsements(api)
    before = fx.fetch_policy(api, book["policy_id"])
    chosen = book["quotes"][EndorsementType.RENTER_EXPOSURE]
    expected_delta = _expected_exposure_delta(EndorsementType.RENTER_EXPOSURE)

    bound = fx.bind_endorsement(api, chosen["id"])
    assert bound["status"] == EndorsementStatus.BOUND
    assert bound["premium_delta_cents"] == expected_delta

    after = fx.fetch_policy(api, book["policy_id"])
    assert after["written_premium_cents"] == (
        before["written_premium_cents"] + expected_delta
    )
    assert after["total_hull_sum_insured_cents"] == (
        before["total_hull_sum_insured_cents"]
    )
    assert after["live_schedule_count"] == before["live_schedule_count"]

    schedule = fx.fetch_schedule(api, book["schedule_id"])
    assert schedule["coverage_status"] == CoverageStatus.ACTIVE
    assert schedule["agreed_value_cents"] == book["schedule"]["agreed_value_cents"]
    assert schedule["use_class"] == book["schedule"]["use_class"]

    rows = fx.ledger_rows(api, book["policy_id"])
    endorsement_rows = rows_of_type(rows, TxnType.ENDORSEMENT_PREMIUM)
    assert len(endorsement_rows) == 1
    assert_ledger_row(
        endorsement_rows[0],
        txn_type=TxnType.ENDORSEMENT_PREMIUM,
        amount_cents=expected_delta,
        basis=TxnBasis.PRO_RATA,
        endorsement_id=chosen["id"],
        effective_date=EXPOSURE_EFFECTIVE_DATE,
    )
