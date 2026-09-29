"""
Requests that violate two rungs of the validation ladder at once, where only the
earlier rung's error may be reported.
"""

from test_helpers import (
    AGRONOMIST_HEADERS,
    DIRECTOR_HEADERS,
    PLANNER_HEADERS,
    CapacityPosture,
    ApiErrorId,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


def _restricted_site_with_two_candidate_series(api):
    """
    Site RS1 at exactly 0.85 utilisation, plus a STAGE_1 and a STAGE_2 series
    each ready to submit a 12-plot entry that would overflow the site.
    """
    program_id, objective_id = fixtures.program_with_objective(
        api, program_overrides={"name": "Soy Priority"}
    )
    lines = [
        fixtures.create_line(
            api, program_id, objective_id, designation=code, seed_inventory_g=100000
        )
        for code in ("SX-6001", "SX-6002", "SX-6003")
    ]
    site = fixtures.create_site(
        api,
        site_code="RS1",
        environment_class="RAINFED_TEMPERATE",
        total_plot_capacity=60,
        plot_cost_usd=40.00,
    )
    series_a = fixtures.create_series(
        api, program_id, replication_count=3, min_locations=1
    )
    fixtures.create_entry(
        api, series_a["id"], lines[0]["id"], site["id"], plot_count=51
    )
    series_b = fixtures.create_series(
        api, program_id, replication_count=3, min_locations=1
    )
    series_c = fixtures.create_series(
        api, program_id, stage="STAGE_2", replication_count=3, min_locations=1
    )
    return {
        "program_id": program_id,
        "site_id": site["id"],
        "line_b_id": lines[1]["id"],
        "line_c_id": lines[2]["id"],
        "series_b_id": series_b["id"],
        "series_c_id": series_c["id"],
    }


def test_restricted_stage_gate_is_reported_before_the_capacity_overflow(api):
    """
    A STAGE_1 entry at a RESTRICTED site breaks the posture rung and the capacity
    rung in one request, and only the posture rung may answer.

    PRD 3.5: "The posture gates come first: a site whose `capacity_posture` is
    `FROZEN` refuses the entry outright with `ERR_SITE_CAPACITY_FROZEN`, and a site
    whose posture is `RESTRICTED` admits an entry only from a series whose `stage`
    is `STAGE_2` or `STAGE_3`, refusing an early-stage series with
    `ERR_SITE_RESTRICTED_STAGE` — scarce ground at a nearly full location is
    reserved for advanced material."
    PRD 3.5: "Only then does the admission test proper run: the server performs
    the daily sweep as it would stand **after** inserting the new entry, and if
    the resulting peak exceeds the site's `total_plot_capacity` the entry is
    refused with `ERR_SITE_PLOT_CAPACITY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/restricted_stage_gate_outranks_site_capacity_overflow
    """
    net = _restricted_site_with_two_candidate_series(api)
    site = validate_success(api.get_site(net["site_id"], AGRONOMIST_HEADERS))
    assert site["capacity_posture"] == CapacityPosture.RESTRICTED

    # 51 plots already committed plus 12 more would peak at 63 against 60.
    validate_error(
        api.create_entry(
            net["series_b_id"],
            factories.entry_payload(net["line_b_id"], net["site_id"], plot_count=12),
            AGRONOMIST_HEADERS,
        ),
        ApiErrorId.SITE_RESTRICTED_STAGE,
        409,
    )


def test_clearing_the_posture_rung_surfaces_the_capacity_rung(api):
    """
    The same 12-plot entry from a STAGE_2 series passes the posture gate and is
    then refused by the daily sweep, and neither rejection moved a counter.

    PRD 2.7: "A single request can violate several rules at once, and the response
    must be predictable, so the checks below are evaluated **strictly in the order
    listed** and the **first** one that fails decides the response."
    PRD 3.5: "Only then does the admission test proper run: the server performs
    the daily sweep as it would stand **after** inserting the new entry, and if
    the resulting peak exceeds the site's `total_plot_capacity` the entry is
    refused with `ERR_SITE_PLOT_CAPACITY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/restricted_stage_gate_outranks_site_capacity_overflow
    """
    net = _restricted_site_with_two_candidate_series(api)
    validate_error(
        api.create_entry(
            net["series_b_id"],
            factories.entry_payload(net["line_b_id"], net["site_id"], plot_count=12),
            AGRONOMIST_HEADERS,
        ),
        ApiErrorId.SITE_RESTRICTED_STAGE,
        409,
    )
    validate_error(
        api.create_entry(
            net["series_c_id"],
            factories.entry_payload(net["line_c_id"], net["site_id"], plot_count=12),
            AGRONOMIST_HEADERS,
        ),
        ApiErrorId.SITE_PLOT_CAPACITY_EXCEEDED,
        409,
    )

    site = validate_success(api.get_site(net["site_id"], AGRONOMIST_HEADERS))
    assert site["peak_committed_plot_count"] == 51
    assert site["available_plot_count"] == 9
    assert site["capacity_posture"] == CapacityPosture.RESTRICTED
    program = validate_success(api.get_program(net["program_id"], DIRECTOR_HEADERS))
    assert program["committed_plot_count"] == 51
    for series_id in (net["series_b_id"], net["series_c_id"]):
        _rows, meta = validate_paginated(
            api.list_entries(AGRONOMIST_HEADERS, {"trial_series_id": series_id})
        )
        assert meta["total_count"] == 0


def _line_with_no_agreement_and_a_thousand_grams(api):
    """Line SX-7001 holding 1000 g of seed and no stewardship package at all."""
    program_id, objective_id = fixtures.program_with_objective(
        api, program_overrides={"name": "Soy Gate"}
    )
    line = fixtures.create_line(
        api, program_id, objective_id, designation="SX-7001", seed_inventory_g=1000
    )
    return program_id, line["id"]


def _nine_thousand_kg_of_ca_prairie(line_id):
    return factories.lot_payload(
        line_id, "CA_PRAIRIE", [factories.allocation("CA_PRAIRIE", 9000)]
    )


def test_stewardship_gate_answers_before_the_seed_inventory_shortfall(api):
    """
    A reservation needing 243125 g from a line holding 1000 g is refused for the
    missing stewardship package, not for the seed.

    PRD 3.9: "Two regulatory gates precede any arithmetic: the line's
    `stewardship_status` must be `APPROVED`, so both `NOT_REQUIRED` and `PENDING`
    fail with `ERR_STEWARDSHIP_NOT_APPROVED`, and a line whose stewardship has
    been withdrawn fails with `ERR_STEWARDSHIP_SUSPENDED`."
    PRD 3.9: "The fiscal gate is last: `allocated_seed_g` may not exceed the
    line's `seed_inventory_g`, or the reservation is refused with
    `ERR_INSUFFICIENT_SEED_INVENTORY`."

    Design: Difficulty/priority_pair_validation_conflict/stewardship_gate_outranks_insufficient_seed_inventory
    """
    _program_id, line_id = _line_with_no_agreement_and_a_thousand_grams(api)

    validate_error(
        api.create_lot(_nine_thousand_kg_of_ca_prairie(line_id), PLANNER_HEADERS),
        ApiErrorId.STEWARDSHIP_NOT_APPROVED,
        422,
    )


def test_approving_the_package_uncovers_the_seed_shortfall(api):
    """
    Once the agreement is APPROVED the identical body reaches the fiscal rung, and
    neither rejection left a lot or moved the ledger.

    PRD 3.9: "The fiscal gate is last: `allocated_seed_g` may not exceed the
    line's `seed_inventory_g`, or the reservation is refused with
    `ERR_INSUFFICIENT_SEED_INVENTORY`."
    PRD 3.9: "On success the lot is created in `status` `RESERVED` with
    `hold_reason` null, `allocated_seed_g` is debited from the line's
    `seed_inventory_g`, and the line's `reserved_seed_g` and
    `planned_launch_units_bags` together with the programme's
    `pre_commercial_units_bags` are all re-derived."

    Design: Difficulty/priority_pair_validation_conflict/stewardship_gate_outranks_insufficient_seed_inventory
    """
    program_id, line_id = _line_with_no_agreement_and_a_thousand_grams(api)
    validate_error(
        api.create_lot(_nine_thousand_kg_of_ca_prairie(line_id), PLANNER_HEADERS),
        ApiErrorId.STEWARDSHIP_NOT_APPROVED,
        422,
    )

    fixtures.approved_agreement(
        api,
        line_id,
        markets=["CA_PRAIRIE"],
        regulatory_dossier_ref="DOS-2852-06",
        grower_agreement_ref="GA-2852-06",
    )
    # 389 bags demand 243125 g of parent seed; the line holds 1000 g.
    validate_error(
        api.create_lot(_nine_thousand_kg_of_ca_prairie(line_id), PLANNER_HEADERS),
        ApiErrorId.INSUFFICIENT_SEED_INVENTORY,
        409,
    )

    line = validate_success(api.get_line(line_id, DIRECTOR_HEADERS))
    assert line["seed_inventory_g"] == 1000
    assert line["reserved_seed_g"] == 0
    _rows, meta = validate_paginated(api.list_line_lots(line_id, PLANNER_HEADERS))
    assert meta["total_count"] == 0
    program = validate_success(api.get_program(program_id, DIRECTOR_HEADERS))
    assert program["pre_commercial_units_bags"] == 0
