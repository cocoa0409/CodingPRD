"""
Optimistic concurrency on the two endpoints that burn the very version they
guard, and the immediate-consistency promise measured against the write response
that caused it.
"""

from test_helpers import (
    ANALYST_HEADERS,
    AGRONOMIST_HEADERS,
    DIRECTOR_HEADERS,
    AnalysisVariant,
    ApiErrorId,
    CapacityPosture,
    DecisionType,
    EntryStatus,
    PipelineStage,
    SeriesStatus,
    approx2,
    approx3,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


def _data_complete_series_with_two_entries(api, site_overrides=None):
    """
    Lines SX-1001 and SX-1002 in one STAGE_1 series of three replications, each
    holding nine plots at one site, observed at 15.0 and 14.0 and both finalised
    so the series has bubbled up to DATA_COMPLETE.
    """
    program_id, objective_id = fixtures.program_with_objective(
        api, objective_overrides={"quality_trait_specs": {"PROTEIN_MIN": 13.0}}
    )
    line_a = fixtures.create_line_a(api, program_id, objective_id)
    line_b = fixtures.create_line_b(api, program_id, objective_id)
    site = fixtures.create_site(api, **(site_overrides or {"site_code": "OC2"}))
    series = fixtures.create_series(
        api, program_id, replication_count=3, min_locations=1
    )
    entry_a = fixtures.create_entry(
        api, series["id"], line_a["id"], site["id"], plot_count=9
    )
    entry_b = fixtures.create_entry(
        api, series["id"], line_b["id"], site["id"], plot_count=9
    )
    fixtures.plant_series(api, series["id"])
    fixtures.record_yield_reps(api, entry_a["id"], [15.0, 15.0, 15.0])
    fixtures.record_yield_reps(api, entry_b["id"], [14.0, 14.0, 14.0])
    fixtures.finalize_entry(api, entry_a["id"])
    fixtures.finalize_entry(api, entry_b["id"])
    return {
        "program_id": program_id,
        "objective_id": objective_id,
        "line_a_id": line_a["id"],
        "line_b_id": line_b["id"],
        "site_id": site["id"],
        "series_id": series["id"],
        "entry_a_id": entry_a["id"],
        "entry_b_id": entry_b["id"],
    }


def test_a_replayed_line_version_is_refused_before_the_advance_is_even_weighed(api):
    """
    The HOLD that was just recorded burned the version the client is holding, so
    replaying it on an ADVANCE draws a staleness refusal that changes nothing at
    all, and the same body with the refreshed version is accepted.

    PRD 2.9: "The first is **recording an advancement decision**. The request must
    carry `expected_line_version` as a required field holding the client's last
    observed `version` of the target `BreedingLine`. If that value does not equal
    the line's current `version`, the request is rejected with
    `ERR_STALE_LINE_VERSION` and HTTP 412."
    PRD 2.9: "Both checks sit early in the ladder of §2.7, at steps 7 and 8, ahead
    of every state and business rule. A stale write is therefore reported as a
    staleness failure rather than as whatever downstream conflict it would have
    caused."
    PRD 3.8: "In every branch, any earlier decision for the same combination of
    `line_id` and `trial_series_id` has `is_superseded` set to true and its
    `granted_plots` released from the programme's `committed_plot_count`, the
    line's `version` increments by one and its `updated_at` is refreshed, and the
    cited series must be `ANALYZED` — a decision resting on unanalysed data is
    refused with `ERR_SERIES_INVALID_STATE`."

    Design: Corner/cross_cutting_complexity_layers/decision_writes_reject_a_stale_line_version_and_accept_the_fresh_one
    """
    net = _data_complete_series_with_two_entries(api)
    fixtures.run_analysis(
        api, net["series_id"], variant=AnalysisVariant.BALANCED_CORE
    )

    first_version = api.line_version(net["line_a_id"], DIRECTOR_HEADERS)
    hold = validate_success(
        api.create_decision(
            factories.decision_payload(
                net["line_a_id"],
                net["series_id"],
                first_version,
                decision=DecisionType.HOLD,
                granted_plots=0,
                rationale="quality data pending",
            ),
            DIRECTOR_HEADERS,
        ),
        201,
    )
    assert hold["is_superseded"] is False
    second_version = api.line_version(net["line_a_id"], DIRECTOR_HEADERS)
    assert second_version == first_version + 1

    advance_body = factories.decision_payload(
        net["line_a_id"],
        net["series_id"],
        first_version,
        decision=DecisionType.ADVANCE,
        granted_plots=60,
        rationale="promote to stage 1",
    )
    validate_error(
        api.create_decision(advance_body, DIRECTOR_HEADERS),
        ApiErrorId.STALE_LINE_VERSION,
        412,
    )

    # The refusal is a pure no-op: nothing was superseded, moved or booked.
    still_current = validate_success(api.get_decision(hold["id"], DIRECTOR_HEADERS))
    assert still_current["is_superseded"] is False
    line = validate_success(api.get_line(net["line_a_id"], DIRECTOR_HEADERS))
    assert line["pipeline_stage"] == PipelineStage.NURSERY
    assert line["version"] == second_version
    program = validate_success(api.get_program(net["program_id"], DIRECTOR_HEADERS))
    assert program["committed_plot_count"] == 18

    advance_body["expected_line_version"] = second_version
    advance = validate_success(
        api.create_decision(advance_body, DIRECTOR_HEADERS), 201
    )
    assert advance["granted_plots"] == 60
    assert advance["from_stage"] == PipelineStage.NURSERY
    assert advance["to_stage"] == PipelineStage.STAGE_1
    # The provisional 104.55 discounted by the NURSERY confidence factor of 0.90.
    assert advance["decision_index_value"] == approx2(94.10)
    assert advance["is_superseded"] is False

    superseded = validate_success(api.get_decision(hold["id"], DIRECTOR_HEADERS))
    assert superseded["is_superseded"] is True
    rows, meta = validate_paginated(
        api.list_decisions(DIRECTOR_HEADERS, {"line_id": net["line_a_id"]})
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2
    after = validate_success(api.get_line(net["line_a_id"], DIRECTOR_HEADERS))
    assert after["version"] == second_version + 1
    assert after["pipeline_stage"] == PipelineStage.STAGE_1
    closing = validate_success(api.get_program(net["program_id"], DIRECTOR_HEADERS))
    assert closing["committed_plot_count"] == 78


def test_the_analysis_guard_is_per_series_so_the_other_variant_is_stale_too(api):
    """
    Publishing one variant advances the series version, so the second variant
    submitted with the version that was valid a moment earlier is refused even
    though it would have superseded nothing, and the refusal writes no row.

    PRD 2.9: "The second is **creating a trial series analysis**. The request must
    carry `expected_series_version` as a required field holding the client's last
    observed `version` of the target `TrialSeries`. If that value does not equal
    the series' current `version`, the request is rejected with
    `ERR_STALE_SERIES_VERSION` and HTTP 412."
    PRD 3.7: "The series moves to `ANALYZED` (from `DATA_COMPLETE`, or remaining
    there if it was already `ANALYZED`) and its `version` increments by one, which
    is why a second analyst working from a stale read is turned away."
    PRD 3.7: "Every earlier analysis of this series with the **same** `variant`
    has its `is_superseded` set to true, so at most one analysis of each variant
    is ever current — analyses of the other variant are untouched."

    Design: Corner/cross_cutting_complexity_layers/analysis_writes_reject_a_version_the_previous_analysis_already_burned
    """
    net = _data_complete_series_with_two_entries(api)
    opening = validate_success(api.get_series(net["series_id"], ANALYST_HEADERS))
    assert opening["status"] == SeriesStatus.DATA_COMPLETE
    first_version = opening["version"]

    first = validate_success(
        api.create_analysis(
            net["series_id"],
            factories.analysis_payload(
                first_version, variant=AnalysisVariant.BALANCED_CORE
            ),
            ANALYST_HEADERS,
        ),
        201,
    )
    assert first["is_superseded"] is False
    analyzed = validate_success(api.get_series(net["series_id"], ANALYST_HEADERS))
    assert analyzed["status"] == SeriesStatus.ANALYZED
    second_version = analyzed["version"]
    assert second_version == first_version + 1
    line = validate_success(api.get_line(net["line_a_id"], ANALYST_HEADERS))
    assert line["advancement_index_provisional"] == approx2(104.55)

    validate_error(
        api.create_analysis(
            net["series_id"],
            factories.analysis_payload(
                first_version, variant=AnalysisVariant.UNBALANCED_INCLUSIVE
            ),
            ANALYST_HEADERS,
        ),
        ApiErrorId.STALE_SERIES_VERSION,
        412,
    )
    rows, meta = validate_paginated(
        api.list_analyses(net["series_id"], ANALYST_HEADERS, {"limit": 50})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]
    unmoved = validate_success(api.get_series(net["series_id"], ANALYST_HEADERS))
    assert unmoved["version"] == second_version
    assert unmoved["status"] == SeriesStatus.ANALYZED

    rerun = validate_success(
        api.create_analysis(
            net["series_id"],
            factories.analysis_payload(
                second_version, variant=AnalysisVariant.BALANCED_CORE
            ),
            ANALYST_HEADERS,
        ),
        201,
    )
    assert rerun["is_superseded"] is False
    rows, meta = validate_paginated(
        api.list_analyses(net["series_id"], ANALYST_HEADERS, {"limit": 50})
    )
    assert meta["total_count"] == 2
    by_id = {row["id"]: row for row in rows}
    assert by_id[first["id"]]["is_superseded"] is True
    assert by_id[rerun["id"]]["is_superseded"] is False
    for row in rows:
        assert row["variant"] == AnalysisVariant.BALANCED_CORE
    closing = validate_success(api.get_series(net["series_id"], ANALYST_HEADERS))
    assert closing["version"] == second_version + 1
    # The refused run never touched the line; the accepted re-run recomputed the
    # same figure over the same inclusion set.
    after = validate_success(api.get_line(net["line_a_id"], ANALYST_HEADERS))
    assert after["advancement_index_provisional"] == approx2(104.55)


def test_every_derived_figure_is_already_current_in_the_write_that_caused_it(api):
    """
    The finalisation response itself carries the finished rollup, and the entry,
    the series, the site and the programme all read their post-write values on the
    very next request, with no second write and nothing left to settle.

    PRD 2.10: "Consistency is immediate: by the time a response is returned, every
    counter, posture and parent status the write affects has already been
    re-derived, and a subsequent read observes the new values."
    PRD 3.6: "Then — and the order matters — that already-rounded three-decimal
    mean is scaled to a per-hectare figure and rounded again: `yield_kg_per_ha` is
    `plot_mean_yield_kg` multiplied by 800, rounded half up to two decimals."
    PRD 3.6: "After a finalisation, a withdrawal or an invalidation, the server
    re-evaluates the parent series: when the series is `PLANTED`, no entry of the
    series is left in `status` `PLANTED`, and at least one entry of the series has
    reached `HARVESTED`, the series auto-transitions `PLANTED → DATA_COMPLETE` and
    its `version` advances."
    PRD 3.5: "The site's **capacity posture** is derived from utilisation, defined
    as `peak_committed_plot_count` divided by `total_plot_capacity` and compared as
    an exact decimal ratio rather than as a floating-point approximation."
    PRD 3.6: "Second, a management tier is selected from that subtotal **and from
    nothing else**: the rate is 0.12 when `plot_cost_subtotal_usd` is strictly
    below 10000.00, 0.09 when it is strictly below 50000.00, and 0.07 otherwise."

    Design: Corner/consistency_model/every_derived_field_is_current_in_the_response_that_caused_it
    """
    program_id, objective_id = fixtures.program_with_objective(api)
    line_a = fixtures.create_line_a(api, program_id, objective_id)
    line_b = fixtures.create_line_b(api, program_id, objective_id)
    site = fixtures.create_site(api, site_code="IC1", total_plot_capacity=100)
    series = fixtures.create_series(
        api, program_id, replication_count=3, min_locations=1
    )
    entry_a = fixtures.create_entry(
        api, series["id"], line_a["id"], site["id"], plot_count=9
    )
    fixtures.create_entry(api, series["id"], line_b["id"], site["id"], plot_count=9)
    fixtures.plant_series(api, series["id"])
    fixtures.record_yield_reps(api, entry_a["id"], [14.1, 14.2, 14.4])

    finalized = validate_success(
        api.finalize_entry(entry_a["id"], AGRONOMIST_HEADERS)
    )
    assert finalized["status"] == EntryStatus.HARVESTED
    assert finalized["valid_rep_count"] == 3
    # 42.7 / 3 rounds to 14.233 first, and only then is scaled by 800.
    assert finalized["plot_mean_yield_kg"] == approx3(14.233)
    assert finalized["yield_kg_per_ha"] == approx2(11386.40)

    reread = validate_success(api.get_entry(entry_a["id"], ANALYST_HEADERS))
    assert reread["valid_rep_count"] == finalized["valid_rep_count"]
    assert reread["plot_mean_yield_kg"] == finalized["plot_mean_yield_kg"]
    assert reread["yield_kg_per_ha"] == finalized["yield_kg_per_ha"]
    assert reread["status"] == finalized["status"]

    # The second entry is still PLANTED, so the bubble-up has correctly not fired.
    parent = validate_success(api.get_series(series["id"], ANALYST_HEADERS))
    assert parent["entry_count"] == 2
    assert parent["location_count"] == 1
    assert parent["status"] == SeriesStatus.PLANTED

    host = validate_success(api.get_site(site["id"], AGRONOMIST_HEADERS))
    assert host["peak_committed_plot_count"] == 18
    assert host["available_plot_count"] == 82
    # 18 of 100 plots is a utilisation of 0.18, well below the 0.85 rung.
    assert host["capacity_posture"] == CapacityPosture.OPEN

    program = validate_success(api.get_program(program_id, DIRECTOR_HEADERS))
    assert program["committed_plot_count"] == 18
    assert program["plot_budget_remaining"] == 4982
    # 18 plots at 45.00 is a subtotal of 810.00, which takes the 0.12 tier for a
    # 97.20 fee and a 907.20 total.
    assert program["committed_budget_usd"] == approx2(907.20)
