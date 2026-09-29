"""
The refusal itself as the object under test: one envelope shape and four declared
statuses across four different rungs, and a late rung that must leave nothing of
the write it refused.

"""

from test_helpers import (
    ANALYST_HEADERS,
    DIRECTOR_HEADERS,
    SCIENTIST_HEADERS,
    NON_EXISTENT_UUID,
    AnalysisVariant,
    ApiErrorId,
    DecisionType,
    PipelineStage,
    approx2,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_four_rungs_produce_four_statuses_inside_one_envelope(api):
    """
    A shape failure, a path failure, a conflict and a business-rule refusal each
    serialise identically — `data.error_id` with a human-readable
    `data.message`, and a `meta` carrying only the two request fields — and none of
    them leaves a record behind.

    PRD 2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error."
    PRD 2.2: "The `message` provides a human-readable explanation of what went
    wrong."
    PRD 2.7: "Any failure here is `ERR_INVALID_REQUEST` (400). Applies to every
    endpoint."
    PRD 3.3: "Because the intervals are half-open, touching endpoints do not
    conflict: a new planting whose `sow_date` equals an existing planting's
    `occupancy_end_date` is admitted, since the fallow period has just expired. Any
    genuine overlap is refused with `ERR_BLOCK_OCCUPANCY_CONFLICT`."

    Design: Corner/errors/every_refusal_uses_the_declared_error_envelope_and_status
    """
    program_id, objective_id = fixtures.program_with_objective(api)
    line = fixtures.create_line(api, program_id, objective_id, designation="SX-1001")
    block = fixtures.create_nursery_block(api, block_code="NB-EV1")
    first = fixtures.create_planting(
        api, block["id"], line["id"], sow_date="2026-10-05",
        expected_harvest_date="2027-02-10", plot_count=20,
    )
    assert first["occupancy_end_date"] == "2027-02-24"

    malformed = factories.line_payload(
        program_id, objective_id, designation="SX-1002"
    )
    malformed.pop("designation")
    shape = api.create_line(malformed, SCIENTIST_HEADERS)
    body = validate_error(shape, ApiErrorId.INVALID_REQUEST, 400)
    assert isinstance(body["message"], str)
    assert body["message"].strip() != ""

    missing = api.get_line(NON_EXISTENT_UUID, ANALYST_HEADERS)
    validate_error(missing, ApiErrorId.LINE_NOT_FOUND, 404)

    # 2027-02-23 is the last day of the fallow tail that ends 2027-02-24.
    overlap = api.create_planting(
        factories.planting_payload(
            block["id"], line["id"], sow_date="2027-02-23",
            expected_harvest_date="2027-06-20", plot_count=20,
        ),
        SCIENTIST_HEADERS,
    )
    validate_error(overlap, ApiErrorId.BLOCK_OCCUPANCY_CONFLICT, 409)

    # January is a WINTER-legal month, but 2026-01-15 is behind the clock.
    past = api.create_planting(
        factories.planting_payload(
            block["id"], line["id"], sow_date="2026-01-15",
            expected_harvest_date="2026-05-20", plot_count=20,
        ),
        SCIENTIST_HEADERS,
    )
    validate_error(past, ApiErrorId.SOW_DATE_IN_PAST, 422)

    for response in (shape, missing, overlap, past):
        payload = response.json()
        assert set(payload["meta"]) == {"api_request_id", "api_request_timestamp"}
        assert payload["meta"]["api_request_id"].startswith("req_")
        assert payload["meta"]["api_request_timestamp"].endswith("Z")
        assert set(payload["data"]) == {"error_id", "message"}
        for forbidden in ("error", "code", "errors"):
            assert forbidden not in payload

    _rows, meta = validate_paginated(
        api.list_plantings(SCIENTIST_HEADERS, {"nursery_block_id": block["id"]})
    )
    assert meta["total_count"] == 1
    program = validate_success(api.get_program(program_id, DIRECTOR_HEADERS))
    assert program["committed_plot_count"] == 20
    # The malformed create left no partial line behind.
    assert program["active_line_count"] == 1


def test_the_index_refusal_leaves_the_earlier_hold_and_every_counter_alone(api):
    """
    The refused advance would have superseded the standing hold, bumped the line's
    version, moved its stage and charged sixty plots; because the index rung
    refuses, none of those consequences may be observable — the supersession being
    the one an implementation is most likely to have applied already.

    PRD 2.10: "Almost every write in this API has secondary consequences, and the
    specification treats those consequences as part of the operation rather than as
    eventual housekeeping."
    PRD 2.10: "A programme's plot and cash commitments, a nursery block's
    occupancy, a site's peak occupancy and posture, a series' entry and location
    census, an entry's replication census and yield rollup, a line's readiness, seed
    ledger and provisional index — all of these are computed by the server from the
    records that justify them, and a value supplied for such a field in a request
    body is ignored."
    PRD 3.8: "Every rung additionally requires that the frozen CUMULATIVE index
    reach the objective's `min_advancement_index`, failing which the decision is
    refused with `ERR_INDEX_BELOW_THRESHOLD`, and that `granted_plots` fit inside
    the programme's `plot_budget_remaining`, failing which it is refused with
    `ERR_PROGRAM_PLOT_BUDGET_EXCEEDED`."
    PRD 3.8: "In every branch, any earlier decision for the same combination of
    `line_id` and `trial_series_id` has `is_superseded` set to true and its
    `granted_plots` released from the programme's `committed_plot_count`, the line's
    `version` increments by one and its `updated_at` is refreshed, and the cited
    series must be `ANALYZED` — a decision resting on unanalysed data is refused
    with `ERR_SERIES_INVALID_STATE`."

    Design: Corner/errors/a_late_rung_refusal_rolls_back_every_earlier_side_effect
    """
    program_id, objective_id = fixtures.program_with_objective(
        api,
        objective_overrides={
            "quality_trait_specs": {"PROTEIN_MIN": 13.0},
            "min_advancement_index": 100.00,
        },
    )
    line_a = fixtures.create_line_a(api, program_id, objective_id)
    line_b = fixtures.create_line_b(api, program_id, objective_id)
    site = fixtures.create_site(api, site_code="AT1")
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
    fixtures.run_analysis(api, series["id"], variant=AnalysisVariant.BALANCED_CORE)

    hold = fixtures.record_decision(
        api, line_a["id"], series["id"], decision=DecisionType.HOLD,
        granted_plots=0, rationale="hold pending the second location",
    )
    assert hold["is_superseded"] is False
    before = validate_success(api.get_line(line_a["id"], DIRECTOR_HEADERS))

    # The frozen cumulative index is 104.55 * 0.90 against a 100.00 bar.
    validate_error(
        api.create_decision(
            factories.decision_payload(
                line_a["id"], series["id"], before["version"],
                decision=DecisionType.ADVANCE, granted_plots=60,
                rationale="push it through",
            ),
            DIRECTOR_HEADERS,
        ),
        ApiErrorId.INDEX_BELOW_THRESHOLD,
        422,
    )

    still_standing = validate_success(api.get_decision(hold["id"], DIRECTOR_HEADERS))
    assert still_standing["is_superseded"] is False
    rows, meta = validate_paginated(
        api.list_decisions(DIRECTOR_HEADERS, {"line_id": line_a["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["decision"] == DecisionType.HOLD

    after = validate_success(api.get_line(line_a["id"], DIRECTOR_HEADERS))
    assert after["version"] == before["version"]
    assert after["pipeline_stage"] == PipelineStage.NURSERY
    assert after["advancement_index_provisional"] == approx2(104.55)
    program = validate_success(api.get_program(program_id, DIRECTOR_HEADERS))
    # The 60 requested plots were never charged against the 18 already committed.
    assert program["committed_plot_count"] == 18
    assert program["plot_budget_remaining"] == 4982
