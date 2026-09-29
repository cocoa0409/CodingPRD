"""Rent schedule publication, absorption pacing and the indexed repricing arithmetic."""

from test_helpers import (
    ASSET_MANAGER_ALT_USER_ID,
    ApiErrorId,
    absorption_review_payload,
    assert_instant_equals,
    assert_ratio_equals,
    clock_payload,
    community_version,
    create_absorption_review,
    create_amenity_phase,
    create_concession_program_payload,
    create_homesite,
    create_household,
    create_lease_payload,
    create_phase,
    create_plat_approved_community,
    draft_lease,
    indexed_schedule_payload,
    make_asset_manager_headers,
    make_household_headers,
    publish_schedule,
    publish_schedule_payload,
    read_community,
    read_lease,
    read_schedule,
    record_occupancy_certificate,
    release_section,
    set_clock,
    setup_absorption_review_scenario,
    setup_released_community,
    sign_lease,
    signature_payload,
    start_construction,
    submit_lease,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_pacing_index_multiplies_pace_supply_factor_and_restricted_penalty(
    api, asset_manager_headers
):
    """A window that absorbed exactly its planned units scores 0.9000 rather than 1.0000
    because the community was RESTRICTED when the review was taken, which lands the verdict
    in the MODERATE band.

    Otherwise: the raw pace is `actual_absorption_units` divided by `planned_absorption_units`; the supply factor is `available_supply_units` divided by `planned_absorption_units` — using 1 in place of the divisor if `planned_absorption_units` were ever smaller than 1 — and then clamped so that it is never below 0.75 and never above 1.25; and the posture penalty is 0.90 when `posture_at_review` is `RESTRICTED` and 1.00 otherwise, including when the posture was `FROZEN`.
    `pacing_index` is the raw pace multiplied by the supply factor multiplied by the posture penalty, rounded half up to four decimal places.
    From 0.8000 up to but not including 1.0000 the tier is `MODERATE` and the recommendation is 0 basis points.

    Design: Difficulty/combinatorial_formula/absorption_pacing_index_four_input_interaction_with_restricted_penalty
    """
    scenario = setup_absorption_review_scenario(
        executed_leases=2,
        homesite_count=4,
        total_planned_units=4,
        product_type="DETACHED",
        asking_rent_cents=285_000,
        clock="2026-08-08T00:00:00Z",
    )
    community_id = scenario["community"]["id"]
    create_amenity_phase(
        community_id,
        sequence_index=2,
        amenity_weight=1,
        construction_window_start="2026-08-01T00:00:00Z",
        construction_window_end="2026-12-01T00:00:00Z",
    )

    community = read_community(community_id)
    assert community["posture"] == "RESTRICTED"
    assert_ratio_equals(community["amenity_delivery_ratio"], 0.0000, "amenity_delivery_ratio")

    response = api.create_absorption_review(
        community_id,
        absorption_review_payload(
            product_type="DETACHED",
            window_start="2026-08-01T00:00:00Z",
            window_end="2026-08-08T00:00:00Z",
            planned_absorption_units=2,
        ),
        asset_manager_headers,
    )
    review = validate_success(response, expected_status=201)

    assert review["actual_absorption_units"] == 2
    assert review["available_supply_units"] == 2
    assert review["posture_at_review"] == "RESTRICTED"
    assert_ratio_equals(review["pacing_index"], 0.9000, "pacing_index")
    assert review["concession_tier"] == "MODERATE"
    assert review["recommended_growth_bps"] == 0


def test_pacing_index_without_the_restricted_penalty_scores_the_light_band(
    api, asset_manager_headers
):
    """The same two-of-two absorption window taken while the community is OPEN keeps the
    penalty at 1.00 and scores 1.0000, which is the LIGHT band and a positive recommendation
    — so the penalty alone moved the earlier verdict.

    Otherwise: the raw pace is `actual_absorption_units` divided by `planned_absorption_units`; the supply factor is `available_supply_units` divided by `planned_absorption_units` — using 1 in place of the divisor if `planned_absorption_units` were ever smaller than 1 — and then clamped so that it is never below 0.75 and never above 1.25; and the posture penalty is 0.90 when `posture_at_review` is `RESTRICTED` and 1.00 otherwise, including when the posture was `FROZEN`.
    From 1.0000 up to but not including 1.2000 the tier is `LIGHT` and the recommendation is 125 basis points.
    The boundaries are inclusive at the bottom: 1.0000 is `LIGHT`, and 0.9999 is `MODERATE`.

    Design: Difficulty/combinatorial_formula/absorption_pacing_index_four_input_interaction_with_restricted_penalty
    """
    scenario = setup_absorption_review_scenario(
        executed_leases=2,
        homesite_count=4,
        total_planned_units=4,
        product_type="DETACHED",
        asking_rent_cents=285_000,
        clock="2026-08-08T00:00:00Z",
    )
    community_id = scenario["community"]["id"]
    assert read_community(community_id)["posture"] == "OPEN"

    response = api.create_absorption_review(
        community_id,
        absorption_review_payload(
            product_type="DETACHED",
            window_start="2026-08-01T00:00:00Z",
            window_end="2026-08-08T00:00:00Z",
            planned_absorption_units=2,
        ),
        asset_manager_headers,
    )
    review = validate_success(response, expected_status=201)

    assert review["actual_absorption_units"] == 2
    assert review["available_supply_units"] == 2
    assert review["posture_at_review"] == "OPEN"
    assert_ratio_equals(review["pacing_index"], 1.0000, "pacing_index")
    assert review["concession_tier"] == "LIGHT"
    assert review["recommended_growth_bps"] == 125


def test_indexed_repricing_step_of_exactly_20000_cents_is_applied_unclamped(
    api, asset_manager_headers
):
    """A COTTAGE line repricing from 800,000 cents at the recommended 250 basis points has a
    step of exactly 20,000 cents, so the clamp is a no-op and the new asking rent is 820,000
    cents.

    A `pacing_index` of 1.2000 or more gives tier `NONE` and a recommendation of 250 basis points.
    The step is the baseline's `asking_rent_cents` multiplied by that basis-point figure and divided by 10,000, rounded half up to whole cents, and then clamped so that it never moves the rent by more than 200 dollars — 20,000 cents — in either direction.
    The new `asking_rent_cents` is the baseline's `asking_rent_cents` plus that clamped step, and `applied_growth_bps` records the basis-point figure that was applied.

    Design: Difficulty/boundary_precision_check/rent_growth_step_clamp_binds_at_exactly_20000_cents
    """
    scenario = setup_released_community(
        total_planned_units=8,
        product_mix={"DETACHED": 5, "COTTAGE": 3, "TOWNHOME": 0},
        homesite_specs=(
            [{"product_type": "DETACHED"} for _ in range(5)]
            + [{"product_type": "COTTAGE"} for _ in range(3)]
        ),
        asking_rents={"DETACHED": 900_000, "COTTAGE": 800_000},
        phase_overrides={
            "planned_unit_count": 8,
            "construction_window_end": "2026-12-01T00:00:00Z",
        },
        maintenance_tech_headcount=3,
        concession_budget_cents=8_000_000,
        facility_commitment_cents=120_000_000,
    )
    community_id = scenario["community"]["id"]
    for index in (0, 1, 5):
        household = create_household(monthly_income_cents=3_500_000)
        lease = draft_lease(scenario["homesites"][index]["id"], household["id"])
        submit_lease(lease["id"])
        sign_lease(lease["id"], household["id"], household["primary_applicant_name"])
    set_clock("2026-08-08T00:00:00Z")

    review = create_absorption_review(
        community_id,
        product_type="COTTAGE",
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-08T00:00:00Z",
        planned_absorption_units=1,
    )
    assert review["actual_absorption_units"] == 1
    assert review["available_supply_units"] == 2
    assert_ratio_equals(review["pacing_index"], 1.2500, "pacing_index")
    assert review["concession_tier"] == "NONE"
    assert review["recommended_growth_bps"] == 250

    response = api.publish_market_rent_schedule(
        indexed_schedule_payload(
            community_id,
            community_version(community_id),
            product_type="COTTAGE",
            effective_from="2026-08-08T00:00:00Z",
        ),
        asset_manager_headers,
    )
    republished = validate_success(response, expected_status=201)

    assert republished["asking_rent_cents"] == 820_000
    assert republished["applied_growth_bps"] == 250
    assert republished["status"] == "PUBLISHED"
    assert republished["superseded_at"] is None

    baseline = read_schedule(scenario["schedules"]["COTTAGE"]["id"])
    assert baseline["status"] == "SUPERSEDED"
    assert_instant_equals(baseline["superseded_at"], "2026-08-08T00:00:00Z", "superseded_at")


def test_indexed_repricing_step_above_20000_cents_is_clamped_without_rewriting_the_growth(
    api, asset_manager_headers
):
    """A DETACHED line repricing from 900,000 cents at the same 250 basis points has a raw step
    of 22,500 cents, so the clamp binds at 20,000 cents and the new rent is 920,000 rather than
    922,500 — while the applied growth is still recorded as the recommended 250 basis points.

    The step is the baseline's `asking_rent_cents` multiplied by that basis-point figure and divided by 10,000, rounded half up to whole cents, and then clamped so that it never moves the rent by more than 200 dollars — 20,000 cents — in either direction.
    Note the order: the step is rounded first and clamped second.
    The new `asking_rent_cents` is the baseline's `asking_rent_cents` plus that clamped step, and `applied_growth_bps` records the basis-point figure that was applied.
    Both values are frozen at creation and are never re-derived, so a later repricing of the community never disturbs a lease already drafted.

    Design: Difficulty/boundary_precision_check/rent_growth_step_clamp_binds_at_exactly_20000_cents
    """
    scenario = setup_released_community(
        total_planned_units=8,
        product_mix={"DETACHED": 5, "COTTAGE": 3, "TOWNHOME": 0},
        homesite_specs=(
            [{"product_type": "DETACHED"} for _ in range(5)]
            + [{"product_type": "COTTAGE"} for _ in range(3)]
        ),
        asking_rents={"DETACHED": 900_000, "COTTAGE": 800_000},
        phase_overrides={
            "planned_unit_count": 8,
            "construction_window_end": "2026-12-01T00:00:00Z",
        },
        maintenance_tech_headcount=3,
        concession_budget_cents=8_000_000,
        facility_commitment_cents=120_000_000,
    )
    community_id = scenario["community"]["id"]
    leases = []
    for index in (0, 1, 5):
        household = create_household(monthly_income_cents=3_500_000)
        lease = draft_lease(scenario["homesites"][index]["id"], household["id"])
        submit_lease(lease["id"])
        sign_lease(lease["id"], household["id"], household["primary_applicant_name"])
        leases.append(lease)
    set_clock("2026-08-08T00:00:00Z")

    review = create_absorption_review(
        community_id,
        product_type="DETACHED",
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-08T00:00:00Z",
        planned_absorption_units=2,
    )
    assert review["actual_absorption_units"] == 2
    assert review["available_supply_units"] == 3
    assert_ratio_equals(review["pacing_index"], 1.2500, "pacing_index")
    assert review["concession_tier"] == "NONE"
    assert review["recommended_growth_bps"] == 250

    response = api.publish_market_rent_schedule(
        indexed_schedule_payload(
            community_id,
            community_version(community_id),
            product_type="DETACHED",
            effective_from="2026-08-08T00:00:00Z",
        ),
        asset_manager_headers,
    )
    republished = validate_success(response, expected_status=201)

    assert republished["asking_rent_cents"] == 920_000
    assert republished["applied_growth_bps"] == 250

    baseline = read_schedule(scenario["schedules"]["DETACHED"]["id"])
    assert baseline["status"] == "SUPERSEDED"
    assert_instant_equals(baseline["superseded_at"], "2026-08-08T00:00:00Z", "superseded_at")

    detached_lease = read_lease(leases[0]["id"])
    assert detached_lease["base_rent_cents"] == 900_000
    assert detached_lease["gross_monthly_charge_cents"] == 927_000
    cottage_lease = read_lease(leases[2]["id"])
    assert cottage_lease["base_rent_cents"] == 800_000
    assert cottage_lease["gross_monthly_charge_cents"] == 823_000


def test_concession_program_stale_version_is_rejected_before_the_restricted_posture_gate(
    api, asset_manager_headers
):
    """A concession program carrying a community version that a rent schedule publication has
    already superseded is refused for staleness, even though the community's derived posture is
    RESTRICTED and would also have blocked the write.

    `POST /concession-programs` likewise requires `expected_community_version` matching the community's current `version`, and likewise fails with `ERR_STALE_COMMUNITY_VERSION` (HTTP 412) on any mismatch.
    The practical consequence worth internalising is that a posture freeze surfaces as a posture error rather than being masked by a downstream business rule, and that a stale `expected_community_version` surfaces before any state or posture reasoning is done.

    Design: Difficulty/priority_pair_validation_conflict/stale_community_version_rejected_before_the_restricted_posture_check
    """
    community = create_plat_approved_community(
        total_planned_units=2,
        product_mix={"DETACHED": 2, "COTTAGE": 0, "TOWNHOME": 0},
        concession_budget_cents=2_000_000,
        facility_commitment_cents=40_000_000,
        maintenance_tech_headcount=1,
    )
    community_id = community["id"]
    stale_version = community["version"]
    publish_schedule(
        community_id,
        product_type="DETACHED",
        asking_rent_cents=285_000,
        effective_from="2026-08-01T00:00:00Z",
    )
    phase = create_phase(community_id, planned_unit_count=2)
    start_construction(phase["id"])
    homesite = create_homesite(phase["id"], product_type="DETACHED", bedrooms=4, square_feet=2100)
    record_occupancy_certificate(homesite["id"])
    release_section(phase["id"], [homesite["id"]])
    create_amenity_phase(
        community_id,
        sequence_index=2,
        amenity_weight=100,
        construction_window_start="2026-09-01T00:00:00Z",
        construction_window_end="2026-12-01T00:00:00Z",
    )

    before = read_community(community_id)
    assert before["posture"] == "RESTRICTED"
    assert_ratio_equals(before["amenity_delivery_ratio"], 0.0000, "amenity_delivery_ratio")
    assert before["released_unit_count"] == 1
    assert before["version"] > stale_version

    response = api.create_concession_program(
        create_concession_program_payload(
            community_id,
            stale_version,
            program_code="CP-MG",
            tier="MODERATE",
            free_weeks=4,
            amortization_mode="STRAIGHT_LINE_NET_EFFECTIVE",
            eligible_product_types=["DETACHED"],
            restricted_posture_eligible=False,
            max_budget_cents=1_000_000,
        ),
        asset_manager_headers,
    )
    validate_error(response, ApiErrorId.ERR_STALE_COMMUNITY_VERSION.value)

    _, meta = validate_paginated(
        api.list_concession_programs(asset_manager_headers, {"community_id": community_id})
    )
    assert meta["total_count"] == 0
    assert read_community(community_id)["version"] == before["version"]


def test_concession_program_with_a_current_version_reveals_the_restricted_posture_refusal(
    api, asset_manager_headers
):
    """With the version freshly read the concurrency check passes, and the same program creation
    against the same RESTRICTED community is refused for its posture — the violation the
    staleness rejection had masked.

    Otherwise the posture is `RESTRICTED` if either of these two conditions holds: the community's `released_unit_count` is at least 1 while its `amenity_delivery_ratio` is strictly below 0.5000; or at least one phase of the community whose `kind` is `AMENITY` currently has `status` equal to `CONSTRUCTION_HALTED`.
    Creation is refused while the community's posture is `FROZEN` with `ERR_COMMUNITY_POSTURE_FROZEN`, and — uniquely among the leasing writes — also while it is `RESTRICTED`, with `ERR_COMMUNITY_POSTURE_RESTRICTED`; a community that has not delivered its amenities has no business writing new concession policy.

    Design: Difficulty/priority_pair_validation_conflict/stale_community_version_rejected_before_the_restricted_posture_check
    """
    community = create_plat_approved_community(
        total_planned_units=2,
        product_mix={"DETACHED": 2, "COTTAGE": 0, "TOWNHOME": 0},
        concession_budget_cents=2_000_000,
        facility_commitment_cents=40_000_000,
        maintenance_tech_headcount=1,
    )
    community_id = community["id"]
    publish_schedule(
        community_id,
        product_type="DETACHED",
        asking_rent_cents=285_000,
        effective_from="2026-08-01T00:00:00Z",
    )
    phase = create_phase(community_id, planned_unit_count=2)
    start_construction(phase["id"])
    homesite = create_homesite(phase["id"], product_type="DETACHED", bedrooms=4, square_feet=2100)
    record_occupancy_certificate(homesite["id"])
    release_section(phase["id"], [homesite["id"]])
    create_amenity_phase(
        community_id,
        sequence_index=2,
        amenity_weight=100,
        construction_window_start="2026-09-01T00:00:00Z",
        construction_window_end="2026-12-01T00:00:00Z",
    )

    current_version = community_version(community_id)
    assert read_community(community_id)["posture"] == "RESTRICTED"

    response = api.create_concession_program(
        create_concession_program_payload(
            community_id,
            current_version,
            program_code="CP-MG",
            tier="MODERATE",
            free_weeks=4,
            amortization_mode="STRAIGHT_LINE_NET_EFFECTIVE",
            eligible_product_types=["DETACHED"],
            restricted_posture_eligible=False,
            max_budget_cents=1_000_000,
        ),
        asset_manager_headers,
    )
    validate_error(response, ApiErrorId.ERR_COMMUNITY_POSTURE_RESTRICTED.value)

    _, meta = validate_paginated(
        api.list_concession_programs(asset_manager_headers, {"community_id": community_id})
    )
    assert meta["total_count"] == 0
    assert read_community(community_id)["version"] == current_version


def test_base_rent_ignores_a_superseded_schedule_dated_later_than_the_published_one(
    api, leasing_agent_headers
):
    """A retired schedule effective 2026-09-01 loses to the live schedule effective 2026-08-15
    even for a lease commencing 2026-09-15, so the lease prices off 270,000 cents and its fee
    follows from that base rent.

    The candidates are ranked by `effective_from` descending, and where two share the same `effective_from` the tie is broken by `created_at` descending.
    Schedules with `status` `SUPERSEDED` are excluded from the candidate set even when their `effective_from` is later than every published one — supersession, not date, decides eligibility.
    Step three computes `community_services_fee_cents` as `base_rent_cents` multiplied by the selected rate in basis points and divided by 10,000, rounded half up to whole cents, plus a flat product surcharge keyed on the home's `product_type`: 4,500 cents for `DETACHED`, 3,000 cents for `COTTAGE` and 2,000 cents for `TOWNHOME`.

    Design: Corner/calculations/base_rent_selection_ignores_a_superseded_schedule_with_a_later_effective_from
    """
    community = create_plat_approved_community(
        total_planned_units=4,
        product_mix={"DETACHED": 4, "COTTAGE": 0, "TOWNHOME": 0},
        concession_budget_cents=2_000_000,
        facility_commitment_cents=40_000_000,
        maintenance_tech_headcount=2,
    )
    community_id = community["id"]
    later_dated = publish_schedule(
        community_id,
        product_type="DETACHED",
        asking_rent_cents=900_000,
        effective_from="2026-09-01T00:00:00Z",
    )
    live = publish_schedule(
        community_id,
        product_type="DETACHED",
        asking_rent_cents=270_000,
        effective_from="2026-08-15T00:00:00Z",
    )
    phase = create_phase(community_id, planned_unit_count=2)
    start_construction(phase["id"])
    homesite = create_homesite(phase["id"], product_type="DETACHED", bedrooms=4, square_feet=2050)
    record_occupancy_certificate(homesite["id"])
    release_section(phase["id"], [homesite["id"]])
    household = create_household()

    retired = read_schedule(later_dated["id"])
    assert retired["status"] == "SUPERSEDED"
    assert retired["superseded_at"] is not None
    assert read_schedule(live["id"])["status"] == "PUBLISHED"

    response = api.create_lease(
        create_lease_payload(
            homesite["id"],
            household["id"],
            term_months=12,
            start_date="2026-09-15T00:00:00Z",
        ),
        leasing_agent_headers,
    )
    lease = validate_success(response, expected_status=201)

    assert lease["priced_by_schedule_id"] == live["id"]
    assert lease["priced_by_schedule_id"] != later_dated["id"]
    assert lease["base_rent_cents"] == 270_000
    assert lease["community_services_fee_cents"] == 12_600
    assert lease["gross_monthly_charge_cents"] == 282_600


def test_occupancy_ratio_of_one_third_is_stored_rounded_half_up_to_four_decimals(api):
    """One executed lease against three planned units gives an occupancy ratio with no exact
    decimal form, and the community reports exactly 0.3333 while staying short of the
    stabilization threshold.

    `occupancy_ratio` is `leased_unit_count` divided by `total_planned_units`, rounded half up to four decimal places.
    The two derived ratios on a community, `occupancy_ratio` and `amenity_delivery_ratio`, are held to four decimal places and rounded half up; so is an absorption review's `pacing_index`.
    Hop three, caused by hop two, moves the community's `lifecycle_status` `LEASE_UP → STABILIZED` if and only if the recomputed `occupancy_ratio` has reached 0.7500 or more — three quarters of the planned units occupied is the stabilization threshold.

    Design: Corner/calculations/occupancy_ratio_is_rounded_half_up_to_four_decimals
    """
    scenario = setup_released_community(
        homesite_count=1,
        product_type="DETACHED",
        total_planned_units=3,
        product_mix={"DETACHED": 3, "COTTAGE": 0, "TOWNHOME": 0},
        asking_rent_cents=285_000,
        phase_overrides={"planned_unit_count": 3},
        concession_budget_cents=2_000_000,
        facility_commitment_cents=40_000_000,
    )
    community_id = scenario["community"]["id"]
    household = create_household()
    lease = draft_lease(scenario["homesites"][0]["id"], household["id"])
    submit_lease(lease["id"])

    response = api.sign_lease(
        lease["id"],
        signature_payload(household["primary_applicant_name"]),
        make_household_headers(household["id"]),
    )
    validate_success(response, expected_status=201)

    community = read_community(community_id)
    assert community["leased_unit_count"] == 1
    assert community["total_planned_units"] == 3
    assert float(community["occupancy_ratio"]) == 0.3333, (
        f"occupancy_ratio must be exactly 0.3333, got {community['occupancy_ratio']!r}"
    )
    assert_ratio_equals(community["occupancy_ratio"], 0.3333, "occupancy_ratio")
    assert community["lifecycle_status"] == "LEASE_UP"
    assert community["facility_status"] == "ADVANCE_ELIGIBLE"


def test_absorption_review_window_must_be_ordered_and_already_elapsed(api, asset_manager_headers):
    """A seven-day window whose end is still in the future is refused, as is a reversed window,
    and advancing the logical clock past the same window makes the identical request succeed.

    The window must be well formed: `window_start` strictly before `window_end`, a span that is a positive whole multiple of seven days, and a `window_end` that is not after the current logical clock — you cannot review a period that has not finished.
    Any of those three failures is `ERR_INVALID_REVIEW_WINDOW`.
    Every rule in this specification that speaks of "now", "the current instant" or "already in the past" reads this logical clock.

    Design: Corner/validations/absorption_review_windows_must_be_ordered_and_already_elapsed
    """
    scenario = setup_released_community(
        homesite_count=1,
        product_type="DETACHED",
        total_planned_units=4,
        product_mix={"DETACHED": 4, "COTTAGE": 0, "TOWNHOME": 0},
        asking_rent_cents=285_000,
        phase_overrides={"planned_unit_count": 4},
        concession_budget_cents=1_000_000,
        facility_commitment_cents=25_000_000,
    )
    community_id = scenario["community"]["id"]

    future_window = api.create_absorption_review(
        community_id,
        absorption_review_payload(
            product_type="DETACHED",
            window_start="2026-08-01T00:00:00Z",
            window_end="2026-08-08T00:00:00Z",
            planned_absorption_units=2,
        ),
        asset_manager_headers,
    )
    validate_error(future_window, ApiErrorId.ERR_INVALID_REVIEW_WINDOW.value)

    reversed_window = api.create_absorption_review(
        community_id,
        absorption_review_payload(
            product_type="DETACHED",
            window_start="2026-07-29T00:00:00Z",
            window_end="2026-07-22T00:00:00Z",
            planned_absorption_units=2,
        ),
        asset_manager_headers,
    )
    validate_error(reversed_window, ApiErrorId.ERR_INVALID_REVIEW_WINDOW.value)

    _, meta_before = validate_paginated(
        api.list_absorption_reviews(asset_manager_headers, {"community_id": community_id})
    )
    assert meta_before["total_count"] == 0

    set_clock("2026-08-15T00:00:00Z")
    accepted = api.create_absorption_review(
        community_id,
        absorption_review_payload(
            product_type="DETACHED",
            window_start="2026-08-01T00:00:00Z",
            window_end="2026-08-08T00:00:00Z",
            planned_absorption_units=2,
        ),
        asset_manager_headers,
    )
    review = validate_success(accepted, expected_status=201)
    assert review["actual_absorption_units"] == 0
    assert review["available_supply_units"] == 1
    assert review["posture_at_review"] == "OPEN"

    _, meta_after = validate_paginated(
        api.list_absorption_reviews(
            asset_manager_headers,
            {"community_id": community_id, "product_type": "DETACHED"},
        )
    )
    assert meta_after["total_count"] == 1


def test_logical_clock_refuses_a_rewind_and_a_replay_of_the_stored_instant(
    api, developer_principal_headers, property_manager_headers
):
    """An earlier instant and a replay of the stored instant are both refused, and a one-second
    advance driven by another operator role then succeeds from the untouched stored value.

    The clock is advanced by `POST /_clock/set_current_utc`, which takes a single field `current_utc` and returns the new clock value in a `current_utc` response field with HTTP 200.
    Any role may drive it.
    The clock may only move forward: a `current_utc` at or before the stored value is rejected with `ERR_CLOCK_REWIND` (HTTP 409).

    Design: Corner/validations/the_logical_clock_cannot_be_rewound_or_replayed
    """
    advanced = validate_success(
        api.set_clock(clock_payload("2026-08-05T00:00:00Z"), developer_principal_headers),
        expected_status=200,
    )
    assert_instant_equals(advanced["current_utc"], "2026-08-05T00:00:00Z", "current_utc")

    rewind = api.set_clock(clock_payload("2026-08-04T00:00:00Z"), developer_principal_headers)
    validate_error(rewind, ApiErrorId.ERR_CLOCK_REWIND.value)

    replay = api.set_clock(clock_payload("2026-08-05T00:00:00Z"), developer_principal_headers)
    validate_error(replay, ApiErrorId.ERR_CLOCK_REWIND.value)

    forward = validate_success(
        api.set_clock(clock_payload("2026-08-05T00:00:01Z"), property_manager_headers),
        expected_status=200,
    )
    assert_instant_equals(forward["current_utc"], "2026-08-05T00:00:01Z", "current_utc")


def test_absorption_indexed_publication_needs_a_baseline_then_a_review(api, asset_manager_headers):
    """An indexed publication reports a missing baseline schedule first and a missing absorption
    review second, and once both exist the review's negative recommendation moves the rent down.

    If no schedule for that pair exists at all, the publication fails with `ERR_RENT_SCHEDULE_NOT_FOUND`.
    The growth figure comes from the most recent absorption review for the same community and product type, ranked by `window_end` descending and then by `created_at` descending; if no such review exists, the publication fails with `ERR_ABSORPTION_REVIEW_NOT_FOUND`.
    If `actual_absorption_units` is zero, `pacing_index` is exactly 0.0000 and no division is attempted at all.
    Below 0.8000 the tier is `AGGRESSIVE` and the recommendation is negative 150 basis points.

    Design: Corner/errors/absorption_indexed_publication_without_a_baseline_or_a_review_is_rejected
    """
    community = create_plat_approved_community(
        total_planned_units=4,
        product_mix={"DETACHED": 4, "COTTAGE": 0, "TOWNHOME": 0},
        concession_budget_cents=1_000_000,
        facility_commitment_cents=25_000_000,
        maintenance_tech_headcount=2,
    )
    community_id = community["id"]

    without_baseline = api.publish_market_rent_schedule(
        indexed_schedule_payload(
            community_id,
            community_version(community_id),
            product_type="DETACHED",
            effective_from="2026-09-01T00:00:00Z",
        ),
        asset_manager_headers,
    )
    validate_error(without_baseline, ApiErrorId.ERR_RENT_SCHEDULE_NOT_FOUND.value)

    manual = validate_success(
        api.publish_market_rent_schedule(
            publish_schedule_payload(
                community_id,
                community_version(community_id),
                product_type="DETACHED",
                effective_from="2026-08-01T00:00:00Z",
                repricing_mode="MANUAL",
                asking_rent_cents=285_000,
            ),
            asset_manager_headers,
        ),
        expected_status=201,
    )
    assert manual["asking_rent_cents"] == 285_000
    assert manual["applied_growth_bps"] == 0
    assert manual["status"] == "PUBLISHED"

    without_review = api.publish_market_rent_schedule(
        indexed_schedule_payload(
            community_id,
            community_version(community_id),
            product_type="DETACHED",
            effective_from="2026-09-01T00:00:00Z",
        ),
        asset_manager_headers,
    )
    validate_error(without_review, ApiErrorId.ERR_ABSORPTION_REVIEW_NOT_FOUND.value)

    set_clock("2026-08-15T00:00:00Z")
    review = create_absorption_review(
        community_id,
        product_type="DETACHED",
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-08T00:00:00Z",
        planned_absorption_units=3,
    )
    assert review["actual_absorption_units"] == 0
    assert_ratio_equals(review["pacing_index"], 0.0000, "pacing_index")
    assert review["concession_tier"] == "AGGRESSIVE"
    assert review["recommended_growth_bps"] == -150

    indexed = validate_success(
        api.publish_market_rent_schedule(
            indexed_schedule_payload(
                community_id,
                community_version(community_id),
                product_type="DETACHED",
                effective_from="2026-09-01T00:00:00Z",
            ),
            asset_manager_headers,
        ),
        expected_status=201,
    )
    assert indexed["applied_growth_bps"] == -150
    assert indexed["asking_rent_cents"] == 280_725

    baseline = read_schedule(manual["id"])
    assert baseline["status"] == "SUPERSEDED"
    assert_instant_equals(baseline["superseded_at"], "2026-08-15T00:00:00Z", "superseded_at")


def test_absorption_indexed_publication_off_a_superseded_baseline_is_refused(
    api, asset_manager_headers
):
    """When an out-of-order publication leaves the latest-dated schedule retired, an indexed
    repricing refuses to index off it rather than quietly repricing from the live earlier-dated
    schedule.

    The baseline is the schedule for the same community and product type ranked by `effective_from` descending and, where two share the same `effective_from`, by `created_at` descending.
    If the baseline that wins that ranking has `status` `SUPERSEDED` rather than `PUBLISHED` — which can happen when an out-of-order manual publication leaves the latest-dated schedule retired while an earlier-dated one is live — the service refuses to index off a stale baseline and returns `ERR_SCHEDULE_ALREADY_SUPERSEDED`.

    Design: Corner/errors/absorption_indexed_publication_off_a_superseded_baseline_is_rejected
    """
    community = create_plat_approved_community(
        total_planned_units=4,
        product_mix={"DETACHED": 4, "COTTAGE": 0, "TOWNHOME": 0},
        concession_budget_cents=1_000_000,
        facility_commitment_cents=25_000_000,
        maintenance_tech_headcount=2,
    )
    community_id = community["id"]
    later_dated = publish_schedule(
        community_id,
        product_type="DETACHED",
        asking_rent_cents=900_000,
        effective_from="2026-09-01T00:00:00Z",
    )
    earlier_dated = publish_schedule(
        community_id,
        product_type="DETACHED",
        asking_rent_cents=270_000,
        effective_from="2026-08-01T00:00:00Z",
    )
    set_clock("2026-08-15T00:00:00Z")
    create_absorption_review(
        community_id,
        product_type="DETACHED",
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-08T00:00:00Z",
        planned_absorption_units=3,
    )
    version_before = community_version(community_id)

    assert read_schedule(later_dated["id"])["status"] == "SUPERSEDED"
    assert read_schedule(earlier_dated["id"])["status"] == "PUBLISHED"

    response = api.publish_market_rent_schedule(
        indexed_schedule_payload(
            community_id,
            version_before,
            product_type="DETACHED",
            effective_from="2026-10-01T00:00:00Z",
        ),
        asset_manager_headers,
    )
    validate_error(response, ApiErrorId.ERR_SCHEDULE_ALREADY_SUPERSEDED.value)

    _, meta = validate_paginated(
        api.list_market_rent_schedules(
            asset_manager_headers,
            {"community_id": community_id, "product_type": "DETACHED"},
        )
    )
    assert meta["total_count"] == 2
    assert read_community(community_id)["version"] == version_before


def test_rent_schedule_publication_carrying_a_stale_community_version_is_rejected(
    api, asset_manager_headers
):
    """A version invalidated by a publication on the other product type is stale for the next
    publication too, because pricing writes bump the shared community record; the retry with the
    refreshed version then supersedes the prior schedule for its own product type only.

    `POST /market-rent-schedules` must carry `expected_community_version` as a required, non-optional field holding the `version` the client last observed on the target community.
    If that value does not equal the community's current `version`, the publication is rejected with `ERR_STALE_COMMUNITY_VERSION` (HTTP 412).
    On success the new schedule is stored with `status` `PUBLISHED`, `superseded_at` null and `published_by_user_id` set from the acting `X-User-ID`; the community's previously `PUBLISHED` schedule for that same community-and-product-type pair moves to `status` `SUPERSEDED` with `superseded_at` stamped at the current logical clock; and the community's `version` increments.

    Design: Corner/cross_cutting_complexity_layers/a_rent_schedule_publication_carrying_a_stale_community_version_is_rejected
    """
    community = create_plat_approved_community(
        total_planned_units=4,
        product_mix={"DETACHED": 3, "COTTAGE": 1, "TOWNHOME": 0},
        concession_budget_cents=1_000_000,
        facility_commitment_cents=25_000_000,
        maintenance_tech_headcount=2,
    )
    community_id = community["id"]
    detached = publish_schedule(
        community_id,
        product_type="DETACHED",
        asking_rent_cents=285_000,
        effective_from="2026-08-01T00:00:00Z",
    )
    observed_version = community_version(community_id)

    cottage = validate_success(
        api.publish_market_rent_schedule(
            publish_schedule_payload(
                community_id,
                observed_version,
                product_type="COTTAGE",
                effective_from="2026-08-01T00:00:00Z",
                repricing_mode="MANUAL",
                asking_rent_cents=219_000,
            ),
            make_asset_manager_headers(ASSET_MANAGER_ALT_USER_ID),
        ),
        expected_status=201,
    )
    assert read_community(community_id)["version"] == observed_version + 1

    stale = api.publish_market_rent_schedule(
        publish_schedule_payload(
            community_id,
            observed_version,
            product_type="DETACHED",
            effective_from="2026-09-01T00:00:00Z",
            repricing_mode="MANUAL",
            asking_rent_cents=292_000,
        ),
        asset_manager_headers,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_COMMUNITY_VERSION.value)

    untouched = read_schedule(detached["id"])
    assert untouched["status"] == "PUBLISHED"
    assert untouched["superseded_at"] is None
    refreshed_version = community_version(community_id)
    assert refreshed_version == observed_version + 1

    retried = validate_success(
        api.publish_market_rent_schedule(
            publish_schedule_payload(
                community_id,
                refreshed_version,
                product_type="DETACHED",
                effective_from="2026-09-01T00:00:00Z",
                repricing_mode="MANUAL",
                asking_rent_cents=292_000,
            ),
            asset_manager_headers,
        ),
        expected_status=201,
    )
    assert retried["status"] == "PUBLISHED"
    assert retried["superseded_at"] is None

    superseded = read_schedule(detached["id"])
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["superseded_at"] is not None
    assert read_schedule(cottage["id"])["status"] == "PUBLISHED"
    assert read_community(community_id)["version"] == refreshed_version + 1
