"""
Closed bounds evaluated on filtered counts and on exact decimal ratios: the
three-replication floor for a yield rollup, and the two posture cut-offs.
"""

from test_helpers import (
    AGRONOMIST_HEADERS,
    DIRECTOR_HEADERS,
    ApiErrorId,
    CapacityPosture,
    EntryStatus,
    SeriesStatus,
    approx2,
    approx3,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


def _two_entries_with_rejected_reps(api):
    """
    Entry A holds three ACCEPTED and one REJECTED replication; entry B holds two
    ACCEPTED and two REJECTED, one short of the floor.
    """
    program_id, objective_id = fixtures.program_with_objective(
        api, program_overrides={"name": "Soy Boundary"}
    )
    line_a = fixtures.create_line(
        api, program_id, objective_id, designation="SX-8001",
        seed_inventory_g=100000,
        disease_resistance_scores={"RUST": 8, "SDS": 7},
        quality_trait_values={"PROTEIN": 13.4},
    )
    line_b = fixtures.create_line(
        api, program_id, objective_id, designation="SX-8002", seed_inventory_g=100000
    )
    site = fixtures.create_site(api, site_code="BS1")
    series = fixtures.create_series(api, program_id, min_locations=1)
    entry_a = fixtures.create_entry(api, series["id"], line_a["id"], site["id"])
    entry_b = fixtures.create_entry(api, series["id"], line_b["id"], site["id"])
    fixtures.plant_series(api, series["id"])
    fixtures.record_yield_reps(api, entry_a["id"], [14.0, 15.5, 15.5], rejected={4: 20.0})
    fixtures.record_yield_reps(api, entry_b["id"], [13.0, 14.0], rejected={3: 14.0, 4: 15.0})
    return series["id"], entry_a["id"], entry_b["id"]


def test_finalize_succeeds_at_exactly_three_valid_reps(api):
    """
    The floor is measured on the QC-filtered count, and the rollup averages only
    the three accepted replications.

    PRD 3.6: "The entry must be `PLANTED`, and its `valid_rep_count` must be at
    least 3 — fewer valid replications cannot support a mean, so the request is
    refused with `ERR_INSUFFICIENT_REPLICATION`."
    PRD 3.6: "The rollup uses exactly the inclusion set that defines
    `valid_rep_count`: `ACCEPTED`, non-outlier `YIELD_KG_PLOT` observations of this
    entry, with rejected rows and outlier-flagged rows excluded from both the count
    and the sum."
    PRD 3.6: "Then — and the order matters — that already-rounded three-decimal
    mean is scaled to a per-hectare figure and rounded again: `yield_kg_per_ha` is
    `plot_mean_yield_kg` multiplied by 800, rounded half up to two decimals."

    Design: Difficulty/boundary_precision_check/finalize_at_exactly_three_valid_reps
    """
    _series_id, entry_a_id, _entry_b_id = _two_entries_with_rejected_reps(api)

    entry = validate_success(api.finalize_entry(entry_a_id, AGRONOMIST_HEADERS))
    assert entry["status"] == EntryStatus.HARVESTED
    assert entry["valid_rep_count"] == 3
    assert entry["plot_mean_yield_kg"] == approx3(15.000)
    assert entry["yield_kg_per_ha"] == approx2(12000.00)
    # Counting the REJECTED 20.0 would have averaged 16.250 instead.
    assert entry["plot_mean_yield_kg"] != approx3(16.250)


def test_finalize_is_refused_one_valid_rep_below_the_floor(api):
    """
    Four recorded observations of which two are REJECTED leave two valid reps, so
    the entry stays PLANTED with a null rollup and the series does not bubble.

    PRD 3.6: "The entry must be `PLANTED`, and its `valid_rep_count` must be at
    least 3 — fewer valid replications cannot support a mean, so the request is
    refused with `ERR_INSUFFICIENT_REPLICATION`."
    PRD 3.6: "After a finalisation, a withdrawal or an invalidation, the server
    re-evaluates the parent series: when the series is `PLANTED`, no entry of the
    series is left in `status` `PLANTED`, and at least one entry of the series has
    reached `HARVESTED`, the series auto-transitions `PLANTED → DATA_COMPLETE` and
    its `version` advances."

    Design: Difficulty/boundary_precision_check/finalize_at_exactly_three_valid_reps
    """
    series_id, entry_a_id, entry_b_id = _two_entries_with_rejected_reps(api)
    fixtures.finalize_entry(api, entry_a_id)

    validate_error(
        api.finalize_entry(entry_b_id, AGRONOMIST_HEADERS),
        ApiErrorId.INSUFFICIENT_REPLICATION,
        422,
    )
    entry_b = validate_success(api.get_entry(entry_b_id, AGRONOMIST_HEADERS))
    assert entry_b["status"] == EntryStatus.PLANTED
    assert entry_b["valid_rep_count"] == 2
    assert entry_b["plot_mean_yield_kg"] is None
    assert entry_b["yield_kg_per_ha"] is None

    series = validate_success(api.get_series(series_id, AGRONOMIST_HEADERS))
    assert series["status"] == SeriesStatus.PLANTED

    _rows, meta = validate_paginated(
        api.list_observations(entry_b_id, AGRONOMIST_HEADERS)
    )
    assert meta["total_count"] == 4


def _three_sixty_plot_sites(api):
    """Three 60-plot sites loaded to 48, 51 and 60 plots by one STAGE_1 series."""
    program_id, objective_id = fixtures.program_with_objective(
        api, program_overrides={"name": "Soy Posture"}
    )
    lines = [
        fixtures.create_line(
            api, program_id, objective_id, designation=code, seed_inventory_g=100000
        )
        for code in ("SX-9001", "SX-9002", "SX-9003")
    ]
    site_a = fixtures.create_site(
        api, site_code="PA1", environment_class="RAINFED_TEMPERATE",
        total_plot_capacity=60, plot_cost_usd=40.00,
    )
    site_b = fixtures.create_site(
        api, site_code="PB1", environment_class="DROUGHT_STRESS",
        total_plot_capacity=60, plot_cost_usd=36.00,
    )
    site_c = fixtures.create_site(
        api, site_code="PC1", total_plot_capacity=60, plot_cost_usd=45.00
    )
    series = fixtures.create_series(
        api, program_id, replication_count=3, min_locations=1
    )
    fixtures.create_entry(api, series["id"], lines[0]["id"], site_a["id"], plot_count=48)
    fixtures.create_entry(api, series["id"], lines[1]["id"], site_b["id"], plot_count=51)
    fixtures.create_entry(api, series["id"], lines[2]["id"], site_c["id"], plot_count=60)
    return {
        "program_id": program_id,
        "objective_id": objective_id,
        "series_id": series["id"],
        "site_a_id": site_a["id"],
        "site_b_id": site_b["id"],
        "site_c_id": site_c["id"],
        "line_a_id": lines[0]["id"],
    }


def test_posture_cutoffs_are_inclusive_at_exactly_085_and_exactly_100(api):
    """
    48/60 stays OPEN, 51/60 is exactly 0.85 and reads RESTRICTED, and 60/60 is
    exactly 1.00 and reads FROZEN.

    PRD 3.5: "The site's **capacity posture** is derived from utilisation, defined
    as `peak_committed_plot_count` divided by `total_plot_capacity` and compared as
    an exact decimal ratio rather than as a floating-point approximation."
    PRD 3.5: "`capacity_posture` reads `FROZEN` when utilisation is 1.00 or
    greater, `RESTRICTED` when utilisation is 0.85 or greater but below 1.00, and
    `OPEN` otherwise; a site sitting exactly at 0.85 is therefore `RESTRICTED` and
    a site sitting exactly at 1.00 is `FROZEN`."

    Design: Difficulty/boundary_precision_check/site_posture_at_exact_085_and_exact_100_utilisation
    """
    net = _three_sixty_plot_sites(api)

    site_a = validate_success(api.get_site(net["site_a_id"], AGRONOMIST_HEADERS))
    assert site_a["peak_committed_plot_count"] == 48
    assert site_a["available_plot_count"] == 12
    assert site_a["capacity_posture"] == CapacityPosture.OPEN

    site_b = validate_success(api.get_site(net["site_b_id"], AGRONOMIST_HEADERS))
    assert site_b["peak_committed_plot_count"] == 51
    assert site_b["available_plot_count"] == 9
    assert site_b["capacity_posture"] == CapacityPosture.RESTRICTED

    site_c = validate_success(api.get_site(net["site_c_id"], AGRONOMIST_HEADERS))
    assert site_c["peak_committed_plot_count"] == 60
    assert site_c["available_plot_count"] == 0
    assert site_c["capacity_posture"] == CapacityPosture.FROZEN

    series = validate_success(api.get_series(net["series_id"], AGRONOMIST_HEADERS))
    assert series["entry_count"] == 3
    assert series["location_count"] == 3
    program = validate_success(api.get_program(net["program_id"], DIRECTOR_HEADERS))
    assert program["committed_plot_count"] == 159
    assert program["plot_budget_remaining"] == 4841


def test_each_posture_admits_a_further_early_stage_entry_differently(api):
    """
    The same three-plot STAGE_1 entry is frozen out at 1.00, stage-refused at
    0.85, and admitted at 0.80.

    PRD 3.5: "The posture gates come first: a site whose `capacity_posture` is
    `FROZEN` refuses the entry outright with `ERR_SITE_CAPACITY_FROZEN`, and a site
    whose posture is `RESTRICTED` admits an entry only from a series whose `stage`
    is `STAGE_2` or `STAGE_3`, refusing an early-stage series with
    `ERR_SITE_RESTRICTED_STAGE` — scarce ground at a nearly full location is
    reserved for advanced material."

    Design: Difficulty/boundary_precision_check/site_posture_at_exact_085_and_exact_100_utilisation
    """
    net = _three_sixty_plot_sites(api)
    probe_line = fixtures.create_line(
        api, net["program_id"], net["objective_id"],
        designation="SX-9004", seed_inventory_g=100000,
    )
    probe_series = fixtures.create_series(
        api, net["program_id"], replication_count=3, min_locations=1
    )

    validate_error(
        api.create_entry(
            probe_series["id"],
            factories.entry_payload(probe_line["id"], net["site_c_id"], plot_count=3),
            AGRONOMIST_HEADERS,
        ),
        ApiErrorId.SITE_CAPACITY_FROZEN,
        409,
    )
    validate_error(
        api.create_entry(
            probe_series["id"],
            factories.entry_payload(probe_line["id"], net["site_b_id"], plot_count=3),
            AGRONOMIST_HEADERS,
        ),
        ApiErrorId.SITE_RESTRICTED_STAGE,
        409,
    )
    admitted = validate_success(
        api.create_entry(
            probe_series["id"],
            factories.entry_payload(probe_line["id"], net["site_a_id"], plot_count=3),
            AGRONOMIST_HEADERS,
        ),
        201,
    )
    assert admitted["plot_count"] == 3
