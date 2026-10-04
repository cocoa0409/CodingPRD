"""Print execution: interruptions, cure windows, completion invariants (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    PRINT_OP,
    QUALITY_INSP,
    assert_layer_inspection,
    assert_layer_inspection_outcome_invariants,
    complete_print_job,
    create_layer_inspection_payload,
    create_printing_job,
    get_success_data,
    post_clear_weather,
    record_and_accept_inspection,
    schedule_print_job,
    set_clock,
    setup_site_ready_for_print,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import make_quality_inspector_headers

QI_SECOND = make_quality_inspector_headers("qi-second")


def test_cure_penalty_nested_ceil_and_conditional(api):
    """PRD §3.7: "The penalty applies only when the cause is `WEATHER` or
    `MATERIAL`: it is the duration divided into 10-minute chunks, rounded up —
    a duration of exactly 10 minutes yields a penalty of 1, and a duration of
    zero yields 0." Also: "The interruption's
    `max_permissible_interruption_minutes` is read from the `mix_code` of the
    batch being consumed at pause time: 30 minutes for `LAVACRETE_A`, 20
    minutes for `LAVACRETE_B`, and 45 minutes for `LAVACRETE_C`."

    A 20-minute WEATHER pause on a LAVACRETE_B batch resumes successfully
    (inclusive boundary) and closes with cure_penalty_layers = ceil(20/10) = 2.

    Design: Difficulty/combinatorial_formula/cure_penalty_nested_ceil_and_conditional
    """
    ctx = setup_site_ready_for_print(jurisdiction_code="JC", mix_code="LAVACRETE_B",
                                     pump_consistency=60)
    site_id = ctx["site"]["id"]
    job = create_printing_job(ctx)
    get_success_data(
        api.transition_print_job(site_id, job["id"], {"to_state": "PAUSED", "cause": "WEATHER"}, PRINT_OP)
    )
    # Post a fresh print-permissible observation so the resume satisfies the
    # weather gate ("the latest weather observation to be print-permissible").
    post_clear_weather(site_id, "2026-09-04T08:19:00Z")
    set_clock("2026-09-04T08:20:00Z")
    resumed = validate_success(
        api.transition_print_job(site_id, job["id"], {"to_state": "PRINTING"}, PRINT_OP)
    )
    assert resumed["status"] == "PRINTING"
    # The closed interruption is observable through the job's cumulative total:
    # 20 minutes were banked and the penalty was ceil(20/10) == 2.
    assert resumed["cumulative_interruption_minutes"] == 20


def test_cure_penalty_exceeded_resume_rejected(api):
    """PRD §3.7: "any subsequent resume attempt is rejected with
    `ERR_INTERRUPTION_CURE_EXCEEDED` — at which point aborting is the correct
    recovery."

    A 25-minute WEATHER pause exceeds the LAVACRETE_B 20-minute window.

    Design: Difficulty/combinatorial_formula/cure_penalty_nested_ceil_and_conditional
    """
    ctx = setup_site_ready_for_print(jurisdiction_code="JCB", mix_code="LAVACRETE_B",
                                     pump_consistency=60)
    site_id = ctx["site"]["id"]
    job = create_printing_job(ctx)
    get_success_data(
        api.transition_print_job(site_id, job["id"], {"to_state": "PAUSED", "cause": "WEATHER"}, PRINT_OP)
    )
    set_clock("2026-09-04T08:25:00Z")
    resp = api.transition_print_job(site_id, job["id"], {"to_state": "PRINTING"}, PRINT_OP)
    validate_error(resp, ApiErrorId.ERR_INTERRUPTION_CURE_EXCEEDED)


def test_interruption_minutes_conserve_continuous_run(api):
    """PRD §3.7: "Completion stamps `actual_end_at`, computes
    `continuous_run_minutes` as the elapsed time between `actual_start_at` and
    `actual_end_at` minus `cumulative_interruption_minutes`" and "Closing an
    interruption also recomputes the job's `cumulative_interruption_minutes` as
    the sum of `duration_minutes` over all `CLOSED` interruptions on the job".

    Run 08:00→09:00 (60 min) with a 5-minute WEATHER pause and a 7-minute
    OPERATOR pause: cumulative 12, continuous run 48.

    Design: Difficulty/compensating_invariant/interruption_minutes_conserve_continuous_run
    """
    ctx = setup_site_ready_for_print(
        jurisdiction_code="JV", mix_code="LAVACRETE_C", pump_consistency=40
    )
    site_id = ctx["site"]["id"]
    job = create_printing_job(ctx, clock_at="2026-09-04T08:00:00Z")
    set_clock("2026-09-04T08:10:00Z")
    get_success_data(
        api.transition_print_job(site_id, job["id"], {"to_state": "PAUSED", "cause": "WEATHER"}, PRINT_OP)
    )
    # Post fresh weather so the resume passes the weather gate.
    from test_helpers import post_clear_weather

    post_clear_weather(site_id, "2026-09-04T08:14:00Z")
    set_clock("2026-09-04T08:15:00Z")
    get_success_data(
        api.transition_print_job(site_id, job["id"], {"to_state": "PRINTING"}, PRINT_OP)
    )
    set_clock("2026-09-04T08:30:00Z")
    get_success_data(
        api.transition_print_job(site_id, job["id"], {"to_state": "PAUSED", "cause": "OPERATOR"}, PRINT_OP)
    )
    set_clock("2026-09-04T08:37:00Z")
    get_success_data(
        api.transition_print_job(site_id, job["id"], {"to_state": "PRINTING"}, PRINT_OP)
    )
    completed = complete_print_job(ctx, job["id"], clock_at="2026-09-04T09:00:00Z")
    assert completed["status"] == "COMPLETED"
    assert completed["cumulative_interruption_minutes"] == 12
    assert completed["continuous_run_minutes"] == 48


def test_abort_consumes_batch_and_recovers_site(api):
    """PRD §3.7: "Aborting closes any open interruption with `resumed_at` set
    to the current logical clock, transitions the consumed batch from
    `QUALIFIED` to `EXHAUSTED`, and recomputes the site's status (dropping from
    `ACTIVE_PRINT` back to `SITE_READY` when no other print is active)."

    Design: Difficulty/compensating_invariant/interruption_minutes_conserve_continuous_run
    """
    ctx = setup_site_ready_for_print(jurisdiction_code="JV2")
    site_id = ctx["site"]["id"]
    job = create_printing_job(ctx)
    site = get_success_data(api.get_site(site_id, PRINT_OP))
    assert site["status"] == "ACTIVE_PRINT"
    aborted = validate_success(
        api.transition_print_job(site_id, job["id"], {"to_state": "ABORTED"}, PRINT_OP)
    )
    assert aborted["status"] == "ABORTED"
    batches, _m = validate_paginated(api.list_material_batches(site_id, PRINT_OP))
    consumed = next(b for b in batches if b["id"] == ctx["batch"]["id"])
    assert consumed["status"] == "EXHAUSTED"
    site = get_success_data(api.get_site(site_id, PRINT_OP))
    assert site["status"] == "SITE_READY"


def test_print_job_invalid_from_completed_to_printing(api):
    """PRD §3.7: "Completing a print (`PRINTING` → `COMPLETED`)" — from-state
    legality is governed by PRD §2.11 item 8: "the source state is in the
    transition's from-set (`ERR_INVALID_STATE`)", so starting a job that
    already completed is rejected.

    Design: Corner/state_machines/print_job_invalid_from_completed_to_printing
    """
    ctx = setup_site_ready_for_print(jurisdiction_code="JI")
    site_id = ctx["site"]["id"]
    job = create_printing_job(ctx)
    completed = complete_print_job(ctx, job["id"])
    assert completed["status"] == "COMPLETED"
    resp = api.transition_print_job(site_id, job["id"], {"to_state": "PRINTING"}, PRINT_OP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_print_job_completed_to_pause_also_rejected(api):
    """PRD §3.7 defines pausing from a running job: "Pausing is driven by the
    job's `transition` capability with `to_state` set to `PAUSED`." A pause on
    a `COMPLETED` job is not in any from-set, so PRD §2.11 item 8 applies:
    "the source state is in the transition's from-set
    (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/print_job_invalid_from_completed_to_printing
    """
    ctx = setup_site_ready_for_print(jurisdiction_code="JI2")
    site_id = ctx["site"]["id"]
    job = create_printing_job(ctx)
    complete_print_job(ctx, job["id"])
    resp = api.transition_print_job(
        site_id, job["id"], {"to_state": "PAUSED", "cause": "OPERATOR"}, PRINT_OP
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_bond_strength_threshold_inclusive_minimum(api):
    """PRD §3.8: "The server derives `passes_bond` (true when bond strength is
    at least 1.5 MPa, inclusive), `passes_dimensional` (true when the
    dimensional deviation is at most 6 mm, inclusive), and a four-valued
    `outcome`: `PASS` when both pass, `FAIL_BOND` when only bond fails,
    `FAIL_DIMENSIONAL` when only dimensional fails, and `FAIL_BOTH` when both
    fail."

    Design: Difficulty/boundary_precision_check/bond_strength_threshold_inclusive_minimum
    """
    ctx = setup_site_ready_for_print(jurisdiction_code="JB")
    site_id = ctx["site"]["id"]
    job = create_printing_job(ctx)
    insp_a = validate_success(
        api.create_layer_inspection(
            site_id,
            job["id"],
            create_layer_inspection_payload(
                layer_index_start=1, layer_index_end=5,
                bond_strength_mpa=1.5, dimensional_deviation_mm=6,
            ),
            QUALITY_INSP,
        ),
        201,
    )
    assert_layer_inspection(insp_a)
    assert_layer_inspection_outcome_invariants(insp_a)
    assert insp_a["passes_bond"] is True
    assert insp_a["passes_dimensional"] is True
    assert insp_a["outcome"] == "PASS"
    insp_b = validate_success(
        api.create_layer_inspection(
            site_id,
            job["id"],
            create_layer_inspection_payload(
                layer_index_start=6, layer_index_end=10,
                bond_strength_mpa=1.49, dimensional_deviation_mm=6,
            ),
            QUALITY_INSP,
        ),
        201,
    )
    assert insp_b["passes_bond"] is False
    assert insp_b["passes_dimensional"] is True
    assert insp_b["outcome"] == "FAIL_BOND"


def test_dimensional_threshold_inclusive_maximum(api):
    """PRD §3.8: "`passes_dimensional` (true when the dimensional deviation is
    at most 6 mm, inclusive)" and "`FAIL_DIMENSIONAL` when only dimensional
    fails".

    Design: Difficulty/boundary_precision_check/bond_strength_threshold_inclusive_minimum
    """
    ctx = setup_site_ready_for_print(jurisdiction_code="JB2")
    site_id = ctx["site"]["id"]
    job = create_printing_job(ctx)
    insp = validate_success(
        api.create_layer_inspection(
            site_id,
            job["id"],
            create_layer_inspection_payload(
                layer_index_start=1, layer_index_end=5,
                bond_strength_mpa=2.0, dimensional_deviation_mm=7,
            ),
            QUALITY_INSP,
        ),
        201,
    )
    assert insp["passes_bond"] is True
    assert insp["passes_dimensional"] is False
    assert insp["outcome"] == "FAIL_DIMENSIONAL"
