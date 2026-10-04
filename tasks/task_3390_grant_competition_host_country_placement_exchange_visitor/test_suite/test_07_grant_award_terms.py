"""Grant terms: provisional vs final award, dependent cap, overlap (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    accept_placement_round,
    add_country_program,
    assert_grant,
    close_cycle,
    confirm_grant,
    confirm_grant_payload,
    create_country_program_payload,
    create_cycle,
    create_draft_application,
    get_application,
    get_grant,
    host_decide,
    open_cycle,
    open_placement_round,
    post_national_quorum_scores,
    recommend_application,
    register_applicant,
    round_half_up_div,
    set_clock_to,
    setup_confirmed_grant,
    setup_grant_pending,
    setup_selected_application,
    submit_application,
    validate_error,
    validate_success,
)


def _confirm_two_cycle_victor():
    """Victor holds a CONFIRMED grant [2027-09-01, 2028-09-01) from cycle 1
    and reaches GRANT_PENDING in cycle 2. Returns (victor, grant1, app2)."""
    cycle1 = create_cycle()
    program1 = add_country_program(cycle1)  # DE, quota 1, 6-12 months
    open_cycle(cycle1)
    victor = register_applicant()
    app1 = create_draft_application(
        victor, cycle1, program1, proposed_duration_months=12,
        project_title="Salt Marsh Carbon",
    )
    app1 = submit_application(app1, victor)
    post_national_quorum_scores(app1, score=82)
    close_cycle(cycle1)
    app1 = recommend_application(app1)
    app1 = host_decide(app1, "SELECT")
    round1 = open_placement_round(app1)
    accept_placement_round(round1, victor)
    grant1 = confirm_grant(
        app1, start_date="2027-09-01T00:00:00Z", end_date="2028-09-01T00:00:00Z",
    )
    assert grant1["status"] == "CONFIRMED"

    cycle2 = create_cycle(
        academic_year="2028-2029", application_deadline="2027-06-01T23:59:59Z",
    )
    program2 = add_country_program(
        cycle2, country_code="FR", min_duration_months=3,
    )
    open_cycle(cycle2)
    app2 = create_draft_application(
        victor, cycle2, program2, proposed_duration_months=6,
        project_title="Loire Wetlands",
    )
    app2 = submit_application(app2, victor)
    post_national_quorum_scores(app2, score=84)
    close_cycle(cycle2)
    app2 = recommend_application(app2)
    app2 = host_decide(app2, "SELECT")
    round2 = open_placement_round(
        app2, institution_name="Sorbonne Hydrology",
        response_deadline="2027-08-01T00:00:00Z",
    )
    accept_placement_round(round2, victor)
    assert get_application(app2)["status"] == "GRANT_PENDING"
    return victor, grant1, app2


def test_confirm_duration_outside_country_range_returns_422(
    api, program_officer_headers,
):
    """PRD §3.6: "Confirmation is gated: the application must be
    GRANT_PENDING, meaning an accepted placement exists
    (`ERR_PLACEMENT_NOT_SECURED`); the grant must still be PROVISIONAL
    (`ERR_INVALID_STATE`); the confirmed duration must fall within the country
    program's bounds (`ERR_DURATION_OUT_OF_RANGE`); the `start_date` must not
    precede the logical clock's date (`ERR_START_DATE_IN_PAST`); and the
    requested period must not collide with another live grant of the same
    applicant (`ERR_GRANT_PERIOD_OVERLAP`)."

    2027-09-01 to 2028-10-01 spans 13 whole calendar months, above the
    program's 12-month maximum.

    Design: Corner/state_machines/confirm_duration_outside_country_range_returns_422
    """
    bundle = setup_grant_pending()
    resp = api.confirm_grant(
        bundle["application"]["id"],
        confirm_grant_payload(
            start_date="2027-09-01T00:00:00Z", end_date="2028-10-01T00:00:00Z",
        ),
        program_officer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DURATION_OUT_OF_RANGE)

    assert get_grant(bundle["grant"])["status"] == "PROVISIONAL"
    assert get_application(bundle["application"])["status"] == "GRANT_PENDING"


def test_confirm_start_in_past_returns_start_date_in_past(
    api, program_officer_headers,
):
    """PRD §3.6: "Confirmation is gated: the application must be
    GRANT_PENDING, meaning an accepted placement exists
    (`ERR_PLACEMENT_NOT_SECURED`); the grant must still be PROVISIONAL
    (`ERR_INVALID_STATE`); the confirmed duration must fall within the country
    program's bounds (`ERR_DURATION_OUT_OF_RANGE`); the `start_date` must not
    precede the logical clock's date (`ERR_START_DATE_IN_PAST`); and the
    requested period must not collide with another live grant of the same
    applicant (`ERR_GRANT_PERIOD_OVERLAP`)."

    At clock 2027-08-01 a 2027-07-01 start is in the past; the 10-month
    window itself is inside the program's 6-12 bounds, so only the temporal
    check can fail.

    Design: Corner/endpoints/confirm_start_in_past_returns_start_date_in_past
    """
    bundle = setup_grant_pending()
    set_clock_to("2027-08-01T00:00:00Z")

    resp = api.confirm_grant(
        bundle["application"]["id"],
        confirm_grant_payload(
            start_date="2027-07-01T00:00:00Z", end_date="2028-05-01T00:00:00Z",
        ),
        program_officer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_START_DATE_IN_PAST)

    assert get_grant(bundle["grant"])["status"] == "PROVISIONAL"


def test_provisional_award_uses_standard_band_and_uncapped_dependents(api):
    """PRD §3.6: "The provisional monthly stipend is always the country
    program's STANDARD-band figure, stored as
    `provisional_monthly_stipend_cents`."
    PRD §3.6: "The `provisional_total_cents` is then the per-month sum of
    monthly stipend, monthly dependent allowance, and monthly health premium,
    multiplied by the application's `proposed_duration_months`, plus the
    one-time `travel_allowance_cents`."

    (300000 + 50000*min(3,2) + 20000)*10 + 150000 = 4350000.

    Design: Difficulty/dual_variant_calc/grant_award_provisional_vs_final_divergence
    """
    bundle = setup_selected_application(
        application_overrides={"dependents_count": 3, "proposed_duration_months": 10},
    )
    grant = bundle["grant"]
    assert_grant(grant)
    assert grant["status"] == "PROVISIONAL"
    assert grant["provisional_monthly_stipend_cents"] == 300000, (
        "the provisional variant always quotes the STANDARD band"
    )
    assert grant["provisional_total_cents"] == 4350000, (
        f"expected 4350000, got {grant['provisional_total_cents']}"
    )


def test_final_award_diverges_from_provisional_on_high_band_and_cap(api):
    """PRD §3.6: "The dependent allowance cap is then evaluated in a pinned
    order: first the base total, which deliberately excludes any dependent
    allowance; then the cap, which is one quarter — 25% — of that base total,
    rounded half up to whole cents; then the granted dependent allowance,
    which is the smaller of the raw allowance and the cap."
    PRD §3.6: "Because the provisional variant pins the STANDARD band and
    skips the cap, the two variants diverge on identical application data
    whenever the accepted band is HIGH or the cap binds."

    HIGH band, 3 dependents, 10 months: base (360000+20000)*10+150000 =
    3950000; dep_raw 1000000 capped to round_half_up(0.25*3950000) = 987500;
    final 4937500 versus provisional 4350000.

    Design: Difficulty/dual_variant_calc/grant_award_provisional_vs_final_divergence
    """
    bundle = setup_grant_pending(
        institution_band="HIGH",
        application_overrides={"dependents_count": 3, "proposed_duration_months": 10},
    )
    grant = confirm_grant(
        bundle["application"],
        start_date="2027-09-01T00:00:00Z", end_date="2028-07-01T00:00:00Z",
    )
    assert_grant(grant)
    assert grant["awarded_band"] == "HIGH"
    assert grant["duration_months"] == 10
    assert grant["final_monthly_stipend_cents"] == 360000
    assert grant["final_total_cents"] == 4937500, (
        f"3950000 + 987500 = 4937500, got {grant['final_total_cents']}"
    )
    assert grant["provisional_total_cents"] == 4350000
    assert grant["final_total_cents"] != grant["provisional_total_cents"], (
        "the variants must diverge on identical data when the band is HIGH"
    )
    assert get_application(bundle["application"])["status"] == "AWARDED"


def test_final_award_standard_band_no_truncation_matches_formula(api):
    """PRD §3.6: "The final monthly stipend, stored as
    `final_monthly_stipend_cents`, is the program's
    `monthly_stipend_high_cents` when the awarded band is HIGH and its
    `monthly_stipend_standard_cents` otherwise."
    PRD §3.6: "The duration itself, stored as `duration_months`, counts whole
    calendar months between the two dates — twelve times the difference
    between the end and start years, plus the difference between the end and
    start months, with days ignored."

    STANDARD band, 1 dependent (no min() truncation), 2027-09-01 to
    2028-07-01: base (300000+20000)*10 + 150000 = 3350000; dep
    50000*min(1,2)*10 = 500000 under the 837500 cap; final 3850000.

    Design: Difficulty/combinatorial_formula/grant_terms_band_min_duration_combinatorics
    """
    bundle = setup_confirmed_grant(
        application_overrides={"dependents_count": 1, "proposed_duration_months": 10},
    )
    grant = bundle["grant"]
    assert_grant(grant)
    assert grant["awarded_band"] == "STANDARD"
    assert grant["final_monthly_stipend_cents"] == 300000
    assert grant["duration_months"] == 10, (
        f"(2028-2027)*12 + (7-9) = 10, got {grant['duration_months']}"
    )
    assert grant["final_total_cents"] == 3850000, (
        f"3350000 + 500000 = 3850000, got {grant['final_total_cents']}"
    )


def test_provisional_and_final_coincide_when_no_branch_binds(
    api, program_officer_headers,
):
    """PRD §3.6: "The provisional variant deliberately quotes the STANDARD
    band, uses the requested duration, and applies no percentage cap to the
    dependent allowance."
    PRD §3.6: "Because the provisional variant pins the STANDARD band and
    skips the cap, the two variants diverge on identical application data
    whenever the accepted band is HIGH or the cap binds."

    STANDARD band, 1 dependent, 10 requested and confirmed months: neither
    divergence condition holds, so provisional == final == 3850000.

    Design: Difficulty/combinatorial_formula/grant_terms_band_min_duration_combinatorics
    """
    bundle = setup_confirmed_grant(
        application_overrides={"dependents_count": 1, "proposed_duration_months": 10},
    )
    grants = validate_success(
        api.list_application_grants(bundle["application"]["id"], program_officer_headers)
    )
    assert len(grants) == 1
    grant = grants[0]
    assert grant["provisional_total_cents"] == 3850000, (
        f"(300000 + 50000*1 + 20000)*10 + 150000 = 3850000, "
        f"got {grant['provisional_total_cents']}"
    )
    assert grant["final_total_cents"] == 3850000
    assert grant["provisional_total_cents"] == grant["final_total_cents"]


def test_dependent_cap_binds_against_base_total_excluding_allowance(api):
    """PRD §3.6: "The dependent allowance cap is then evaluated in a pinned
    order: first the base total, which deliberately excludes any dependent
    allowance; then the cap, which is one quarter — 25% — of that base total,
    rounded half up to whole cents; then the granted dependent allowance,
    which is the smaller of the raw allowance and the cap."

    IN program (dependent allowance 200000/month), 2 dependents, 12 months:
    base (300000+20000)*12 + 150000 = 3990000; dep_raw 4800000; cap
    round_half_up(0.25*3990000) = 997500; final = 3990000 + 997500 = 4987500.

    Design: Difficulty/combinatorial_formula/dependent_cap_evaluation_order_pinned
    """
    bundle = setup_confirmed_grant(
        program_overrides={
            "country_code": "IN", "slot_quota": 2,
            "min_duration_months": 3, "max_duration_months": 12,
            "monthly_stipend_high_cents": 350000,
            "dependent_allowance_monthly_cents": 200000,
        },
        application_overrides={"proposed_duration_months": 12, "dependents_count": 2},
        start_date="2027-09-01T00:00:00Z", end_date="2028-09-01T00:00:00Z",
    )
    grant = bundle["grant"]
    assert grant["duration_months"] == 12
    assert grant["final_monthly_stipend_cents"] == 300000
    assert grant["final_total_cents"] == 4987500, (
        f"base 3990000 + capped dependent 997500 = 4987500, "
        f"got {grant['final_total_cents']}"
    )


def test_dependent_cap_wrong_order_value_is_not_returned(api):
    """PRD §3.6: "Computing the quarter against a base that already includes
    the dependent allowance yields a different figure and is wrong."

    Capping against base_total + dep_raw (3990000 + 4800000) would grant
    2197500 and total 6187500 — the pinned order yields 4987500 instead.

    Design: Difficulty/combinatorial_formula/dependent_cap_evaluation_order_pinned
    """
    bundle = setup_confirmed_grant(
        program_overrides={
            "country_code": "IN", "slot_quota": 2,
            "min_duration_months": 3, "max_duration_months": 12,
            "monthly_stipend_high_cents": 350000,
            "dependent_allowance_monthly_cents": 200000,
        },
        application_overrides={"proposed_duration_months": 12, "dependents_count": 2},
        start_date="2027-09-01T00:00:00Z", end_date="2028-09-01T00:00:00Z",
    )
    grant = bundle["grant"]
    base_total = (300000 + 20000) * 12 + 150000
    assert base_total == 3990000
    dep_cap = round_half_up_div(base_total, 4)  # round_half_up(0.25 * base)
    assert dep_cap == 997500
    assert grant["final_total_cents"] == base_total + dep_cap
    assert grant["final_total_cents"] != 6187500, (
        "the cap must be keyed on the base total EXCLUDING the allowance"
    )


def test_grant_period_overlap_with_existing_grant_rejected(
    api, program_officer_headers,
):
    """PRD §3.6: "For the overlap rule the period is treated as running from
    `start_date` up to but not including `end_date`; it overlaps another grant
    of the same applicant in CONFIRMED, ACTIVE, or SUSPENDED status whenever
    the two periods share any day under that convention, while pure adjacency
    — a new start exactly equal to an existing end — is permitted."

    Existing CONFIRMED grant [2027-09-01, 2028-09-01); a new period starting
    2028-08-01 shares August 2028 with it.

    Design: Difficulty/resource_temporal_overlap/grant_period_half_open_overlap
    """
    victor, grant1, app2 = _confirm_two_cycle_victor()
    assert grant1["start_date"].startswith("2027-09-01")
    assert grant1["end_date"].startswith("2028-09-01")

    resp = api.confirm_grant(
        app2["id"],
        confirm_grant_payload(
            start_date="2028-08-01T00:00:00Z", end_date="2029-02-01T00:00:00Z",
        ),
        program_officer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_GRANT_PERIOD_OVERLAP)

    grants2 = validate_success(
        api.list_application_grants(app2["id"], program_officer_headers)
    )
    assert grants2[0]["status"] == "PROVISIONAL", (
        "a rejected confirmation must leave the grant PROVISIONAL"
    )
    assert get_application(app2)["status"] == "GRANT_PENDING"


def test_grant_period_adjacency_is_permitted(api, program_officer_headers):
    """PRD §3.6: "For the overlap rule the period is treated as running from
    `start_date` up to but not including `end_date`; it overlaps another grant
    of the same applicant in CONFIRMED, ACTIVE, or SUSPENDED status whenever
    the two periods share any day under that convention, while pure adjacency
    — a new start exactly equal to an existing end — is permitted."

    After the overlapping attempt fails, retrying with start 2028-09-01 —
    exactly the existing grant's end_date — succeeds: half-open adjacency is
    not overlap, and a failed confirmation leaves the grant retryable.

    Design: Difficulty/resource_temporal_overlap/grant_period_half_open_overlap
    """
    victor, grant1, app2 = _confirm_two_cycle_victor()

    overlap = api.confirm_grant(
        app2["id"],
        confirm_grant_payload(
            start_date="2028-08-01T00:00:00Z", end_date="2029-02-01T00:00:00Z",
        ),
        program_officer_headers,
    )
    validate_error(overlap, ApiErrorId.ERR_GRANT_PERIOD_OVERLAP)

    adjacent = api.confirm_grant(
        app2["id"],
        confirm_grant_payload(
            start_date="2028-09-01T00:00:00Z", end_date="2029-03-01T00:00:00Z",
        ),
        program_officer_headers,
    )
    grant2 = validate_success(adjacent, 200)
    assert_grant(grant2)
    assert grant2["status"] == "CONFIRMED"
    assert grant2["duration_months"] == 6, (
        f"(2029-2028)*12 + (3-9) = 6, got {grant2['duration_months']}"
    )
    assert get_application(app2)["status"] == "AWARDED"
