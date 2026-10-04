"""Assortment specs and the production pipeline."""
import test_helpers.fixtures as fx
from test_helpers import (
    api_client, ApiErrorId, validate_success, validate_error, validate_paginated,
    get_success_data, assert_assortment_spec, assert_production_run,
    NON_EXISTENT_UUID,
)

ADMIN = fx.ADMIN


def test_spec_box_size_computed_and_client_input_ignored(api):
    """PRD section 3.4: "From the entries the system computes `box_size` as the
    sum of the entry counts" and PRD section 2.8 stage 3: "Undeclared extra
    fields are ignored: never echoed, never stored." PRD section 3.4: "A new
    spec is `ACTIVE` with `boxes_available` and `boxes_reserved` both 0."

    Design: Corner/entities/spec_box_size_computed_and_client_input_ignored
    """
    fx.reset_clock()
    color = fx.make_active_color()
    resp = api_client.create_assortment_spec(
        {"name": "Cerulean 8-box", "kind": "RETAIL",
         "entries": [{"color_id": color["id"], "count": 8}],
         "wholesale_price_cents": 1600, "box_size": 64},
        ADMIN)
    data = validate_success(resp, 201)
    assert_assortment_spec(data)
    assert data["box_size"] == 8  # computed from entries; the supplied 64 ignored
    assert data["status"] == "ACTIVE"
    assert data["boxes_available"] == 0
    assert data["boxes_reserved"] == 0


def test_spec_create_with_out_of_set_box_size_is_rejected(api):
    """PRD section 3.4: "the sum must be one of 8, 16, 24, or 64 — any other
    total is likewise `ERR_SPEC_INVALID`."

    Design: Corner/entities/spec_create_with_out_of_set_box_size_is_rejected
    """
    fx.reset_clock()
    color = fx.make_active_color()
    resp = api_client.create_assortment_spec(
        {"name": "Tiny 3-box", "kind": "RETAIL",
         "entries": [{"color_id": color["id"], "count": 3}],
         "wholesale_price_cents": 600},
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_SPEC_INVALID)
    assert resp.status_code == 409
    # nothing persisted: a subsequently created valid spec succeeds
    ok = api_client.create_assortment_spec(
        {"name": "Cerulean 8-box", "kind": "RETAIL",
         "entries": [{"color_id": color["id"], "count": 8}],
         "wholesale_price_cents": 1600},
        ADMIN)
    validate_success(ok, 201)


def test_classroom_spec_missing_core_color_is_rejected(api):
    """PRD section 3.4: "a `CLASSROOM` spec must include every `ACTIVE`
    core-curriculum color" — violations are rejected as `ERR_SPEC_INVALID`
    (HTTP 409).

    Design: Corner/errors/classroom_spec_missing_core_color_is_rejected
    """
    fx.reset_clock()
    core = fx.make_active_color("Cerulean", "#02A4D3", True)
    non_core = fx.make_active_color(
        "Denim", "#1560BD", None,
        opens="2026-09-25T00:00:00Z", closes="2026-10-10T23:59:59Z",
        open_clock="2026-09-26T00:00:00Z", close_clock="2026-10-11T00:00:00Z")
    resp = api_client.create_assortment_spec(
        {"name": "Classroom 24-box", "kind": "CLASSROOM",
         "partner_name": "CrayonEdu Partners",
         "entries": [{"color_id": non_core["id"], "count": 24}],
         "wholesale_price_cents": 4800},
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_SPEC_INVALID)
    assert resp.status_code == 409


def test_spec_deprecated_blocks_new_runs(api):
    """PRD section 3.4: "the spec must be `ACTIVE`, else `ERR_SPEC_DEPRECATED`"
    and "the moment any entry color becomes `RETIRED` or `ARCHIVED`, the spec
    becomes `DEPRECATED`, recomputed on every color status change — this is
    the cascade the retirement of §3.1 sets in motion, and deprecation is
    the single gate through which retired colors block new production."

    Design: Corner/errors/spec_deprecated_blocks_new_runs
    """
    fx.reset_clock()
    env = fx.production_setup()
    fx.retire_color(env["color"]["id"])
    spec = fx.get_spec(env["spec"]["id"])
    assert spec["status"] == "DEPRECATED"
    resp = api_client.create_production_run(
        {"assortment_spec_id": env["spec"]["id"],
         "pigment_batch_id": env["batch"]["id"], "planned_boxes": 40,
         "planned_start_date": "2027-04-15T00:00:00Z",
         "planned_end_date": "2027-05-20T00:00:00Z"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_SPEC_DEPRECATED)
    assert resp.status_code == 409


def test_run_create_with_unknown_spec_id_returns_not_found(api):
    """PRD section 2.8 stage 4: "Path identifiers must exist first; then body
    foreign keys are checked in the endpoint's declared input order, left to
    right. The first missing reference yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/run_create_with_unknown_spec_id_returns_not_found
    """
    fx.reset_clock()
    resp = api_client.create_production_run(
        {"assortment_spec_id": "00000000-0000-4000-8000-000000000001",
         "pigment_batch_id": "00000000-0000-4000-8000-000000000002",
         "planned_boxes": 10, "planned_start_date": "2027-04-15T00:00:00Z",
         "planned_end_date": "2027-05-20T00:00:00Z"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert resp.status_code == 404


def test_run_planned_start_within_lead_time_returns_too_soon(api):
    """PRD section 2.10: "a run's `planned_start_date` must be no earlier than
    sixty days after the current logical clock value, or creation is rejected
    with `ERR_PLANNED_START_TOO_SOON` (HTTP 422)." — at clock 2026-09-21 the
    earliest legal start is 2026-11-20.

    Design: Corner/validations/run_planned_start_within_lead_time_returns_too_soon
    """
    fx.reset_clock()
    env = fx.production_setup()  # clock ends at 2026-09-21T00:00:00Z
    resp = api_client.create_production_run(
        {"assortment_spec_id": env["spec"]["id"],
         "pigment_batch_id": env["batch"]["id"], "planned_boxes": 10,
         "planned_start_date": "2026-10-15T00:00:00Z",
         "planned_end_date": "2026-11-15T00:00:00Z"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PLANNED_START_TOO_SOON)
    assert resp.status_code == 422
    data, meta = validate_paginated(api_client.list_production_runs(ADMIN))
    assert data == []


def test_run_advances_molding_labeling_packing_completed(api):
    """PRD section 3.4: "The run's `stage` walks `PLANNED`, `MOLDING`,
    `LABELING`, `PACKING`, `COMPLETED` through successive advances" and PRD
    section 2.5: "`version` (integer): starts at 1 when the resource
    is created and increments by exactly 1 on every mutation."

    Design: Corner/state_machines/run_advances_molding_labeling_packing_completed
    """
    fx.reset_clock()
    env = fx.production_setup()
    run = fx.create_run(env["spec"]["id"], env["batch"]["id"])
    stages = []
    for _ in range(3):
        stages.append(fx.advance_run(run["id"])["stage"])
    final = fx.complete_run(run["id"], [{"color_id": env["color"]["id"], "count": 1000}])
    stages.append(final["stage"])
    assert stages == ["MOLDING", "LABELING", "PACKING", "COMPLETED"]
    assert final["version"] == 5  # create plus four transitions
    assert final["boxes_produced"] == 125
    assert final["waste_units"] == 0
    assert final["packing_penalty_cents"] == 0


def test_run_cancel_from_labeling_then_advance_is_rejected(api):
    """PRD section 3.4: "`CANCEL` terminates a run from `PLANNED`, `MOLDING`,
    `LABELING`, `PACKING`, or `ON_HOLD` into `CANCELLED`" and "any other action
    disallowed from the current stage is rejected with `ERR_RUN_STAGE_INVALID`
    (HTTP 409)" — including CANCEL from COMPLETED, since "recall quarantine
    (§3.2) remains its only exit".

    Design: Corner/state_machines/run_cancel_from_labeling_then_advance_is_rejected
    """
    fx.reset_clock()
    env = fx.production_setup_with_completed_run(packed_units=16, planned_boxes=2)
    r2 = env["run"]  # COMPLETED
    r1 = fx.create_run(env["spec"]["id"], env["batch"]["id"])
    fx.advance_run(r1["id"])
    fx.advance_run(r1["id"])  # LABELING
    cancelled = get_success_data(
        api_client.production_run_transition(r1["id"], {"action": "CANCEL"}, ADMIN))
    assert cancelled["stage"] == "CANCELLED"
    resp1 = api_client.production_run_transition(r1["id"], {"action": "ADVANCE"}, ADMIN)
    validate_error(resp1, ApiErrorId.ERR_RUN_STAGE_INVALID)
    resp2 = api_client.production_run_transition(r2["id"], {"action": "CANCEL"}, ADMIN)
    validate_error(resp2, ApiErrorId.ERR_RUN_STAGE_INVALID)
    assert resp2.status_code == 409


def test_run_advance_from_on_hold_is_rejected(api):
    """PRD section 3.4: "Attempting to advance a run that is `ON_HOLD` is
    rejected with `ERR_RUN_ON_HOLD` (HTTP 409) — the run must be resumed first"
    and "`RESUME` returns an `ON_HOLD` run to exactly the stage recorded in
    `stage_before_hold` and clears both `stage_before_hold` and `hold_reason` to
    null."

    Design: Corner/state_machines/run_advance_from_on_hold_is_rejected
    """
    fx.reset_clock()
    env = fx.production_setup()
    run = fx.create_run(env["spec"]["id"], env["batch"]["id"])
    fx.advance_run(run["id"])  # MOLDING
    get_success_data(api_client.production_run_transition(run["id"], {"action": "HOLD"}, ADMIN))
    resp = api_client.production_run_transition(run["id"], {"action": "ADVANCE"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_RUN_ON_HOLD)
    assert resp.status_code == 409
    resumed = get_success_data(
        api_client.production_run_transition(run["id"], {"action": "RESUME"}, ADMIN))
    assert resumed["stage"] == "MOLDING"
    assert resumed["stage_before_hold"] is None
    assert resumed["hold_reason"] is None


def test_run_completed_creates_available_inventory_lot(api):
    """PRD section 3.4: "Completion creates an **inventory lot** bound to its
    producing run by `production_run_id`, in `AVAILABLE`, whose `boxes_received`
    and `boxes_on_hand` both equal `boxes_produced`, whose `boxes_committed` and
    `boxes_shipped` start at 0" and "the spec's `boxes_available` is recomputed
    in the same motion."

    Design: Corner/state_machines/run_completed_creates_available_inventory_lot
    """
    fx.reset_clock()
    env = fx.production_setup_with_completed_run()
    lots = fx.list_lots(env["run"]["id"])
    assert len(lots) == 1
    lot = lots[0]
    assert lot["status"] == "AVAILABLE"
    assert lot["boxes_received"] == 125
    assert lot["boxes_on_hand"] == 125
    assert lot["boxes_committed"] == 0
    assert lot["boxes_shipped"] == 0
    assert lot["production_run_id"] == env["run"]["id"]
    spec = fx.get_spec(env["spec"]["id"])
    assert spec["boxes_available"] == 125


def test_production_runs_list_paginates_and_filters(api):
    """PRD section 2.3: "Every list response carries the pagination fields
    `limit`, `offset`, `total_count`, and `has_more` in the `meta` object" and
    PRD section 3.4: the run list "accepts optional `assortment_spec_id`,
    `pigment_batch_id`, and `stage` filters."

    Design: Corner/entities/production_runs_list_paginates_and_filters
    """
    fx.reset_clock()
    env = fx.production_setup()
    for boxes in (125, 6, 25):
        fx.create_run(env["spec"]["id"], env["batch"]["id"], planned_boxes=boxes)
    page1, meta1 = validate_paginated(
        api_client.list_production_runs(ADMIN, params={"stage": "PLANNED", "limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    page2, meta2 = validate_paginated(
        api_client.list_production_runs(ADMIN, params={"stage": "PLANNED", "limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    by_batch, meta3 = validate_paginated(
        api_client.list_production_runs(ADMIN, params={"pigment_batch_id": env["batch"]["id"]}))
    assert len(by_batch) == 3
    none, meta4 = validate_paginated(
        api_client.list_production_runs(ADMIN, params={"pigment_batch_id": NON_EXISTENT_UUID}))
    assert none == []


def test_list_endpoints_apply_pagination_defaults(api):
    """PRD section 2.3: "The `limit` parameter sets the maximum number of items
    returned: it defaults to 10 when omitted, accepts a minimum of 1, and is
    capped at a maximum of 100. The `offset` parameter sets the number of items
    skipped and defaults to 0."

    Design: Corner/endpoints/list_endpoints_apply_pagination_defaults
    """
    fx.reset_clock()
    env = fx.production_setup()
    fx.create_run(env["spec"]["id"], env["batch"]["id"])
    data, meta = validate_paginated(api_client.list_production_runs(ADMIN))
    assert len(data) == 1
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_derived_fields_recomputed_in_same_response(api):
    """PRD section 2.2: "Unless otherwise noted, operations that create or
    modify a resource will return the created or updated resource object in the
    data field." and PRD section 3.4: the completing advance computes
    "`boxes_produced` ... `waste_units` ... `packing_penalty_cents`" — the
    transition's own 200 body already carries the computed values.

    Design: Corner/consistency_model/derived_fields_recomputed_in_same_response
    """
    fx.reset_clock()
    env = fx.production_setup()
    run = fx.create_run(env["spec"]["id"], env["batch"]["id"])
    fx.advance_run_to_packing(run["id"])
    resp = api_client.production_run_transition(
        run["id"], {"action": "ADVANCE",
                    "packed_counts": [{"color_id": env["color"]["id"], "count": 1000}]}, ADMIN)
    data = validate_success(resp, 200)
    assert data["stage"] == "COMPLETED"
    assert data["boxes_produced"] == 125
    assert data["packing_penalty_cents"] == 0
    assert data["waste_units"] == 0


def test_packing_penalty_over_and_under_factors(api):
    """PRD section 3.4: "Each line's penalty is the `UNDER_UNIT_PENALTY_CENTS`
    rate of 18.75 cents per variance unit, multiplied by the `OVER_FACTOR` of
    1.5 on lines packed above expectation, rounded half up to integer cents per
    line and only then summed into `packing_penalty_cents`". 3 over on one line
    costs round(3*18.75*1.5) = 84; 1 under on another costs round(1*18.75) = 19.

    Design: Corner/calculations/packing_penalty_over_and_under_factors
    """
    fx.reset_clock()
    env = fx.two_color_run_at_packing(planned_boxes=10)
    run = fx.complete_run(
        env["run"]["id"],
        [{"color_id": env["color1"]["id"], "count": 83},
         {"color_id": env["color2"]["id"], "count": 79}])
    assert run["stage"] == "COMPLETED"  # total variance 4 <= 5
    assert run["packing_variance_units"] == 4
    assert run["packing_penalty_cents"] == 103  # 84 over-line + 19 under-line
    assert run["boxes_produced"] == 9  # min(floor(83/8), floor(79/8))
    assert run["waste_units"] == 18  # 162 - 9*16


def test_run_create_requires_approved_formula_first(api):
    """PRD section 3.4: "Creation then walks the linked-entity gates in the
    fixed order of §2.8 stage 10: every entry color of the spec must be
    covered by an `APPROVED` formula, else `ERR_FORMULA_NOT_APPROVABLE`; the
    pigment batch must be `CERTIFIED`, else `ERR_BATCH_NOT_CERTIFIED`".

    Design: Difficulty/cross_entity_state_dependency/production_run_requires_approved_formulas_certified_batch_active_spec
    """
    fx.reset_clock()
    color = fx.make_active_color()
    spec = fx.create_spec([{"color_id": color["id"], "count": 8}])
    batch = fx.create_batch()  # still QUARANTINE
    formula = fx.create_formula(color["id"])  # still DRAFT
    resp = api_client.create_production_run(
        {"assortment_spec_id": spec["id"], "pigment_batch_id": batch["id"],
         "planned_boxes": 125, "planned_start_date": "2027-04-15T00:00:00Z",
         "planned_end_date": "2027-05-20T00:00:00Z"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_FORMULA_NOT_APPROVABLE)
    assert resp.status_code == 409
    fx.submit_formula(formula["id"])
    fx.pass_latest_safety_test(formula["id"])
    fx.approve_formula(formula["id"])
    resp2 = api_client.create_production_run(
        {"assortment_spec_id": spec["id"], "pigment_batch_id": batch["id"],
         "planned_boxes": 125, "planned_start_date": "2027-04-15T00:00:00Z",
         "planned_end_date": "2027-05-20T00:00:00Z"}, ADMIN)
    validate_error(resp2, ApiErrorId.ERR_BATCH_NOT_CERTIFIED)


def test_run_create_succeeds_once_formula_approved_and_batch_certified(api):
    """PRD section 3.4: "Against an `ACTIVE` spec, a `PlatformAdmin` plans a
    **production run**" and "A run is born in `PLANNED`" — once the formula is
    APPROVED and the batch CERTIFIED, the identical create succeeds (201).

    Design: Difficulty/cross_entity_state_dependency/production_run_requires_approved_formulas_certified_batch_active_spec
    """
    fx.reset_clock()
    color = fx.make_active_color()
    spec = fx.create_spec([{"color_id": color["id"], "count": 8}])
    batch = fx.create_batch()
    formula = fx.create_formula(color["id"])
    fx.submit_formula(formula["id"])
    fx.pass_latest_safety_test(formula["id"])
    fx.approve_formula(formula["id"])
    fx.certify_batch(batch["id"])
    resp = api_client.create_production_run(
        {"assortment_spec_id": spec["id"], "pigment_batch_id": batch["id"],
         "planned_boxes": 125, "planned_start_date": "2027-04-15T00:00:00Z",
         "planned_end_date": "2027-05-20T00:00:00Z"}, ADMIN)
    data = validate_success(resp, 201)
    assert_production_run(data)
    assert data["stage"] == "PLANNED"


def test_over_tolerance_packing_advance_diverts_to_quality_hold(api):
    """PRD section 3.4: "If the total variance exceeds the `TOLERANCE_UNITS`
    tolerance of 5 units, the run does not complete: it is placed `ON_HOLD` with
    `stage_before_hold` recorded as `PACKING` and `hold_reason` recorded as
    `QUALITY`, the computed penalty is still recorded against the run, and no
    inventory lot is created."

    Design: Difficulty/non_linear_state_machine/production_run_quality_hold_resume_cycle
    """
    fx.reset_clock()
    env = fx.production_setup()
    run = fx.create_run(env["spec"]["id"], env["batch"]["id"])
    fx.advance_run_to_packing(run["id"])
    resp = api_client.production_run_transition(
        run["id"], {"action": "ADVANCE",
                    "packed_counts": [{"color_id": env["color"]["id"], "count": 1006}]}, ADMIN)
    data = validate_success(resp, 200)
    assert data["stage"] == "ON_HOLD"
    assert data["stage_before_hold"] == "PACKING"
    assert data["hold_reason"] == "QUALITY"
    assert data["packing_variance_units"] == 6
    assert data["packing_penalty_cents"] == 169  # round_half_up(6 * 18.75 * 1.5)
    assert fx.list_lots(run["id"]) == []  # no lot for a held run


def test_resume_from_hold_then_corrected_advance_completes(api):
    """PRD section 3.4: "`RESUME` returns an `ON_HOLD` run to exactly the stage
    recorded in `stage_before_hold`" and "Otherwise the run completes" — the
    penalty recorded at the hold is recomputed to 0 on the successful pass, and
    completion then creates the lot "whose `boxes_received` and `boxes_on_hand`
    both equal `boxes_produced`".

    Design: Difficulty/non_linear_state_machine/production_run_quality_hold_resume_cycle
    """
    fx.reset_clock()
    env = fx.production_setup()
    run = fx.create_run(env["spec"]["id"], env["batch"]["id"])
    fx.advance_run_to_packing(run["id"])
    api_client.production_run_transition(
        run["id"], {"action": "ADVANCE",
                    "packed_counts": [{"color_id": env["color"]["id"], "count": 1006}]}, ADMIN)
    resumed = get_success_data(
        api_client.production_run_transition(run["id"], {"action": "RESUME"}, ADMIN))
    assert resumed["stage"] == "PACKING"
    final = fx.complete_run(run["id"], [{"color_id": env["color"]["id"], "count": 1000}])
    assert final["stage"] == "COMPLETED"
    assert final["packing_penalty_cents"] == 0  # recomputed
    assert final["boxes_produced"] == 125
    assert final["waste_units"] == 0
    lots = fx.list_lots(run["id"])
    assert len(lots) == 1
    assert lots[0]["status"] == "AVAILABLE"
    assert lots[0]["boxes_received"] == 125
    assert lots[0]["boxes_on_hand"] == 125


def test_packing_penalty_rounds_per_line_then_sums(api):
    """PRD section 2.6: "each spec-entry line penalty is rounded half up to
    integer cents first, and the line results are then summed; summing the raw
    line amounts and rounding once is explicitly not the rule, because the two
    orders diverge (two lines each under-packed by 2 units yield 18.75 × 2 =
    37.5 cents per line, which rounds to 38 per line and sums to 76, whereas
    rounding the raw sum of 75.0 would yield 75)."

    Design: Difficulty/combinatorial_formula/packing_penalty_rounds_per_line_then_sums
    """
    fx.reset_clock()
    env = fx.two_color_run_at_packing(planned_boxes=10)
    run = fx.complete_run(
        env["run"]["id"],
        [{"color_id": env["color1"]["id"], "count": 78},
         {"color_id": env["color2"]["id"], "count": 78}])
    assert run["stage"] == "COMPLETED"
    assert run["packing_variance_units"] == 4
    assert run["packing_penalty_cents"] == 76  # 38 + 38; not round(75.0) = 75
    assert run["packing_penalty_cents"] != 75


def test_packing_mass_balance_after_per_line_rounding(api):
    """PRD section 3.4: "`boxes_produced` is the minimum over the spec entries
    of the whole-boxes floor of that entry's packed units divided by the entry's
    count; `waste_units` is the total packed units minus `boxes_produced`
    multiplied by `box_size`, and the `run_production_mass_balance` invariant
    holds exactly".

    Design: Difficulty/combinatorial_formula/packing_penalty_rounds_per_line_then_sums
    """
    fx.reset_clock()
    env = fx.two_color_run_at_packing(planned_boxes=10)
    run = fx.complete_run(
        env["run"]["id"],
        [{"color_id": env["color1"]["id"], "count": 78},
         {"color_id": env["color2"]["id"], "count": 78}])
    assert run["boxes_produced"] == 9   # min(floor(78/8), floor(78/8))
    assert run["waste_units"] == 12     # 156 - 9*16
    total_packed = 78 + 78
    assert total_packed == run["boxes_produced"] * 16 + run["waste_units"]


def test_packing_variance_at_tolerance_completes(api):
    """PRD section 3.4: "If the total variance exceeds the `TOLERANCE_UNITS`
    tolerance of 5 units, the run does not complete" — a variance of exactly 5
    does not exceed the tolerance, so the run COMPLETES with penalty
    round_half_up(5 x 18.75 x 1.5) = 141.

    Design: Difficulty/boundary_precision_check/packing_variance_at_tolerance_completes_above_it_holds
    """
    fx.reset_clock()
    env = fx.production_setup()
    run = fx.create_run(env["spec"]["id"], env["batch"]["id"])
    fx.advance_run_to_packing(run["id"])
    final = fx.complete_run(run["id"], [{"color_id": env["color"]["id"], "count": 1005}])
    assert final["stage"] == "COMPLETED"
    assert final["packing_variance_units"] == 5
    assert final["packing_penalty_cents"] == 141  # round_half_up(5 * 18.75 * 1.5)
    lots = fx.list_lots(run["id"])
    assert len(lots) == 1
    assert lots[0]["status"] == "AVAILABLE"
    assert lots[0]["boxes_received"] == 125


def test_packing_variance_above_tolerance_holds_without_lot(api):
    """PRD section 3.4: "If the total variance exceeds the `TOLERANCE_UNITS`
    tolerance of 5 units, the run does not complete: it is placed `ON_HOLD`
    with `stage_before_hold` recorded as `PACKING` and `hold_reason`
    recorded as `QUALITY`, the computed penalty is still recorded against
    the run, and no inventory lot is created" — a variance of 6 exceeds
    it, penalty
    round_half_up(6 x 18.75 x 1.5) = 169.

    Design: Difficulty/boundary_precision_check/packing_variance_at_tolerance_completes_above_it_holds
    """
    fx.reset_clock()
    env = fx.production_setup()
    run = fx.create_run(env["spec"]["id"], env["batch"]["id"])
    fx.advance_run_to_packing(run["id"])
    resp = api_client.production_run_transition(
        run["id"], {"action": "ADVANCE",
                    "packed_counts": [{"color_id": env["color"]["id"], "count": 1006}]}, ADMIN)
    data = validate_success(resp, 200)
    assert data["stage"] == "ON_HOLD"
    assert data["packing_variance_units"] == 6
    assert data["packing_penalty_cents"] == 169
    assert fx.list_lots(run["id"]) == []


def test_run_packing_mass_balance_boxes_waste(api):
    """PRD section 3.4: "the `run_production_mass_balance` invariant holds
    exactly — total packed units equal `boxes_produced` boxes times `box_size`
    plus `waste_units`." 78 + 78 = 156 == 9 x 16 + 12.

    Design: Difficulty/compensating_invariant/run_packing_mass_balance_boxes_waste
    """
    fx.reset_clock()
    env = fx.two_color_run_at_packing(planned_boxes=10)
    run = fx.complete_run(
        env["run"]["id"],
        [{"color_id": env["color1"]["id"], "count": 78},
         {"color_id": env["color2"]["id"], "count": 78}])
    assert run["boxes_produced"] == 9
    assert run["waste_units"] == 12
    assert 78 + 78 == run["boxes_produced"] * 16 + run["waste_units"]


def test_run_packing_completion_lot_receives_boxes_produced(api):
    """PRD section 3.4: "Completion creates an **inventory lot** bound to
    its producing run by `production_run_id`, in `AVAILABLE`, whose
    `boxes_received` and `boxes_on_hand` both equal `boxes_produced`, whose
    `boxes_committed` and `boxes_shipped` start at 0".

    Design: Difficulty/compensating_invariant/run_packing_mass_balance_boxes_waste
    """
    fx.reset_clock()
    env = fx.two_color_run_at_packing(planned_boxes=10)
    run = fx.complete_run(
        env["run"]["id"],
        [{"color_id": env["color1"]["id"], "count": 78},
         {"color_id": env["color2"]["id"], "count": 78}])
    lots = fx.list_lots(run["id"])
    assert len(lots) == 1
    assert lots[0]["boxes_received"] == 9
    assert lots[0]["boxes_on_hand"] == 9
