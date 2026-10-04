"""Seasoning gate boundaries and the wood-reject rework cascade."""
from test_helpers import (
    SEASONING_MIN_DAYS,
    ApiErrorId,
    TEST_USERS,
    advance_build_by_master,
    advance_build_payload,
    condition_wood_batch,
    create_craftsman_set,
    create_wood_batch,
    get_build_order,
    get_success_data,
    get_wood_batch,
    make_master_craftsman_headers,
    set_clock_days_after,
    setup_build_in_stage,
    validate_error,
    validate_success,
)

WM = TEST_USERS["workshop_manager_headers"]


def _seasoning_build_with_spare_batch():
    """MODEL_B build in SEASONING on batch one, plus a spare CONDITIONED batch."""
    wb1 = create_wood_batch("MAPLE", 12.0)
    wb2 = create_wood_batch("SPRUCE", 11.5)
    wb1 = condition_wood_batch(wb1, ready_moisture=8.0)
    wb2 = condition_wood_batch(wb2, ready_moisture=7.5)
    craftsmen = create_craftsman_set()
    ctx = setup_build_in_stage(
        "MODEL_B", "SEASONING", {"RIM_BENT": 100, "SEASONING": 30}, craftsmen, wb1
    )
    return ctx, wb2


def test_seasoning_gate_fails_at_day_364(api):
    """PRD section 3.2: "at least 365 whole days must have elapsed since
    `seasoning_started_at`, with exactly 365 passing; otherwise the advance fails
    with `ERR_SEASONING_INCOMPLETE`."

    Design: Corner/validations/seasoning_gate_fails_at_day_364
    """
    ctx = setup_build_in_stage("MODEL_B", "SEASONING", {"RIM_BENT": 100, "SEASONING": 30})
    build = ctx["build"]
    set_clock_days_after(build["seasoning_started_at"], SEASONING_MIN_DAYS - 1)
    resp = api.advance_build_order(
        build["id"],
        advance_build_payload("ACTION_REGULATION", 40, build["version"]),
        make_master_craftsman_headers(ctx["craftsmen"]["SEASONING_CHECK"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SEASONING_INCOMPLETE)
    after = get_build_order(build["id"])
    assert after["status"] == "SEASONING"
    assert after["version"] == build["version"]


def test_seasoning_exactly_365_days_allows_regulation(api):
    """PRD section 3.2: "at least 365 whole days must have elapsed since
    `seasoning_started_at`, with exactly 365 passing".

    Design: Difficulty/boundary_precision_check/seasoning_exactly_365_days_allows_regulation
    """
    ctx = setup_build_in_stage("MODEL_B", "SEASONING", {"RIM_BENT": 100, "SEASONING": 30})
    build = ctx["build"]
    set_clock_days_after(build["seasoning_started_at"], SEASONING_MIN_DAYS)
    advanced = advance_build_by_master(
        build, "ACTION_REGULATION", 40, ctx["craftsmen"]["SEASONING_CHECK"]
    )
    assert advanced["status"] == "ACTION_REGULATION"
    assert advanced["version"] == build["version"] + 1
    assert advanced["seasoning_started_at"] == build["seasoning_started_at"]


def test_seasoning_advance_appends_stage_log(api):
    """PRD section 3.2: "Every successful advance appends a build stage log entry
    recording the owning `build_order_id`, the `to_stage` entered, the
    `operation_type` derived from that stage".
    PRD section 3.2: "entering `SEASONING`, and leaving it for `ACTION_REGULATION`,
    both credit `SEASONING_CHECK`."

    Design: Difficulty/boundary_precision_check/seasoning_exactly_365_days_allows_regulation
    """
    ctx = setup_build_in_stage("MODEL_B", "SEASONING", {"RIM_BENT": 100, "SEASONING": 30})
    build = ctx["build"]
    set_clock_days_after(build["seasoning_started_at"], SEASONING_MIN_DAYS)
    advance_build_by_master(build, "ACTION_REGULATION", 40, ctx["craftsmen"]["SEASONING_CHECK"])
    logs = validate_success(api.list_build_stage_logs(build["id"], WM), 200)
    assert len(logs) == 3
    assert logs[2]["to_stage"] == "ACTION_REGULATION"
    assert logs[2]["operation_type"] == "SEASONING_CHECK"


def test_wood_reject_fires_rework_cascade(api):
    """PRD section 3.2: "When a `WorkshopManager` rejects an allocated batch whose
    owning build is in `SEASONING` (section 3.1), the build drops back from
    `SEASONING` to `RIM_BENT`, its `wood_batch_id` is cleared to null, its
    `seasoning_started_at` is cleared to null, its `version` increments".

    Design: Difficulty/non_linear_state_machine/build_seasoning_rework_cycle
    """
    ctx, _wb2 = _seasoning_build_with_spare_batch()
    build = ctx["build"]
    batch = ctx["batch"]
    rejected = validate_success(api.reject_wood_batch(batch["id"], {}, WM), 200)
    assert rejected["status"] == "REJECTED"
    after = get_build_order(build["id"])
    assert after["status"] == "RIM_BENT"
    assert after["wood_batch_id"] is None
    assert after["seasoning_started_at"] is None
    assert after["version"] == build["version"] + 1


def test_reworked_build_readvances_with_fresh_batch(api):
    """PRD section 3.2: "after a rework has stripped the order of its batch, that
    payload value must name a `CONDITIONED` batch ... and the named batch then
    becomes `ALLOCATED`."
    PRD section 3.2: the advance into SEASONING "sets `seasoning_started_at` to the
    current logical clock".

    Design: Difficulty/non_linear_state_machine/build_seasoning_rework_cycle
    """
    ctx, wb2 = _seasoning_build_with_spare_batch()
    build = ctx["build"]
    validate_success(api.reject_wood_batch(ctx["batch"]["id"], {}, WM), 200)
    stripped = get_build_order(build["id"])
    advanced = advance_build_by_master(
        stripped, "SEASONING", 35, ctx["craftsmen"]["SEASONING_CHECK"],
        wood_batch_id=wb2["id"],
    )
    assert advanced["status"] == "SEASONING"
    assert advanced["wood_batch_id"] == wb2["id"]
    assert advanced["version"] == stripped["version"] + 1
    assert get_wood_batch(wb2["id"])["status"] == "ALLOCATED"


def test_wood_reject_drops_material_from_wip(api):
    """PRD section 3.2: "its `wip_value_cents` is recomputed with the rejected
    batch's material cost dropped."
    PRD section 3.2: "The ACTUAL variant is then the allocated batch's material cost
    (zero while no batch is allocated) plus that labor sum".
    Labor kept: 100h x 14,500 + 30h x 9,500 = 1,735,000 cents.

    Design: Difficulty/transitive_cascade/wood_reject_rework_wip_cascade
    """
    ctx, _wb2 = _seasoning_build_with_spare_batch()
    build = ctx["build"]
    validate_success(api.reject_wood_batch(ctx["batch"]["id"], {}, WM), 200)
    after = get_build_order(build["id"])
    assert after["status"] == "RIM_BENT"
    assert after["wip_value_cents"] == 1_735_000
    valuation = get_success_data(api.get_build_valuation(build["id"], WM))
    assert valuation["actual_wip_cents"] == 1_735_000


def test_wood_reject_provisional_includes_replacement(api):
    """PRD section 3.2: "The PROVISIONAL variant starts from the actual figure, adds
    the model's material cost as planned replacement material while no batch is
    allocated, and adds planned labor for every forward transition not yet taken".
    PRD section 3.2: "After a rework has returned the order to `RIM_BENT`, the
    untaken set restarts from the transition into `SEASONING`."
    Here: 1,735,000 + 3,600,000 replacement + (40x9,500 + 40x9,500 + 200x21,000 +
    160x24,000) = 14,135,000 cents.

    Design: Difficulty/transitive_cascade/wood_reject_rework_wip_cascade
    """
    ctx, _wb2 = _seasoning_build_with_spare_batch()
    build = ctx["build"]
    validate_success(api.reject_wood_batch(ctx["batch"]["id"], {}, WM), 200)
    valuation = get_success_data(api.get_build_valuation(build["id"], WM))
    assert valuation["actual_wip_cents"] == 1_735_000
    assert valuation["provisional_wip_cents"] == 14_135_000
    assert valuation["delta_cents"] == 14_135_000 - 1_735_000
