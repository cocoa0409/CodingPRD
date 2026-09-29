"""
The entity surface: creation envelopes, retrieval shapes, listing pagination,
per-family 404 codes, shape rejection, declared defaults, computed fields, and
the containment/junction relationships that bind the graph together.
"""

from test_helpers import (
    AGRONOMIST_HEADERS,
    ANALYST_HEADERS,
    DIRECTOR_HEADERS,
    PLANNER_HEADERS,
    REGULATORY_HEADERS,
    SCIENTIST_HEADERS,
    UNKNOWN_UUID,
    AdvancementReadiness,
    ApiErrorId,
    CapacityPosture,
    EntryStatus,
    OccupancyStatus,
    PipelineStage,
    ProgramStatus,
    QcStatus,
    StewardshipStatus,
    approx2,
    assert_identity,
    assert_instant_shape,
    assert_meta_envelope,
    assert_no_version_fields,
    assert_versioned,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_program_creation_returns_the_whole_record_with_zeroed_rollups(api):
    """
    A 201 carries every declared programme field, not a bare id, and all five
    rollups sit at their creation values.

    PRD 3.1: "The programme opens with `status` `ACTIVE`; the only other value
    that field ever takes is `CLOSED`."
    PRD 3.1: "At registration `committed_plot_count`, `committed_budget_usd`,
    `active_line_count` and `pre_commercial_units_bags` are all zero, and
    `plot_budget_remaining` equals `total_plot_budget` because nothing has been
    committed yet."
    PRD 2.4: "`updated_at` is an ISO 8601 UTC instant refreshed on every mutation
    of the record, and `version` is an integer that starts at 1 on creation and
    increments by exactly 1 on every mutation, including mutations the server
    performs on its own initiative as part of a cascade."

    Design: Corner/entities/program_creation_returns_envelope_with_zeroed_rollups
    """
    response = api.create_program(factories.program_payload(), DIRECTOR_HEADERS)
    body = response.json()
    assert_meta_envelope(body)
    assert body["response_type"] == "object"
    program = validate_success(response, 201)

    assert program["name"] == "Soy North Central"
    assert program["crop_code"] == "SOYBEAN"
    assert program["market_zone"] == "NORTH_CENTRAL"
    assert program["total_plot_budget"] == 5000
    assert program["total_budget_usd"] == approx2(2000000.00)
    assert program["committed_plot_count"] == 0
    assert program["plot_budget_remaining"] == 5000
    assert program["committed_budget_usd"] == approx2(0.00)
    assert program["active_line_count"] == 0
    assert program["pre_commercial_units_bags"] == 0
    assert program["status"] == ProgramStatus.ACTIVE
    assert_versioned(program, expected_version=1)
    assert_instant_shape(program["created_at"])
    assert_instant_shape(program["updated_at"])


def test_line_retrieval_exposes_both_state_dimensions_and_the_seed_ledger(api):
    """
    One read must show `pipeline_stage` and `stewardship_status` together with all
    four seed-ledger figures, because every stewardship rule reads the second
    dimension.

    PRD 3.2: "A directly registered line has `origin_block_id` null, opens at
    `pipeline_stage` `NURSERY` with `stewardship_status` `NOT_REQUIRED`, sets
    `cumulative_seed_produced_g` to its opening `seed_inventory_g`, and increments
    the programme's `active_line_count`."
    PRD 3.9: "`reserved_seed_g` is the sum of `allocated_seed_g` over the line's
    lots whose `status` is `RESERVED`, `IN_PRODUCTION` or `ON_HOLD`, excluding
    `COMPLETED` and `CANCELLED` lots."

    Design: Corner/entities/line_retrieval_returns_both_state_dimensions_and_seed_ledger
    """
    program_id, objective_id = fixtures.program_with_objective(api)
    created = fixtures.create_line_a(api, program_id, objective_id)

    line = validate_success(api.get_line(created["id"], ANALYST_HEADERS))
    assert line["pipeline_stage"] == PipelineStage.NURSERY
    assert line["stewardship_status"] == StewardshipStatus.NOT_REQUIRED
    assert line["seed_inventory_g"] == 500000
    assert line["reserved_seed_g"] == 0
    assert line["consumed_seed_g"] == 0
    assert line["cumulative_seed_produced_g"] == 500000
    assert line["disease_resistance_scores"] == {"RUST": 8, "SDS": 7}
    assert line["quality_trait_values"] == {"PROTEIN": 13.4, "TEST_WEIGHT": 75.0}
    assert line["advancement_readiness"] == AdvancementReadiness.READY
    assert line["origin_block_id"] is None
    assert line["female_parent_line_id"] is None
    assert line["male_parent_line_id"] is None


def test_line_listing_reports_the_filtered_total_and_honours_the_window(api):
    """
    `total_count` counts the whole filtered set while the page respects `limit`,
    so a two-row page out of three rows still reports three with more to come.

    PRD 2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more`
    inside the `meta` object of the envelope, where `total_count` is the number of
    records matching the filter before pagination is applied and `has_more` is
    true when records remain beyond the current window."
    PRD 2.3: "Unless a specific endpoint states a different ordering, list results
    are sorted by `created_at` ascending."

    Design: Corner/entities/breeding_lines_list_paginates_and_filters_by_program
    """
    program_id, objective_id = fixtures.program_with_objective(api)
    for designation, seed in (
        ("SX-1001", 500000),
        ("SX-1002", 400000),
        ("SX-1003", 300000),
    ):
        fixtures.create_line(
            api, program_id, objective_id, designation=designation, seed_inventory_g=seed
        )

    rows, meta = validate_paginated(
        api.list_lines(
            DIRECTOR_HEADERS, {"program_id": program_id, "limit": 2, "offset": 0}
        )
    )
    assert len(rows) == 2
    assert [row["designation"] for row in rows] == ["SX-1001", "SX-1002"]
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0

    tail, tail_meta = validate_paginated(
        api.list_lines(
            DIRECTOR_HEADERS, {"program_id": program_id, "limit": 2, "offset": 2}
        )
    )
    assert [row["designation"] for row in tail] == ["SX-1003"]
    assert tail_meta["total_count"] == 3
    assert tail_meta["has_more"] is False

    empty, empty_meta = validate_paginated(
        api.list_lines(
            DIRECTOR_HEADERS, {"program_id": program_id, "pipeline_stage": "STAGE_1"}
        )
    )
    assert empty == []
    assert empty_meta["total_count"] == 0


def test_each_path_resolved_family_answers_with_its_own_404_code(api):
    """
    Thirteen path-resolved families each answer with their own identifier so a
    client can tell which segment of a nested path failed.

    PRD 2.7: "Every identifier embedded in the path resolves, validated left to
    right, with the first unresolved identifier deciding the code:
    `ERR_PROGRAM_NOT_FOUND`, `ERR_OBJECTIVE_NOT_FOUND`,
    `ERR_NURSERY_BLOCK_NOT_FOUND`, `ERR_CROSSING_BLOCK_NOT_FOUND`,
    `ERR_LINE_NOT_FOUND`, `ERR_PLANTING_NOT_FOUND`, `ERR_TRIAL_SITE_NOT_FOUND`,
    `ERR_TRIAL_SERIES_NOT_FOUND`, `ERR_TRIAL_ENTRY_NOT_FOUND`,
    `ERR_DECISION_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`,
    `ERR_SEED_LOT_NOT_FOUND` or `ERR_BACKCROSS_NOT_FOUND`, each HTTP 404."
    PRD 2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/entities/unknown_path_ids_return_the_entity_specific_404
    """
    probes = [
        (api.get_program(UNKNOWN_UUID, DIRECTOR_HEADERS), ApiErrorId.PROGRAM_NOT_FOUND),
        (
            api.get_objective(UNKNOWN_UUID, DIRECTOR_HEADERS),
            ApiErrorId.OBJECTIVE_NOT_FOUND,
        ),
        (
            api.get_nursery_block(UNKNOWN_UUID, SCIENTIST_HEADERS),
            ApiErrorId.NURSERY_BLOCK_NOT_FOUND,
        ),
        (
            api.get_crossing_block(UNKNOWN_UUID, SCIENTIST_HEADERS),
            ApiErrorId.CROSSING_BLOCK_NOT_FOUND,
        ),
        (api.get_line(UNKNOWN_UUID, DIRECTOR_HEADERS), ApiErrorId.LINE_NOT_FOUND),
        (
            api.get_planting(UNKNOWN_UUID, SCIENTIST_HEADERS),
            ApiErrorId.PLANTING_NOT_FOUND,
        ),
        (
            api.get_site(UNKNOWN_UUID, AGRONOMIST_HEADERS),
            ApiErrorId.TRIAL_SITE_NOT_FOUND,
        ),
        (
            api.get_series(UNKNOWN_UUID, AGRONOMIST_HEADERS),
            ApiErrorId.TRIAL_SERIES_NOT_FOUND,
        ),
        (
            api.get_entry(UNKNOWN_UUID, AGRONOMIST_HEADERS),
            ApiErrorId.TRIAL_ENTRY_NOT_FOUND,
        ),
        (
            api.get_decision(UNKNOWN_UUID, DIRECTOR_HEADERS),
            ApiErrorId.DECISION_NOT_FOUND,
        ),
        (
            api.get_agreement(UNKNOWN_UUID, REGULATORY_HEADERS),
            ApiErrorId.AGREEMENT_NOT_FOUND,
        ),
        (api.get_lot(UNKNOWN_UUID, PLANNER_HEADERS), ApiErrorId.SEED_LOT_NOT_FOUND),
        (
            api.get_backcross(UNKNOWN_UUID, SCIENTIST_HEADERS),
            ApiErrorId.BACKCROSS_NOT_FOUND,
        ),
    ]
    for response, error_id in probes:
        body = validate_error(response, error_id, 404)
        assert response.json()["response_type"] == "error"
        assert isinstance(body["message"], str) and body["message"]


def test_a_missing_required_field_and_a_bad_weight_sum_are_both_shape_failures(api):
    """
    A plainly absent required input and a body-local cross-field rule both answer
    at the shape rung, and the shape rung outranks the body foreign-key rung.

    PRD 3.1: "`yield_weight`, `disease_weight` and `quality_weight` each lie
    between 0 and 1 inclusive with two decimal places, and the three must sum to
    exactly 1.00 — a body whose weights sum to 0.99 or 1.01 is rejected at the
    request-shape step with `ERR_INVALID_REQUEST`."
    PRD 2.7: "This step also settles the cross-field rules that need no other
    entity to decide: `granted_plots` must be 0 unless `decision` is `ADVANCE`;
    `donor_line_id` must differ from `recurrent_line_id`; `market_allocations` must
    be non-empty with every `demand_kg` greater than 0; `approved_markets` must be
    non-empty; `yield_weight` plus `disease_weight` plus `quality_weight` must equal
    exactly 1.00; and `expected_harvest_date` must be strictly later than
    `sow_date`."

    Design: Corner/entities/line_create_missing_designation_and_bad_weight_sum_rejected
    """
    program_id, objective_id = fixtures.program_with_objective(api)

    validate_error(
        api.create_line(
            factories.line_payload(program_id, objective_id, designation=factories.OMIT),
            SCIENTIST_HEADERS,
        ),
        ApiErrorId.INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_objective(
            program_id,
            factories.objective_payload(
                market_segment="MG3_SOUTH", quality_weight=0.30
            ),
            DIRECTOR_HEADERS,
        ),
        ApiErrorId.INVALID_REQUEST,
        400,
    )
    # Both a missing designation and an unknown program_id: the shape rung wins.
    validate_error(
        api.create_line(
            factories.line_payload(
                UNKNOWN_UUID, objective_id, designation=factories.OMIT
            ),
            SCIENTIST_HEADERS,
        ),
        ApiErrorId.INVALID_REQUEST,
        400,
    )

    program = validate_success(api.get_program(program_id, DIRECTOR_HEADERS))
    assert program["active_line_count"] == 0
    _rows, meta = validate_paginated(api.list_objectives(program_id, DIRECTOR_HEADERS))
    assert meta["total_count"] == 1


def test_omitted_optional_inputs_materialise_their_declared_defaults(api):
    """
    Omitted optionals become their declared defaults rather than null, and the
    nursery buffer default is load-bearing because the occupancy interval is built
    from it.

    PRD 3.2: "Both maps default to empty and `seed_inventory_g` defaults to 0."
    PRD 3.3: "A `BreedingScientist` registers a **nursery block** with a
    `block_code` that must be unique across all blocks, a `nursery_type` of either
    `WINTER` or `SUMMER`, a `location_code` naming the physical location
    (`CL_QUILLOTA`, for instance), a `plot_count` of at least 1 describing how many
    plots the block physically holds, and an optional `fallow_buffer_days` of at
    least 0 that defaults to 14 when omitted."
    PRD 3.3: "`nursery_cycles_completed` is by definition the number of this line's
    plantings that reached `HARVESTED`, which is why a failure leaves it
    untouched."

    Design: Corner/entities/line_create_omitting_optional_inputs_applies_declared_defaults
    """
    program_id, objective_id = fixtures.program_with_objective(api)
    line = fixtures.create_line(
        api,
        program_id,
        objective_id,
        designation="SX-1009",
        generation_number=4,
        seed_inventory_g=factories.OMIT,
    )
    assert line["seed_inventory_g"] == 0
    assert line["cumulative_seed_produced_g"] == 0
    assert line["reserved_seed_g"] == 0
    assert line["consumed_seed_g"] == 0
    assert line["disease_resistance_scores"] == {}
    assert line["quality_trait_values"] == {}
    assert line["nursery_cycles_completed"] == 0
    assert line["planned_launch_units_bags"] == 0
    assert line["advancement_index_provisional"] is None
    # Generation 4 sits below the objective's min_generation_number of 5.
    assert line["advancement_readiness"] == AdvancementReadiness.NOT_READY

    block = fixtures.create_nursery_block(
        api,
        block_code="NB-DEF1",
        nursery_type="SUMMER",
        location_code="IA_AMES",
        plot_count=120,
        fallow_buffer_days=factories.OMIT,
    )
    assert block["fallow_buffer_days"] == 14
    assert block["occupancy_status"] == OccupancyStatus.AVAILABLE


def test_site_capacity_fields_are_derived_at_every_read(api):
    """
    Peak, availability and posture appear in no input list, so they must be
    re-derived from the entry population rather than written once.

    PRD 3.5: "A new site opens with `peak_committed_plot_count` at 0,
    `available_plot_count` equal to `total_plot_capacity`, and `capacity_posture`
    `OPEN`."
    PRD 2.10: "Derived fields are never accepted from a client. A programme's plot
    and cash commitments, a nursery block's occupancy, a site's peak occupancy and
    posture, a series' entry and location census, an entry's replication census and
    yield rollup, a line's readiness, seed ledger and provisional index — all of
    these are computed by the server from the records that justify them, and a
    value supplied for such a field in a request body is ignored."
    PRD 3.5: "The entry is created in `status` `ENTERED` with `valid_rep_count` at
    0 and both `plot_mean_yield_kg` and `yield_kg_per_ha` null."

    Design: Corner/entities/computed_and_system_fields_ignore_client_supplied_values
    """
    program_id, objective_id = fixtures.program_with_objective(api)
    line = fixtures.create_line(api, program_id, objective_id)
    series = fixtures.create_series(
        api, program_id, replication_count=3, min_locations=1
    )
    site = fixtures.create_site(
        api,
        site_code="CF1",
        environment_class="RAINFED_TEMPERATE",
        total_plot_capacity=60,
        plot_cost_usd=40.00,
    )
    assert site["capacity_posture"] == CapacityPosture.OPEN
    assert site["peak_committed_plot_count"] == 0
    assert site["available_plot_count"] == 60
    assert_versioned(site, expected_version=1)

    entry = fixtures.create_entry(
        api, series["id"], line["id"], site["id"], plot_count=51
    )
    assert entry["valid_rep_count"] == 0
    assert entry["plot_mean_yield_kg"] is None
    assert entry["yield_kg_per_ha"] is None
    assert entry["withdrawal_reason"] is None
    assert entry["status"] == EntryStatus.ENTERED

    reread = validate_success(api.get_site(site["id"], AGRONOMIST_HEADERS))
    assert reread["peak_committed_plot_count"] == 51
    assert reread["available_plot_count"] == 9
    assert reread["capacity_posture"] == CapacityPosture.RESTRICTED
    assert reread["id"] == site["id"]
    assert reread["created_at"] == site["created_at"]
    assert reread["version"] == 2

    again = validate_success(api.get_site(site["id"], AGRONOMIST_HEADERS))
    assert again["peak_committed_plot_count"] == 51
    assert again["capacity_posture"] == CapacityPosture.RESTRICTED


def test_out_of_enum_and_out_of_range_inputs_are_refused(api):
    """
    An unrecognised `environment_class`, an unrecognised `plot_design` and a
    `replication_count` below its floor of 2 are all shape failures that persist
    nothing.

    PRD 3.5: "A site carries a `site_code` unique across all sites, an
    `environment_class` drawn from `HIGH_YIELD_IRRIGATED`, `RAINFED_TEMPERATE`,
    `DROUGHT_STRESS` and `DISEASE_NURSERY`, a `total_plot_capacity` of at least 1
    describing how many plots the site can host on any single day, a
    `plot_cost_usd` greater than zero with two decimals giving the cost of one plot
    at that location, and a season window defined by `season_start_date` and a
    `season_end_date` that must be strictly later than the start."
    PRD 3.5: "A `ProgramLead` or a `TrialAgronomist` opens one by naming the owning
    `program_id`, the `stage` it serves (`STAGE_1`, `STAGE_2` or `STAGE_3`), the
    `season_year` of harvest, the `plot_design` used at every location (`RCBD`,
    `AUGMENTED` or `ALPHA_LATTICE`), a `replication_count` of at least 2 giving the
    replications per entry per location, and a `min_locations` of at least 1 fixing
    how many distinct sites the network needs before it may be planted — a value of
    1 is legal and describes a single-location screening nursery series."

    Design: Corner/entities/trial_site_and_series_enum_and_range_constraints_enforced
    """
    program_id, _objective_id = fixtures.program_with_objective(api)

    validate_error(
        api.create_site(
            factories.site_payload(
                site_code="TC1",
                environment_class="TROPICAL_WET",
                total_plot_capacity=60,
                plot_cost_usd=40.00,
            ),
            AGRONOMIST_HEADERS,
        ),
        ApiErrorId.INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_series(
            factories.series_payload(
                program_id, plot_design="SPLIT_PLOT", min_locations=1
            ),
            AGRONOMIST_HEADERS,
        ),
        ApiErrorId.INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_series(
            factories.series_payload(program_id, replication_count=1, min_locations=1),
            AGRONOMIST_HEADERS,
        ),
        ApiErrorId.INVALID_REQUEST,
        400,
    )

    _rows, meta = validate_paginated(
        api.list_program_trial_series(program_id, AGRONOMIST_HEADERS)
    )
    assert meta["total_count"] == 0
    program = validate_success(api.get_program(program_id, DIRECTOR_HEADERS))
    assert program["committed_plot_count"] == 0
    assert program["committed_budget_usd"] == approx2(0.00)


def test_an_observation_carries_no_version_and_cannot_be_written_twice(api):
    """
    The one entity outside the common versioning contract, and the uniqueness
    triple that makes it a measurement rather than a mutable cell.

    PRD 2.4: "`PhenotypeObservation` is the single exception. A phenotype
    observation is an immutable measurement: it carries `id` and `created_at` only,
    and both `updated_at` and `version` are absent from its representation."
    PRD 3.6: "Observations may be recorded while the entry is `ENTERED` or
    `PLANTED`, `rep_number` must lie between 1 and the series' `replication_count`
    inclusive, and the combination of `trial_entry_id`, `trait_code` and
    `rep_number` must be unique — a repeat, or a `rep_number` outside the legal
    range, is refused with `ERR_DUPLICATE_OBSERVATION`."
    PRD 3.6: "Every recorded observation re-derives the entry's `valid_rep_count`,
    which counts only this entry's observations whose `trait_code` is
    `YIELD_KG_PLOT`, whose `qc_status` is `ACCEPTED` and whose `is_outlier` is
    false."

    Design: Corner/entities/phenotype_observation_is_immutable_and_carries_no_version
    """
    program_id, objective_id = fixtures.program_with_objective(api)
    line_a = fixtures.create_line_a(api, program_id, objective_id)
    line_b = fixtures.create_line_b(api, program_id, objective_id)
    site = fixtures.create_site(api, site_code="IM1")
    series = fixtures.create_series(
        api, program_id, replication_count=4, min_locations=1
    )
    entry = fixtures.create_entry(
        api, series["id"], line_a["id"], site["id"], plot_count=8
    )
    fixtures.create_entry(api, series["id"], line_b["id"], site["id"], plot_count=8)
    fixtures.plant_series(api, series["id"])

    observation = validate_success(
        api.create_observation(
            entry["id"], factories.observation_payload(1, 14.0), AGRONOMIST_HEADERS
        ),
        201,
    )
    assert_identity(observation)
    assert_instant_shape(observation["created_at"])
    assert_no_version_fields(observation)
    assert observation["qc_status"] == QcStatus.ACCEPTED
    assert observation["is_outlier"] is False
    assert observation["recorded_by_user_id"]
    assert observation["trial_entry_id"] == entry["id"]

    validate_error(
        api.create_observation(
            entry["id"], factories.observation_payload(1, 16.0), AGRONOMIST_HEADERS
        ),
        ApiErrorId.DUPLICATE_OBSERVATION,
        409,
    )

    rows, meta = validate_paginated(api.list_observations(entry["id"], AGRONOMIST_HEADERS))
    assert meta["total_count"] == 1
    assert rows[0]["value"] == approx2(14.0)
    for row in rows:
        assert_no_version_fields(row)
    reread = validate_success(api.get_entry(entry["id"], AGRONOMIST_HEADERS))
    assert reread["valid_rep_count"] == 1


def test_an_objective_hangs_off_the_programme_named_in_its_path(api):
    """
    The parent identifier lives in the path, so an unresolvable parent is a path
    404 and a resolvable one supplies the child's `program_id`.

    PRD 2.7: "**Path existence.** Every identifier embedded in the path resolves,
    validated left to right, with the first unresolved identifier deciding the
    code: `ERR_PROGRAM_NOT_FOUND`, `ERR_OBJECTIVE_NOT_FOUND`,
    `ERR_NURSERY_BLOCK_NOT_FOUND`, `ERR_CROSSING_BLOCK_NOT_FOUND`,
    `ERR_LINE_NOT_FOUND`, `ERR_PLANTING_NOT_FOUND`, `ERR_TRIAL_SITE_NOT_FOUND`,
    `ERR_TRIAL_SERIES_NOT_FOUND`, `ERR_TRIAL_ENTRY_NOT_FOUND`,
    `ERR_DECISION_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_SEED_LOT_NOT_FOUND`
    or `ERR_BACKCROSS_NOT_FOUND`, each HTTP 404."
    PRD 3.1: "An objective is created under its programme, so its `program_id` is
    taken from the path rather than from the body, and it carries a
    `market_segment` label (`MX_NORTH`, say), a `target_yield_kg_per_ha` greater
    than zero expressing the yield the segment demands in kilograms per hectare,
    and a `min_generation_number` of at least 2 fixing the earliest selfing
    generation that may enter a yield trial."

    Design: Corner/entities/objective_requires_an_existing_parent_program_in_the_path
    """
    validate_error(
        api.create_objective(UNKNOWN_UUID, factories.objective_payload(), DIRECTOR_HEADERS),
        ApiErrorId.PROGRAM_NOT_FOUND,
        404,
    )

    program = fixtures.create_program(api)
    objective = validate_success(
        api.create_objective(
            program["id"], factories.objective_payload(), DIRECTOR_HEADERS
        ),
        201,
    )
    assert objective["program_id"] == program["id"]
    assert_versioned(objective, expected_version=1)

    _rows, meta = validate_paginated(api.list_objectives(program["id"], DIRECTOR_HEADERS))
    assert meta["total_count"] == 1
    reread = validate_success(api.get_objective(objective["id"], DIRECTOR_HEADERS))
    assert reread["min_advancement_index"] == approx2(85.00)
    assert reread["program_id"] == program["id"]


def test_the_entry_junction_resolves_its_body_keys_in_declaration_order(api):
    """
    The junction holds three references: the series from the path and the line and
    site from the body, and the body pair answers in the order the input list
    names them.

    PRD 2.7: "**Body foreign keys.** Every foreign key supplied in the body
    resolves, validated in the order the endpoint's input list declares them,
    raising the matching 404 from the set `ERR_PROGRAM_NOT_FOUND`,
    `ERR_OBJECTIVE_NOT_FOUND`, `ERR_LINE_NOT_FOUND`,
    `ERR_NURSERY_BLOCK_NOT_FOUND`, `ERR_TRIAL_SITE_NOT_FOUND`,
    `ERR_TRIAL_SERIES_NOT_FOUND`."
    PRD 3.5: "The agronomist supplies the `line_id`, the `trial_site_id`, a
    `plot_count` of at least 1, and a `planting_window_start` and
    `planting_window_end` bounding the dates on which the entry occupies plots, the
    end date inclusive."
    PRD 3.5: "Creation then updates three neighbours: the series' `entry_count` —
    the count of its entries whose `status` is `ENTERED`, `PLANTED` or `HARVESTED`
    — and its `location_count`, the number of distinct `trial_site_id` values over
    those same entries; the site's peak, availability and posture; and the
    programme's `committed_plot_count`, which rises by the entry's `plot_count`
    with `plot_budget_remaining` recomputed."

    Design: Corner/entities/trial_entry_junction_binds_series_line_and_site_across_the_graph
    """
    program_id, objective_id = fixtures.program_with_objective(api)
    line = fixtures.create_line(api, program_id, objective_id)
    site = fixtures.create_site(api, site_code="JN1")
    series = fixtures.create_series(
        api, program_id, replication_count=4, min_locations=1
    )

    # Both body keys unresolvable: `line_id` is declared first, so it answers.
    validate_error(
        api.create_entry(
            series["id"],
            factories.entry_payload(UNKNOWN_UUID, UNKNOWN_UUID),
            AGRONOMIST_HEADERS,
        ),
        ApiErrorId.LINE_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_entry(
            series["id"],
            factories.entry_payload(line["id"], UNKNOWN_UUID),
            AGRONOMIST_HEADERS,
        ),
        ApiErrorId.TRIAL_SITE_NOT_FOUND,
        404,
    )

    entry = validate_success(
        api.create_entry(
            series["id"],
            factories.entry_payload(line["id"], site["id"]),
            AGRONOMIST_HEADERS,
        ),
        201,
    )
    assert entry["trial_series_id"] == series["id"]
    assert entry["line_id"] == line["id"]
    assert entry["trial_site_id"] == site["id"]
    assert entry["status"] == EntryStatus.ENTERED

    reread = validate_success(api.get_series(series["id"], AGRONOMIST_HEADERS))
    assert reread["entry_count"] == 1
    assert reread["location_count"] == 1
    for params in ({"line_id": line["id"]}, {"trial_site_id": site["id"]}):
        _rows, meta = validate_paginated(api.list_entries(AGRONOMIST_HEADERS, params))
        assert meta["total_count"] == 1
