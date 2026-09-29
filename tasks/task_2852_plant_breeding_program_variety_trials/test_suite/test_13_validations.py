"""
The validation ladder in the small: ownership rules that fire after the rows have
all resolved, four temporal gates reading four different calendars, uniqueness
scopes that differ per code, aggregate budgets consumed from two directions, and
a whitelist that only an approved package can widen.
"""

from test_helpers import (
    AGRONOMIST_HEADERS,
    DIRECTOR_HEADERS,
    PLANNER_HEADERS,
    REGULATORY_APPROVER_HEADERS,
    REGULATORY_APPROVER_USER_ID,
    REGULATORY_HEADERS,
    SCIENTIST_HEADERS,
    AgreementStatus,
    ApiErrorId,
    EntryStatus,
    StewardshipStatus,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


def _two_programmes_each_with_its_own_objective(api):
    """P1 North Central and P2 Southern, the second already holding line SY-2001."""
    p1, obj1 = fixtures.program_with_objective(api)
    p2, obj2 = fixtures.program_with_objective(
        api,
        program_overrides={
            "name": "Soy Southern",
            "market_zone": "SOUTHERN",
            "total_plot_budget": 3000,
            "total_budget_usd": 900000.00,
        },
        objective_overrides={
            "market_segment": "MG5_SOUTH",
            "target_yield_kg_per_ha": 9000.00,
            "required_disease_resistances": ["RUST"],
            "min_resistance_score": 5,
            "quality_trait_specs": {"PROTEIN_MIN": 12.5},
            "min_advancement_index": 80.00,
        },
    )
    foreign = fixtures.create_line(
        api, p2, obj2, designation="SY-2001", seed_inventory_g=200000
    )
    return {"p1": p1, "obj1": obj1, "p2": p2, "obj2": obj2, "foreign": foreign["id"]}


def test_an_objective_and_a_parent_from_another_programme_are_both_refused(api):
    """
    Every referenced row exists, so the path and body-key rungs are satisfied and
    the refusals can only be about ownership; the two surfaces carry two different
    codes and neither of them touched the programme's census.

    PRD 2.7: "**Objective belongs to the programme.** The referenced
    `BreedingObjective`'s `program_id` equals the line's `program_id` — otherwise
    `ERR_OBJECTIVE_PROGRAM_MISMATCH` (422). Applies to direct breeding line
    registration and to progeny registration."
    PRD 2.7: "**Parents belong to the programme.** `female_parent_line_id` and
    `male_parent_line_id` both belong to the same `program_id` as the new line, and
    a backcross `donor_line_id` belongs to the recurrent line's programme —
    otherwise `ERR_PARENT_LINE_PROGRAM_MISMATCH` (422). Applies to progeny
    registration, direct breeding line registration, and backcross project
    creation."
    PRD 3.1: "Two census counters complete the picture: `active_line_count` counts
    the programme's breeding lines whose `pipeline_stage` is neither `DISCARDED`
    nor `COMMERCIAL`, and `pre_commercial_units_bags` sums `planned_units_bags`
    over the seed increase lots of the programme's lines whose `status` is
    `RESERVED`, `IN_PRODUCTION` or `COMPLETED`, excluding lots that are `ON_HOLD`
    or `CANCELLED`."

    Design: Corner/validations/cross_program_references_are_refused_on_every_surface
    """
    net = _two_programmes_each_with_its_own_objective(api)

    validate_error(
        api.create_line(
            factories.line_payload(net["p1"], net["obj2"], designation="SX-1001"),
            SCIENTIST_HEADERS,
        ),
        ApiErrorId.OBJECTIVE_PROGRAM_MISMATCH,
        422,
    )
    validate_error(
        api.create_line(
            factories.line_payload(
                net["p1"], net["obj1"], designation="SX-1001",
                female_parent_line_id=net["foreign"],
            ),
            SCIENTIST_HEADERS,
        ),
        ApiErrorId.PARENT_LINE_PROGRAM_MISMATCH,
        422,
    )

    good = fixtures.create_line(
        api, net["p1"], net["obj1"], designation="SX-1001"
    )
    program = validate_success(api.get_program(net["p1"], DIRECTOR_HEADERS))
    assert program["active_line_count"] == 1

    validate_error(
        api.create_backcross(
            factories.backcross_payload(
                good["id"], net["foreign"], target_trait_code="RUST"
            ),
            SCIENTIST_HEADERS,
        ),
        ApiErrorId.PARENT_LINE_PROGRAM_MISMATCH,
        422,
    )
    _rows, meta = validate_paginated(
        api.list_backcrosses(SCIENTIST_HEADERS, {"recurrent_line_id": good["id"]})
    )
    assert meta["total_count"] == 0


def test_four_temporal_gates_each_read_their_own_calendar(api):
    """
    A future sow date still fails the block's own month set, an admissible month
    still fails the clock, an entry window is judged against its site's season, and
    moving the clock forward invalidates an `effective_from` that was legal a
    moment earlier — which is what proves the check is live rather than pinned.

    PRD 3.3: "The distinction between the two nursery types is seasonal rather
    than cosmetic: a `WINTER` block is a counter-season off-shore nursery and
    admits sowing only in October, November, December, January or February, while a
    `SUMMER` block is a home-season nursery and admits sowing only in April, May,
    June, July or August. A sowing month outside the block's admissible set is
    refused with `ERR_NURSERY_SEASON_MISMATCH`."
    PRD 3.3: "the `sow_date` may not be earlier than the logical clock's current
    date, or `ERR_SOW_DATE_IN_PAST` is returned"
    PRD 3.5: "Next the planting window must sit inside the site's season:
    `planting_window_start` on or after `season_start_date`, `planting_window_end`
    on or before `season_end_date`, and `planting_window_end` on or after
    `planting_window_start`, or `ERR_ENTRY_WINDOW_OUTSIDE_SEASON` is returned."
    PRD 3.9: "The window is checked against the logical clock: `effective_from`
    must be on or after the clock's current date and `effective_to` must be
    strictly later than `effective_from`, or the request is refused with
    `ERR_AGREEMENT_DATES_INVALID`."

    Design: Corner/validations/temporal_gates_read_the_logical_clock_and_the_owning_calendar
    """
    program_id, objective_id = fixtures.program_with_objective(api)
    line = fixtures.create_line(api, program_id, objective_id, designation="SX-1001")
    summer = fixtures.create_nursery_block(
        api, block_code="NB-SUM", nursery_type="SUMMER",
        location_code="US_IL_CHAMPAIGN",
    )
    winter = fixtures.create_nursery_block(api, block_code="NB-WIN")
    site = fixtures.create_site(api, site_code="TM1")
    series = fixtures.create_series(
        api, program_id, replication_count=3, min_locations=1
    )

    # September is in the future but outside the WINTER month set {10,11,12,1,2}.
    validate_error(
        api.create_planting(
            factories.planting_payload(
                winter["id"], line["id"], sow_date="2026-09-10",
                expected_harvest_date="2027-01-20", plot_count=20,
            ),
            SCIENTIST_HEADERS,
        ),
        ApiErrorId.NURSERY_SEASON_MISMATCH,
        422,
    )
    # July is an admissible SUMMER month; the clock stands at 2026-08-01.
    validate_error(
        api.create_planting(
            factories.planting_payload(
                summer["id"], line["id"], sow_date="2026-07-31",
                expected_harvest_date="2026-11-20", plot_count=20,
            ),
            SCIENTIST_HEADERS,
        ),
        ApiErrorId.SOW_DATE_IN_PAST,
        422,
    )
    good = fixtures.create_planting(
        api, summer["id"], line["id"], sow_date="2026-08-05",
        expected_harvest_date="2026-11-20", plot_count=20,
    )
    assert good["occupancy_end_date"] == "2026-12-04"

    validate_error(
        api.create_entry(
            series["id"],
            factories.entry_payload(
                line["id"], site["id"], plot_count=9,
                planting_window_start="2027-02-15",
                planting_window_end="2027-06-30",
            ),
            AGRONOMIST_HEADERS,
        ),
        ApiErrorId.ENTRY_WINDOW_OUTSIDE_SEASON,
        422,
    )

    validate_error(
        api.create_agreement(
            line["id"],
            factories.agreement_payload(
                regulatory_dossier_ref="DOS-1", grower_agreement_ref="GA-1",
                effective_from="2026-09-01", effective_to="2026-08-15",
            ),
            REGULATORY_HEADERS,
        ),
        ApiErrorId.AGREEMENT_DATES_INVALID,
        422,
    )

    validate_success(api.set_clock("2026-12-01T00:00:00Z", DIRECTOR_HEADERS))
    validate_error(
        api.create_agreement(
            line["id"],
            factories.agreement_payload(
                regulatory_dossier_ref="DOS-1", grower_agreement_ref="GA-1",
                effective_from="2026-09-01", effective_to="2029-09-01",
            ),
            REGULATORY_HEADERS,
        ),
        ApiErrorId.AGREEMENT_DATES_INVALID,
        422,
    )
    agreement = validate_success(
        api.create_agreement(
            line["id"],
            factories.agreement_payload(
                regulatory_dossier_ref="DOS-1", grower_agreement_ref="GA-1",
                effective_from="2026-12-01", effective_to="2029-09-01",
            ),
            REGULATORY_HEADERS,
        ),
        201,
    )
    assert agreement["status"] == AgreementStatus.DRAFT
    assert validate_success(api.get_line(line["id"], SCIENTIST_HEADERS))[
        "stewardship_status"
    ] == StewardshipStatus.PENDING


def test_the_three_code_scopes_differ_and_a_withdrawal_frees_the_entry_triple(api):
    """
    A designation is unique only inside its programme while a block code and a site
    code are unique everywhere, and the entry triple's uniqueness is scoped to the
    three live statuses — so withdrawing an entry hands the same combination back.

    PRD 2.7: "**Code uniqueness.** `block_code` is unique across all nursery
    blocks, `site_code` is unique across all trial sites, and `designation` is
    unique within its `program_id` — otherwise `ERR_DUPLICATE_CODE` (409). Applies
    to nursery block registration, trial site registration, direct breeding line
    registration, and progeny registration."
    PRD 3.5: "Then the same line may not already be entered at the same site in the
    same series — any existing entry with that same combination of
    `trial_series_id`, `line_id` and `trial_site_id` in `status` `ENTERED`,
    `PLANTED` or `HARVESTED` makes the request a duplicate and yields
    `ERR_DUPLICATE_TRIAL_ENTRY`."
    PRD 3.5: "Then `plot_count` must be an exact multiple of the series'
    `replication_count`, since every replication needs the same plot allotment, or
    `ERR_PLOT_COUNT_NOT_DIVISIBLE` is returned."
    PRD 3.6: "**Withdrawal** applies to an entry that is `ENTERED` or `PLANTED`,
    whose series is not `CLOSED`: the agronomist supplies a `withdrawal_reason`, the
    entry moves to `WITHDRAWN`, the programme's `committed_plot_count` falls by the
    entry's `plot_count` with `plot_budget_remaining` recomputed, the site's
    `peak_committed_plot_count`, `available_plot_count` and `capacity_posture` are
    re-derived over the remaining active entries, and the series' `entry_count`
    falls by one with `location_count` re-derived — the plots were never used, so
    the location no longer counts."

    Design: Corner/validations/uniqueness_scopes_differ_per_code_and_a_withdrawal_frees_the_triple
    """
    net = _two_programmes_each_with_its_own_objective(api)
    line_a = fixtures.create_line(
        api, net["p1"], net["obj1"], designation="SX-1001"
    )
    fixtures.create_nursery_block(api, block_code="NB-U1")
    site = fixtures.create_site(api, site_code="US1")
    series = fixtures.create_series(
        api, net["p1"], replication_count=4, min_locations=1
    )

    validate_error(
        api.create_line(
            factories.line_payload(
                net["p1"], net["obj1"], designation="SX-1001",
                seed_inventory_g=100000,
            ),
            SCIENTIST_HEADERS,
        ),
        ApiErrorId.DUPLICATE_CODE,
        409,
    )
    twin = fixtures.create_line(
        api, net["p2"], net["obj2"], designation="SX-1001", seed_inventory_g=100000
    )
    assert twin["designation"] == "SX-1001"
    p2 = validate_success(api.get_program(net["p2"], DIRECTOR_HEADERS))
    # SY-2001 plus the twin designation the second programme is entitled to hold.
    assert p2["active_line_count"] == 2

    validate_error(
        api.create_nursery_block(
            factories.nursery_block_payload(
                block_code="NB-U1", nursery_type="SUMMER",
                location_code="US_IL_CHAMPAIGN", plot_count=100,
                fallow_buffer_days=7,
            ),
            SCIENTIST_HEADERS,
        ),
        ApiErrorId.DUPLICATE_CODE,
        409,
    )
    validate_error(
        api.create_site(
            factories.site_payload(
                site_code="US1", environment_class="DROUGHT_STRESS",
                total_plot_capacity=100, plot_cost_usd=40.00,
            ),
            AGRONOMIST_HEADERS,
        ),
        ApiErrorId.DUPLICATE_CODE,
        409,
    )

    validate_error(
        api.create_entry(
            series["id"],
            factories.entry_payload(line_a["id"], site["id"], plot_count=10),
            AGRONOMIST_HEADERS,
        ),
        ApiErrorId.PLOT_COUNT_NOT_DIVISIBLE,
        422,
    )
    first = fixtures.create_entry(
        api, series["id"], line_a["id"], site["id"], plot_count=12
    )
    validate_error(
        api.create_entry(
            series["id"],
            factories.entry_payload(line_a["id"], site["id"], plot_count=12),
            AGRONOMIST_HEADERS,
        ),
        ApiErrorId.DUPLICATE_TRIAL_ENTRY,
        409,
    )

    withdrawn = validate_success(
        api.withdraw_entry(
            first["id"],
            factories.withdraw_payload("re-siting to the irrigated block"),
            AGRONOMIST_HEADERS,
        )
    )
    assert withdrawn["status"] == EntryStatus.WITHDRAWN
    second = fixtures.create_entry(
        api, series["id"], line_a["id"], site["id"], plot_count=12
    )
    assert second["id"] != first["id"]
    assert validate_success(api.get_series(series["id"], AGRONOMIST_HEADERS))[
        "entry_count"
    ] == 1
    assert validate_success(api.get_site(site["id"], AGRONOMIST_HEADERS))[
        "peak_committed_plot_count"
    ] == 12


def test_one_plot_budget_is_drawn_down_from_two_surfaces_and_the_block_gate_wins(api):
    """
    Nursery plantings and trial entries consume the same programme counter, so each
    request is individually plausible and only the running total refuses; and a
    planting that breaks both the block's physical size and the programme budget
    must report the block.

    PRD 3.3: "Four rules guard the request beyond the shape checks: the requested
    `plot_count` may not exceed the block's physical `plot_count`, or
    `ERR_BLOCK_PLOT_COUNT_EXCEEDED` is returned; the `sow_date` may not be earlier
    than the logical clock's current date, or `ERR_SOW_DATE_IN_PAST` is returned;
    the committed plots may not exceed the programme's `plot_budget_remaining`, or
    `ERR_PROGRAM_PLOT_BUDGET_EXCEEDED` is returned; and the block must actually be
    free for the whole interval."
    PRD 3.1: "`committed_plot_count` is a conserved quantity summed over exactly
    three sources and no others: the `plot_count` of every trial entry whose series
    belongs to this programme and whose `status` is `ENTERED`, `PLANTED` or
    `HARVESTED`; the `plot_count` of every nursery planting whose line belongs to
    this programme and whose `status` is `SCHEDULED` or `PLANTED`; and the
    `granted_plots` of every advancement decision whose line belongs to this
    programme, whose `decision` is `ADVANCE`, whose `is_superseded` is false, and
    whose line's `pipeline_stage` is not `DISCARDED`."
    PRD 3.5: "The last gate is fiscal: the entry's `plot_count` must fit inside the
    programme's `plot_budget_remaining`, or `ERR_PROGRAM_PLOT_BUDGET_EXCEEDED` is
    returned."

    Design: Corner/validations/plot_budget_is_aggregate_and_the_block_gate_outranks_it
    """
    program_id, objective_id = fixtures.program_with_objective(
        api, program_overrides={"total_plot_budget": 60}
    )
    lines = [
        fixtures.create_line(
            api, program_id, objective_id, designation=code, seed_inventory_g=grams
        )
        for code, grams in (
            ("SX-1001", 500000), ("SX-1002", 400000), ("SX-1003", 300000)
        )
    ]
    block = fixtures.create_nursery_block(
        api, block_code="NB-AG1", plot_count=50
    )
    site = fixtures.create_site(api, site_code="AG1")
    series = fixtures.create_series(
        api, program_id, replication_count=2, min_locations=1
    )

    # 61 exceeds the block's 50 plots and the programme's whole 60-plot budget.
    validate_error(
        api.create_planting(
            factories.planting_payload(
                block["id"], lines[0]["id"], sow_date="2026-10-05",
                expected_harvest_date="2027-02-10", plot_count=61,
            ),
            SCIENTIST_HEADERS,
        ),
        ApiErrorId.BLOCK_PLOT_COUNT_EXCEEDED,
        422,
    )
    fixtures.create_planting(
        api, block["id"], lines[0]["id"], sow_date="2026-10-05",
        expected_harvest_date="2027-02-10", plot_count=30,
    )
    program = validate_success(api.get_program(program_id, DIRECTOR_HEADERS))
    assert program["committed_plot_count"] == 30
    assert program["plot_budget_remaining"] == 30

    fixtures.create_entry(
        api, series["id"], lines[0]["id"], site["id"], plot_count=20
    )
    program = validate_success(api.get_program(program_id, DIRECTOR_HEADERS))
    assert program["committed_plot_count"] == 50
    assert program["plot_budget_remaining"] == 10

    validate_error(
        api.create_entry(
            series["id"],
            factories.entry_payload(lines[1]["id"], site["id"], plot_count=20),
            AGRONOMIST_HEADERS,
        ),
        ApiErrorId.PROGRAM_PLOT_BUDGET_EXCEEDED,
        409,
    )
    # The exact-fit case is admitted; the budget closes at zero.
    fixtures.create_entry(
        api, series["id"], lines[1]["id"], site["id"], plot_count=10
    )
    program = validate_success(api.get_program(program_id, DIRECTOR_HEADERS))
    assert program["committed_plot_count"] == 60
    assert program["plot_budget_remaining"] == 0

    validate_error(
        api.create_entry(
            series["id"],
            factories.entry_payload(lines[2]["id"], site["id"], plot_count=2),
            AGRONOMIST_HEADERS,
        ),
        ApiErrorId.PROGRAM_PLOT_BUDGET_EXCEEDED,
        409,
    )
    report = validate_success(api.get_pipeline_report(program_id, DIRECTOR_HEADERS))
    assert report["committed_plot_count"] == 60
    assert report["plot_budget_remaining"] == 0
    assert validate_success(api.get_site(site["id"], AGRONOMIST_HEADERS))[
        "peak_committed_plot_count"
    ] == 30


def test_only_one_package_may_be_live_and_its_markets_gate_every_lot(api):
    """
    A second package is refused while the first is merely a DRAFT, and once the
    first is approved its `approved_markets` array — not the approval itself — is
    what decides which market a lot may be reserved for.

    PRD 3.9: "The line must not be `DISCARDED`, and it must not already hold an
    agreement whose `status` is `DRAFT`, `SUBMITTED`, `CHANGES_REQUESTED` or
    `APPROVED` — a second live package on the same line is refused with
    `ERR_AGREEMENT_ALREADY_ACTIVE`."
    PRD 3.9: "An `APPROVE` outcome moves the agreement `SUBMITTED → APPROVED`,
    stamps `approved_by_user_id` with the approver's `X-User-ID`, and flips the
    line's `stewardship_status` to `APPROVED` with the line's `version`
    incrementing."
    PRD 3.9: "The `target_market` must additionally appear in the
    `approved_markets` array of the line's `APPROVED` agreement, or the reservation
    is refused with `ERR_MARKET_NOT_IN_AGREEMENT`."
    PRD 3.9: "For each element of `market_allocations` the server inflates that
    market's `demand_kg` by a seed loss allowance of eight percent — multiplying it
    by one plus 0.08 — divides the result by the 25-kilogram commercial bag size,
    and rounds **that quotient up** to the next whole bag."

    Design: Corner/validations/seed_lot_market_must_appear_in_the_lines_approved_agreement
    """
    program_id, objective_id = fixtures.program_with_objective(api)
    line = fixtures.create_line(api, program_id, objective_id, designation="SX-1001")
    agreement = validate_success(
        api.create_agreement(
            line["id"], factories.agreement_payload(), REGULATORY_HEADERS
        ),
        201,
    )

    validate_error(
        api.create_agreement(
            line["id"],
            factories.agreement_payload(
                approved_markets=["CANADA_EAST"],
                regulatory_dossier_ref="DOS-2852-02",
                grower_agreement_ref="GA-2852-02",
            ),
            REGULATORY_HEADERS,
        ),
        ApiErrorId.AGREEMENT_ALREADY_ACTIVE,
        409,
    )

    validate_success(api.submit_agreement(agreement["id"], REGULATORY_HEADERS))
    approved = validate_success(
        api.review_agreement(
            agreement["id"], factories.review_payload(), REGULATORY_APPROVER_HEADERS
        )
    )
    assert approved["status"] == AgreementStatus.APPROVED
    assert approved["approved_by_user_id"] == REGULATORY_APPROVER_USER_ID
    assert validate_success(api.get_line(line["id"], PLANNER_HEADERS))[
        "stewardship_status"
    ] == StewardshipStatus.APPROVED

    validate_error(
        api.create_lot(
            factories.lot_payload(
                line["id"], "CANADA_EAST", [factories.allocation("CANADA_EAST", 100)]
            ),
            PLANNER_HEADERS,
        ),
        ApiErrorId.MARKET_NOT_IN_AGREEMENT,
        422,
    )
    lot = validate_success(
        api.create_lot(
            factories.lot_payload(
                line["id"], "US_CORNBELT", [factories.allocation("US_CORNBELT", 100)]
            ),
            PLANNER_HEADERS,
        ),
        201,
    )
    # 100 kg inflated to 108 kg needs the ceiling of 4.32 bags.
    assert lot["planned_units_bags"] == 5
    assert lot["allocated_seed_g"] == 3125

    after = validate_success(api.get_line(line["id"], PLANNER_HEADERS))
    assert after["seed_inventory_g"] == 496875
    assert after["reserved_seed_g"] == 3125
    assert after["planned_launch_units_bags"] == 5
    program = validate_success(api.get_program(program_id, DIRECTOR_HEADERS))
    assert program["pre_commercial_units_bags"] == 5
    _rows, meta = validate_paginated(api.list_line_lots(line["id"], PLANNER_HEADERS))
    assert meta["total_count"] == 1
