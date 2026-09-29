"""
Two shared resources with deliberately opposite interval conventions: a nursery
block reserved on a half-open interval that includes a fallow buffer, and a trial
site swept over closed windows where a shared boundary day still competes.
"""

from test_helpers import (
    AGRONOMIST_HEADERS,
    DIRECTOR_HEADERS,
    SCIENTIST_HEADERS,
    ApiErrorId,
    CapacityPosture,
    EntryStatus,
    OccupancyStatus,
    PlantingStatus,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


def _block_holding_one_scheduled_planting(api):
    """
    WINTER block NB-OC1 with a 14-day fallow buffer holding one SCHEDULED planting
    sown 2026-10-05 with an expected harvest on 2027-02-10.
    """
    program_id, objective_id = fixtures.program_with_objective(
        api, program_overrides={"name": "Soy Nursery"}
    )
    line = fixtures.create_line(
        api,
        program_id,
        objective_id,
        designation="SX-1101",
        generation_number=3,
        seed_inventory_g=100000,
    )
    block = fixtures.create_nursery_block(
        api, block_code="NB-OC1", plot_count=200, fallow_buffer_days=14
    )
    first = fixtures.create_planting(
        api,
        block["id"],
        line["id"],
        sow_date="2026-10-05",
        expected_harvest_date="2027-02-10",
        plot_count=50,
    )
    return {
        "program_id": program_id,
        "line_id": line["id"],
        "block_id": block["id"],
        "first_planting_id": first["id"],
    }


def test_a_planting_sown_on_the_predecessors_occupancy_end_date_is_admitted(api):
    """
    The reserved interval runs to `expected_harvest_date` plus the buffer and is
    half-open, so 2027-02-24 is free while 2027-02-23 is still taken.

    PRD 3.3: "The planting is created in `status` `SCHEDULED`; the server computes
    `occupancy_end_date` as the `expected_harvest_date` advanced by the block's
    `fallow_buffer_days` days, which is the exclusive end of the block's occupancy
    interval and therefore the first date on which the block may be re-sown."
    PRD 3.3: "Because the intervals are half-open, touching endpoints do not
    conflict: a new planting whose `sow_date` equals an existing planting's
    `occupancy_end_date` is admitted, since the fallow period has just expired."
    PRD 3.3: "Any genuine overlap is refused with `ERR_BLOCK_OCCUPANCY_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/nursery_block_half_open_occupancy_plus_fallow_buffer
    """
    net = _block_holding_one_scheduled_planting(api)
    first = validate_success(
        api.get_planting(net["first_planting_id"], SCIENTIST_HEADERS)
    )
    # 2027-02-10 advanced by the block's 14 fallow days.
    assert first["occupancy_end_date"] == "2027-02-24"
    assert first["status"] == PlantingStatus.SCHEDULED

    second = validate_success(
        api.create_planting(
            factories.planting_payload(
                net["block_id"],
                net["line_id"],
                sow_date="2027-02-24",
                expected_harvest_date="2027-06-20",
                plot_count=50,
            ),
            SCIENTIST_HEADERS,
        ),
        201,
    )
    assert second["occupancy_end_date"] == "2027-07-04"
    assert second["status"] == PlantingStatus.SCHEDULED

    validate_error(
        api.create_planting(
            factories.planting_payload(
                net["block_id"],
                net["line_id"],
                sow_date="2027-02-23",
                expected_harvest_date="2027-06-20",
                plot_count=50,
            ),
            SCIENTIST_HEADERS,
        ),
        ApiErrorId.BLOCK_OCCUPANCY_CONFLICT,
        409,
    )

    program = validate_success(api.get_program(net["program_id"], DIRECTOR_HEADERS))
    # Only the two admitted plantings committed ground.
    assert program["committed_plot_count"] == 100
    _rows, meta = validate_paginated(
        api.list_plantings(SCIENTIST_HEADERS, {"nursery_block_id": net["block_id"]})
    )
    assert meta["total_count"] == 2


def test_occupancy_reads_the_clock_across_the_crop_and_the_fallow_leg(api):
    """
    The same interval reports OCCUPIED before the expected harvest and FALLOW
    after it, and the touching planting clears the occupancy rung only to be
    turned away by the WINTER season rung.

    PRD 3.3: "It reads `AVAILABLE` unless the logical clock's calendar date falls
    inside the occupancy interval of a planting on this block whose `status` is
    `SCHEDULED`, `PLANTED`, `HARVESTED` or `FAILED`."
    PRD 3.3: "Inside such an interval it reads `OCCUPIED` when the clock date is
    on or after that planting's `sow_date` and strictly before its
    `expected_harvest_date`, and `FALLOW` when the clock date is on or after
    `expected_harvest_date` and strictly before `occupancy_end_date`."
    PRD 3.3: "A sowing month outside the block's admissible set is refused with
    `ERR_NURSERY_SEASON_MISMATCH`."

    Design: Difficulty/resource_temporal_overlap/nursery_block_half_open_occupancy_plus_fallow_buffer
    """
    net = _block_holding_one_scheduled_planting(api)
    validate_success(
        api.create_planting(
            factories.planting_payload(
                net["block_id"],
                net["line_id"],
                sow_date="2027-02-24",
                expected_harvest_date="2027-06-20",
                plot_count=50,
            ),
            SCIENTIST_HEADERS,
        ),
        201,
    )

    # The unset clock reads 2026-08-01, which is before either sow date.
    block = validate_success(api.get_nursery_block(net["block_id"], SCIENTIST_HEADERS))
    assert block["occupancy_status"] == OccupancyStatus.AVAILABLE

    validate_success(api.set_clock("2026-11-01T00:00:00Z", SCIENTIST_HEADERS))
    block = validate_success(api.get_nursery_block(net["block_id"], SCIENTIST_HEADERS))
    assert block["occupancy_status"] == OccupancyStatus.OCCUPIED

    validate_success(api.set_clock("2027-02-15T00:00:00Z", SCIENTIST_HEADERS))
    block = validate_success(api.get_nursery_block(net["block_id"], SCIENTIST_HEADERS))
    assert block["occupancy_status"] == OccupancyStatus.FALLOW

    # 2027-07-04 is the second planting's occupancy_end_date, so the ground is
    # free; July is not an admissible WINTER sowing month.
    validate_error(
        api.create_planting(
            factories.planting_payload(
                net["block_id"],
                net["line_id"],
                sow_date="2027-07-04",
                expected_harvest_date="2027-11-01",
                plot_count=50,
            ),
            SCIENTIST_HEADERS,
        ),
        ApiErrorId.NURSERY_SEASON_MISMATCH,
        422,
    )


def _site_at_forty_five_of_sixty_plots(api):
    """Site TO1 (capacity 60) holding one 45-plot entry over 2027-04-01 to 2027-06-30."""
    program_id, objective_id = fixtures.program_with_objective(
        api, program_overrides={"name": "Soy Overlap"}
    )
    line_a = fixtures.create_line(
        api, program_id, objective_id, designation="SX-1201", seed_inventory_g=100000
    )
    line_b = fixtures.create_line(
        api, program_id, objective_id, designation="SX-1202", seed_inventory_g=100000
    )
    site = fixtures.create_site(
        api,
        site_code="TO1",
        environment_class="RAINFED_TEMPERATE",
        total_plot_capacity=60,
        plot_cost_usd=40.00,
    )
    series = fixtures.create_series(
        api, program_id, replication_count=3, min_locations=1
    )
    fixtures.create_entry(
        api,
        series["id"],
        line_a["id"],
        site["id"],
        plot_count=45,
        planting_window_start="2027-04-01",
        planting_window_end="2027-06-30",
    )
    return {
        "program_id": program_id,
        "site_id": site["id"],
        "series_id": series["id"],
        "line_b_id": line_b["id"],
    }


def test_two_entries_sharing_a_single_boundary_day_compete_for_plots(api):
    """
    45 plots ending 2027-06-30 and 18 plots starting 2027-06-30 both occupy the
    site on that one date, so their aggregate 63 overflows a 60-plot location that
    neither entry alone would strain.

    PRD 3.5: "For each date it sums the `plot_count` of every such entry whose
    `planting_window_start` is on or before that date and whose
    `planting_window_end` is on or after it — both endpoints occupy the site, so
    two entries that share a single boundary date do compete for plots."
    PRD 3.5: "Only then does the admission test proper run: the server performs
    the daily sweep as it would stand **after** inserting the new entry, and if
    the resulting peak exceeds the site's `total_plot_capacity` the entry is
    refused with `ERR_SITE_PLOT_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/trial_site_closed_interval_aggregate_peak_at_shared_boundary_day
    """
    net = _site_at_forty_five_of_sixty_plots(api)
    validate_error(
        api.create_entry(
            net["series_id"],
            factories.entry_payload(
                net["line_b_id"],
                net["site_id"],
                plot_count=18,
                planting_window_start="2027-06-30",
                planting_window_end="2027-08-31",
            ),
            AGRONOMIST_HEADERS,
        ),
        ApiErrorId.SITE_PLOT_CAPACITY_EXCEEDED,
        409,
    )

    site = validate_success(api.get_site(net["site_id"], AGRONOMIST_HEADERS))
    assert site["peak_committed_plot_count"] == 45
    assert site["available_plot_count"] == 15
    assert site["capacity_posture"] == CapacityPosture.OPEN
    _rows, meta = validate_paginated(
        api.list_entries(AGRONOMIST_HEADERS, {"trial_series_id": net["series_id"]})
    )
    assert meta["total_count"] == 1


def test_shifting_the_window_one_day_makes_the_two_entries_disjoint(api):
    """
    Starting a day later the same 18 plots never share a date with the 45, so the
    site peak stays at 45 while the programme still carries both entries.

    PRD 3.5: "`peak_committed_plot_count` is the largest of those daily sums, or 0
    when the site has no active entries at all, and `available_plot_count` is
    `total_plot_capacity` less that peak."
    PRD 3.5: "Creation then updates three neighbours: the series' `entry_count` —
    the count of its entries whose `status` is `ENTERED`, `PLANTED` or `HARVESTED`
    — and its `location_count`, the number of distinct `trial_site_id` values over
    those same entries; the site's peak, availability and posture; and the
    programme's `committed_plot_count`, which rises by the entry's `plot_count`
    with `plot_budget_remaining` recomputed."

    Design: Difficulty/resource_temporal_overlap/trial_site_closed_interval_aggregate_peak_at_shared_boundary_day
    """
    net = _site_at_forty_five_of_sixty_plots(api)
    entry_b = validate_success(
        api.create_entry(
            net["series_id"],
            factories.entry_payload(
                net["line_b_id"],
                net["site_id"],
                plot_count=18,
                planting_window_start="2027-07-01",
                planting_window_end="2027-08-31",
            ),
            AGRONOMIST_HEADERS,
        ),
        201,
    )
    assert entry_b["status"] == EntryStatus.ENTERED

    site = validate_success(api.get_site(net["site_id"], AGRONOMIST_HEADERS))
    assert site["peak_committed_plot_count"] == 45
    assert site["available_plot_count"] == 15
    assert site["capacity_posture"] == CapacityPosture.OPEN

    program = validate_success(api.get_program(net["program_id"], DIRECTOR_HEADERS))
    # The programme counts both entries even though the site peak does not.
    assert program["committed_plot_count"] == 63
    assert program["plot_budget_remaining"] == 4937

    series = validate_success(api.get_series(net["series_id"], AGRONOMIST_HEADERS))
    assert series["entry_count"] == 2
    assert series["location_count"] == 1
    _rows, meta = validate_paginated(
        api.list_entries(AGRONOMIST_HEADERS, {"trial_series_id": net["series_id"]})
    )
    assert meta["total_count"] == 2
