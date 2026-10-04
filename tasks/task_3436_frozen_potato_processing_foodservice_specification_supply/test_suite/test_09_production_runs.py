"""Production runs: stage machine invalid transitions, the per-family yield
constant, line capability, the QA color gate, and rejection byproduct
diversion."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_byproduct_batch,
    deliver_lot,
    make_active_agreement,
    make_run_in_qa_hold,
    make_validated_spec,
    setup_full_pipeline,
    validate_error,
    validate_paginated,
    validate_success,
)

QA = TEST_USERS["qa_lead_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
ACCOUNT = TEST_USERS["account_manager_headers"]


def test_run_advance_from_qa_hold_returns_invalid_stage(api):
    """PRD §3.6: "Advancing from any other stage — including the terminal
    `RELEASED`, `REJECTED`, or `CANCELLED` — is rejected with
    `ERR_RUN_INVALID_STAGE`."
    PRD §3.6: "Three outcomes leave `QA_HOLD`, all gated to that stage
    (`ERR_RUN_INVALID_STAGE` otherwise)."

    Design: Corner/state_machines/run_advance_from_qa_hold_returns_invalid_stage
    """
    world = setup_full_pipeline(api=api)
    run = make_run_in_qa_hold(world["line"]["id"], world["spec"]["id"],
                              world["agreement"]["id"], [world["lot"]["id"]], api=api)
    assert run["status"] == "QA_HOLD"
    assert run["actual_cases"] == 620, "first pass: floor(1000.0 x 0.62)"

    resp = api.advance_run(run["id"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_RUN_INVALID_STAGE)
    assert resp.status_code == 409, "QA_HOLD exits only via qa-release, rework, or reject"

    reread = validate_success(api.get_production_run(run["id"], PLANNER))
    assert reread["status"] == "QA_HOLD"
    assert reread["actual_cases"] == 620


def test_run_actual_cases_uses_the_cut_family_yield_constant(api):
    """PRD §3.6: "On the first pass (`rework_count` zero), the figure is the
    run's `total_input_cwt` multiplied by the yield for its cut family — 0.62
    cases per hundredweight for `STRAIGHT`, 0.58 for `CRINKLE`, 0.66 for
    `WEDGE`, and 0.55 for `SHOESTRING` — rounded down to whole cases."

    Design: Corner/calculations/run_actual_cases_uses_the_cut_family_yield_constant
    """
    world = setup_full_pipeline(
        api=api,
        spec_overrides={"spec_code": "SP-A-CR", "cut_family": "CRINKLE", "cut_size_mm": 10.0,
                        "coating_type": "SEASONED", "target_color_units": 2.0,
                        "max_cook_time_sec": 210},
    )
    run = make_run_in_qa_hold(world["line"]["id"], world["spec"]["id"],
                              world["agreement"]["id"], [world["lot"]["id"]], api=api)
    assert run["cut_family"] == "CRINKLE"
    assert run["actual_cases"] == 580, (
        f"floor(1000.0 x 0.58 CRINKLE) = 580, not the STRAIGHT 620; got {run['actual_cases']}"
    )


def test_run_create_with_unsupported_cut_family_returns_409(api):
    """PRD §3.6: "The specification must be `LOCKED` (`ERR_SPEC_NOT_LOCKED`),
    and the specification's `cut_family` must appear among the line's
    `supported_cut_families` (`ERR_CUT_FAMILY_UNSUPPORTED`)."

    Design: Corner/errors/run_create_with_unsupported_cut_family_returns_409
    """
    world = setup_full_pipeline(api=api)  # LINE-1 supports STRAIGHT and CRINKLE
    spec_w = make_validated_spec(world["chain"]["id"], api=api, spec_code="SP-A-W",
                                 cut_family="WEDGE", cut_size_mm=12.0, coating_type="NONE",
                                 target_color_units=3.0, max_cook_time_sec=240)
    agr_w = make_active_agreement(world["chain"]["id"], spec_w["id"], api=api,
                                  weekly_contracted_cases=5000)

    resp = api.create_production_run(
        {
            "line_id": world["line"]["id"], "spec_id": spec_w["id"],
            "agreement_id": agr_w["id"], "input_lot_ids": [world["lot"]["id"]],
            "scheduled_start": "2026-09-02T08:00:00Z", "scheduled_end": "2026-09-02T10:00:00Z",
        },
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_CUT_FAMILY_UNSUPPORTED)
    assert resp.status_code == 409

    lot = validate_success(api.get_potato_lot(world["lot"]["id"], QA))
    assert lot["status"] == "IN_STORAGE", "a rejected creation must not allocate the lot"
    runs, _ = validate_paginated(api.list_production_runs(PLANNER, params={"line_id": world["line"]["id"]}))
    assert runs == []


def test_qa_release_color_tolerance_half_unit_inclusive(api):
    """PRD §3.6: "Releasing the run requires a `measured_color_units` reading
    whose absolute difference from the specification's `target_color_units` is
    at most 0.5 (`ERR_COLOR_OUT_OF_TOLERANCE`, HTTP 422, otherwise)".

    Design: Corner/calculations/qa_release_color_tolerance_half_unit_inclusive
    """
    world = setup_full_pipeline(api=api)  # spec target_color_units 2.5
    lot_b = deliver_lot(world["contract"]["id"], world["facility"]["id"],
                        world["grower"]["id"], api=api)
    run1 = make_run_in_qa_hold(world["line"]["id"], world["spec"]["id"],
                               world["agreement"]["id"], [world["lot"]["id"]], api=api)
    run2 = make_run_in_qa_hold(world["line"]["id"], world["spec"]["id"],
                               world["agreement"]["id"], [lot_b["id"]], api=api,
                               scheduled_start="2026-09-02T10:00:00Z",
                               scheduled_end="2026-09-02T11:00:00Z")

    released = validate_success(
        api.qa_release_run(run1["id"], {"measured_color_units": 3.0}, QA)
    )
    assert released["status"] == "RELEASED", "|3.0 - 2.5| = 0.5 is inside the inclusive tolerance"

    resp = api.qa_release_run(run2["id"], {"measured_color_units": 3.01}, QA)
    validate_error(resp, ApiErrorId.ERR_COLOR_OUT_OF_TOLERANCE)
    assert resp.status_code == 422, "|3.01 - 2.5| = 0.51 exceeds the half unit"
    reread = validate_success(api.get_production_run(run2["id"], QA))
    assert reread["status"] == "QA_HOLD"


def test_run_reject_diverts_output_to_condemned_waste_batch(api):
    """PRD §3.6: "Rejecting the run requires a `disposition` of
    `CONDEMNED_WASTE` or `CATTLE_FEED` (any other value, including
    `STARCH_RECOVERY`, is `ERR_INVALID_REQUEST`); the run moves to `REJECTED`,
    its input lots are likewise consumed, and the system books a
    `ByproductBatch` with `stream` `REJECTED_PRODUCT`, `routing` copied from
    the disposition, `weight_cwt` equal to the run's `total_input_cwt`, and
    `source_run_id` pointing at the run (with `source_lot_id` null)."
    PRD §3.3: "The batch's `unit_revenue_cents_per_cwt` follows a fixed tariff
    by routing: 900 cents per hundredweight for `CATTLE_FEED`, 1,400 for
    `STARCH_RECOVERY`, and 0 for `CONDEMNED_WASTE`."

    Design: Corner/endpoints/run_reject_diverts_output_to_condemned_waste_batch
    """
    world = setup_full_pipeline(api=api)
    run = make_run_in_qa_hold(world["line"]["id"], world["spec"]["id"],
                              world["agreement"]["id"], [world["lot"]["id"]], api=api)
    assert run["actual_cases"] == 620

    rejected = validate_success(
        api.reject_run(run["id"], {"disposition": "CONDEMNED_WASTE"}, QA)
    )
    assert rejected["status"] == "REJECTED"

    rows, _ = validate_paginated(
        api.list_byproduct_batches(QA, params={"source_run_id": run["id"]})
    )
    assert len(rows) == 1
    batch = rows[0]
    assert_byproduct_batch(batch)
    assert batch["stream"] == "REJECTED_PRODUCT"
    assert batch["routing"] == "CONDEMNED_WASTE"
    assert batch["weight_cwt"] == 1000.0, "the batch carries the run's whole input mass"
    assert batch["total_revenue_cents"] == 0

    lot = validate_success(api.get_potato_lot(world["lot"]["id"], QA))
    assert lot["status"] == "CONSUMED"

    agreement = validate_success(api.get_supply_agreement(world["agreement"]["id"], ACCOUNT))
    assert agreement["lifetime_released_cases"] == 0, "rejected output never enters inventory"
