"""Declared states, the edges between them and the ones that are refused.

Every machine in the contract is walked here: where each entity starts, which
branch an adjudication takes, what a failed clean drags down with it, and what
a terminal state refuses to do a second time.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    LINE_OPERATOR_HEADERS,
    QA_MANAGER_HEADERS,
    QA_TECHNICIAN_HEADERS,
    USER_LINE_OPERATOR,
    USER_QA_MANAGER_A,
    USER_QA_TECH_A,
    USER_QA_TECH_B,
    USER_QA_TECH_C,
    USER_QA_TECH_D,
    USER_SANITATION_TECH_A,
    USER_SANITATION_TECH_B,
    make_qa_manager_headers,
    make_qa_technician_headers,
    make_sanitation_tech_headers,
)

HTTP_CREATED = 201

# The lot, load and swab used to sample every declared initial state at once.
INITIAL_LOT_OVERRIDES = {
    "grower_code": "GRW-200",
    "ranch_block": "B2",
    "harvest_datetime": "2026-08-01T08:00:00Z",
    "water_source": c.WATER_MUNICIPAL,
}
INITIAL_LOAD_OVERRIDES = {
    "received_at": "2026-08-02T05:20:00Z",
    "pulp_temp_c": 2.0,
    "gross_weight_lb": 10000.00,
    "tare_weight_lb": 1000.00,
}
INITIAL_SWAB_OVERRIDES = {
    "zone": c.ZONE_2,
    "site_code": "DRAIN-4",
    "organism": c.ORGANISM_LISTERIA_SPP,
    "collected_at": "2026-08-02T06:10:00Z",
}
UNLOADED_WEIGHTED_LB = 0.00
UNLOADED_INDEX = 0.000

# A lot the preharvest programme has already condemned.
POSITIVE_LOT_OVERRIDES = {
    "grower_code": "GRW-300",
    "ranch_block": "B3",
    "harvest_datetime": "2026-08-01T08:00:00Z",
    "preharvest_test_result": c.PREHARVEST_POSITIVE,
}
CONDEMNED_SCORE = 0

# A lot whose field evidence scores 20: surface water, animals, presumptive, four rejects.
SUSPENDED_LOT_OVERRIDES = {
    "grower_code": "GRW-400",
    "ranch_block": "B4",
    "harvest_datetime": "2026-08-01T08:00:00Z",
    "water_source": c.WATER_SURFACE,
    "adjacent_animal_operation": True,
    "preharvest_test_result": c.PREHARVEST_PRESUMPTIVE,
    "prior_rejected_receipt_count": 4,
}
SUSPENDED_SCORE = 20
SUSPENDED_LOAD_OVERRIDES = {
    "received_at": "2026-08-03T06:00:00Z",
    "pulp_temp_c": 2.0,
    "gross_weight_lb": 21000.00,
    "tare_weight_lb": 1000.00,
}
SUSPENDED_LOAD_ACCEPTED_LB = 20000.00
ATTEMPTED_DRAW_LB = 10000.00

# An ATP swab fifty relative light units above the line's limit of 200.
FAILING_ATP_RLU = 250
SECOND_ATTEMPT = 2
RESET_COMPONENT_COUNT = 0

# The window of the second run, planned the day after the cascade.
NEXT_DAY_START_AT = "2026-08-04T07:00:00Z"
NEXT_DAY_END_AT = "2026-08-04T12:00:00Z"

# The clean scheduled for the second shift, after the standing run closes.
SECOND_SHIFT_SCHEDULED_FOR = "2026-08-03T13:00:00Z"
SECOND_EVENT_SEQUENCE = 2

# Two environmental swabs on the same line, at two different sites.
CONTACT_SWAB_OVERRIDES = {
    "zone": c.ZONE_1,
    "site_code": "BLADE-2",
    "organism": c.ORGANISM_LISTERIA_MONOCYTOGENES,
    "collected_at": "2026-08-02T04:00:00Z",
}
DRAIN_SWAB_OVERRIDES = {
    "zone": c.ZONE_2,
    "site_code": "DRAIN-9",
    "organism": c.ORGANISM_LISTERIA_SPP,
    "collected_at": "2026-08-02T04:05:00Z",
}

# The two narratives a reopened corrective action carries in turn.
FIRST_NARRATIVE = "Wiped down the blade housing"
SECOND_NARRATIVE = "Disassembled and replaced the blade housing seals"


def test_every_machine_reports_its_own_declared_initial_state(api):
    """Seven fresh rows, seven initial states, and a run that starts in two.

    PRD: A new line starts with `posture` at `RESTRICTED`, `open_corrective_action_count` at 0, and `last_validated_sanitation_at`, `last_run_allergen_group` and `last_run_ended_at` all null.
    PRD: On creation the server sets `status` to `IN_SERVICE`, `last_changeout_at` to the logical clock's current instant, `weighted_load_lb` to 0, `organic_load_index` to 0.000, `target_free_chlorine_ppm` to 20.0, `changeout_count` to 0 and `reading_sequence_high_water` to 0.
    PRD: A newly identified lot has `status` of `PENDING_APPROVAL`, `out_of_spec_receipt_count` and `env_positive_run_count` at 0, `recalled_at` null, and both `preharvest_risk_score` and `trailing_risk_score` null — a lot's risk is not scored until it is adjudicated.
    PRD: A new swab has `result` of `PENDING`, and a pending swab does not affect the line's posture at all.
    PRD: The new run begins with `run_status` of `SETUP` and `disposition_status` of `UNRESTRICTED`, and `started_at`, `closed_at`, `target_ppm_at_start` and `required_dwell_seconds_at_start` all null.

    Design: Corner/state_machines/corner_every_entity_starts_in_its_declared_initial_state
    """
    world = fx.master_data_world(api)

    line = fx.read_line(api, world.line_id)
    assert line["posture"] == c.POSTURE_RESTRICTED
    assert line["open_corrective_action_count"] == 0
    assert line["last_validated_sanitation_at"] is None
    assert line["last_run_allergen_group"] is None
    assert line["last_run_ended_at"] is None

    a.assert_wash_chemistry(
        fx.read_wash_system(api, world.wash_system_id),
        weighted_load_lb=UNLOADED_WEIGHTED_LB,
        organic_load_index=UNLOADED_INDEX,
        target_free_chlorine_ppm=c.TARGET_PPM_TIER_BASE,
        status=c.WASH_IN_SERVICE,
    )
    assert fx.read_wash_system(api, world.wash_system_id)["changeout_count"] == 0

    lot = fx.create_grower_lot(api, **INITIAL_LOT_OVERRIDES)
    assert lot["status"] == c.LOT_PENDING_APPROVAL
    assert lot["preharvest_risk_score"] is None
    assert lot["trailing_risk_score"] is None
    assert lot["out_of_spec_receipt_count"] == 0
    assert lot["env_positive_run_count"] == 0
    assert lot["recalled_at"] is None

    load = fx.create_receipt(api, lot["id"], **INITIAL_LOAD_OVERRIDES)
    assert load["status"] == c.RECEIPT_PENDING_INSPECTION

    event = fx.schedule_sanitation(api, world.line_id)
    assert event["status"] == c.SANITATION_SCHEDULED
    assert event["attempt_count"] == 0
    assert event["sequence_no"] == 1

    swab = fx.create_swab(api, world.line_id, **INITIAL_SWAB_OVERRIDES)
    assert swab["result"] == c.SWAB_RESULT_PENDING
    assert swab["resulted_at"] is None

    run = fx.plan_run(
        api, world.line_id, world.product_id, world.spec_id, world.wash_system_id
    )
    assert run["run_status"] == c.RUN_SETUP
    assert run["disposition_status"] == c.DISPOSITION_UNRESTRICTED
    assert run["started_at"] is None
    assert run["closed_at"] is None
    assert run["target_ppm_at_start"] is None
    assert run["required_dwell_seconds_at_start"] is None
    assert run["allergen_changeover_required"] is False


def test_a_positive_preharvest_test_rejects_the_lot_and_zeroes_both_scores(api):
    """Well water and a clean scorecard cannot save a confirmed positive.

    PRD: When `preharvest_test_result` is `POSITIVE`, the lot moves `PENDING_APPROVAL → REJECTED` regardless of the weighted score — a confirmed preharvest pathogen positive is a hard rejection — and both `preharvest_risk_score` and `trailing_risk_score` are set to 0.
    PRD: Adjudication increments the lot's `version` by 1.
    PRD: Nothing about the grower lot's own state is checked at receiving; a load may be recorded against a lot that has not yet been adjudicated.

    Design: Corner/state_machines/corner_positive_preharvest_test_rejects_lot_with_zero_scores
    """
    fx.set_clock(api, c.CLOCK_MASTER_DATA)
    lot = fx.create_grower_lot(api, **POSITIVE_LOT_OVERRIDES)
    assert lot["water_source"] == c.WATER_WELL
    assert lot["adjacent_animal_operation"] is False
    assert lot["prior_rejected_receipt_count"] == 0

    adjudicated = fx.approve_grower_lot(api, lot["id"])
    a.assert_risk_scores(
        adjudicated,
        preharvest=CONDEMNED_SCORE,
        trailing=CONDEMNED_SCORE,
        status=c.LOT_REJECTED,
    )
    a.assert_version_is(adjudicated, 2, "grower lot")

    # Receiving is deliberately unguarded: the gate lives on consumption.
    load = fx.create_receipt(api, lot["id"], **INITIAL_LOAD_OVERRIDES)
    assert load["status"] == c.RECEIPT_PENDING_INSPECTION
    assert load["grower_lot_id"] == lot["id"]


def test_a_score_below_fifty_is_approved_straight_into_suspension(api):
    """The lot is adjudicated, its load is perfect, and the pounds still cannot move.

    PRD: When the test result is anything other than `POSITIVE` and the computed score is below 50, the lot moves `PENDING_APPROVAL → SUSPENDED` — approved into suspension. Both `preharvest_risk_score` and `trailing_risk_score` receive the computed value, and the lot may not be consumed.
    PRD: The grower lot behind the named load must have `status` of `APPROVED`. Lots that are `PENDING_APPROVAL`, `SUSPENDED`, `REJECTED` or `RECALLED` may never be consumed, and the attempt is refused with `ERR_GROWER_LOT_NOT_APPROVED` (HTTP 422).

    Design: Corner/state_machines/corner_low_preharvest_score_approves_into_suspension
    """
    world = fx.build_world(api, stop_after=fx.STOP_RUN_RUNNING)

    suspended = fx.approved_grower_lot(api, **SUSPENDED_LOT_OVERRIDES)
    a.assert_risk_scores(
        suspended,
        preharvest=SUSPENDED_SCORE,
        trailing=SUSPENDED_SCORE,
        status=c.LOT_SUSPENDED,
    )

    load = fx.create_receipt(api, suspended["id"], **SUSPENDED_LOAD_OVERRIDES)
    accepted = fx.disposition_receipt(
        api, load["id"], c.DECISION_ACCEPT, trim_loss_lb=0.00
    )
    assert accepted["status"] == c.RECEIPT_ACCEPTED, (
        "the receiving path is unaffected by the lot's suspension"
    )
    assert accepted["accepted_lb"] == SUSPENDED_LOAD_ACCEPTED_LB
    assert accepted["remaining_lb"] == SUSPENDED_LOAD_ACCEPTED_LB

    validate_error(
        api.create_lot_consumption(
            world.run_id,
            f.lot_consumption_payload(
                load["id"], world.run["version"], ATTEMPTED_DRAW_LB
            ),
            LINE_OPERATOR_HEADERS,
        ),
        ApiErrorId.GROWER_LOT_NOT_APPROVED,
    )
    assert fx.read_receipt(api, load["id"])["remaining_lb"] == SUSPENDED_LOAD_ACCEPTED_LB


def test_a_second_adjudication_of_an_approved_lot_writes_nothing(api):
    """Approval is not replayable: the refusal leaves state and version alone.

    PRD: Adjudication increments the lot's `version` by 1. It is legal only from `PENDING_APPROVAL`; attempting it on a lot in any other state is refused with `ERR_GROWER_LOT_INVALID_STATE` (HTTP 409).

    Design: Corner/state_machines/corner_approve_twice_is_refused
    """
    world = fx.build_world(api, stop_after=fx.STOP_LOT_APPROVED)
    before = fx.read_grower_lot(api, world.grower_lot_id)
    a.assert_risk_scores(
        before, preharvest=c.RISK_START, trailing=c.RISK_START, status=c.LOT_APPROVED
    )

    validate_error(
        api.approve_grower_lot(world.grower_lot_id, QA_MANAGER_HEADERS),
        ApiErrorId.GROWER_LOT_INVALID_STATE,
    )

    after = fx.read_grower_lot(api, world.grower_lot_id)
    assert after["status"] == before["status"]
    a.assert_version_is(after, before["version"], "grower lot")
    a.assert_instant_equals(after["updated_at"], before["updated_at"], "updated_at")


def test_neither_terminal_lot_state_accepts_another_adjudication_or_recall(api):
    """A recalled lot and a rejected lot both refuse recall and approval alike.

    PRD: A `QAManager` may also **recall** a lot that is `APPROVED` or `SUSPENDED`, which drives it to the terminal `RECALLED` state and runs the containment sweep described in §3.9. Recall on a lot that is neither `APPROVED` nor `SUSPENDED` is refused with `ERR_GROWER_LOT_INVALID_STATE`.
    PRD: The recall first drives the lot to `RECALLED` and stamps `recalled_at` from the logical clock.
    PRD: Caused by that, every load whose `grower_lot_id` names the lot and whose `status` is `PENDING_INSPECTION` or `ACCEPTED` moves to `QUARANTINED`, processed in `received_at` ascending order with `created_at` ascending as the tie-break.

    Design: Corner/state_machines/corner_recalled_lot_is_terminal
    """
    world = fx.build_world(api, stop_after=fx.STOP_RECEIPT_ACCEPTED)

    recalled = validate_success(
        api.recall_grower_lot(world.grower_lot_id, QA_MANAGER_HEADERS)
    )
    assert recalled["status"] == c.LOT_RECALLED
    a.assert_instant_equals(recalled["recalled_at"], c.CLOCK_MASTER_DATA, "recalled_at")
    assert fx.read_receipt(api, world.receipt_id)["status"] == c.RECEIPT_QUARANTINED

    rejected = fx.approve_grower_lot(
        api, fx.create_grower_lot(api, **POSITIVE_LOT_OVERRIDES)["id"]
    )
    assert rejected["status"] == c.LOT_REJECTED

    # The sweep can never be replayed, and neither leaf reopens for adjudication.
    validate_error(
        api.recall_grower_lot(world.grower_lot_id, QA_MANAGER_HEADERS),
        ApiErrorId.GROWER_LOT_INVALID_STATE,
    )
    validate_error(
        api.approve_grower_lot(world.grower_lot_id, QA_MANAGER_HEADERS),
        ApiErrorId.GROWER_LOT_INVALID_STATE,
    )
    validate_error(
        api.recall_grower_lot(rejected["id"], QA_MANAGER_HEADERS),
        ApiErrorId.GROWER_LOT_INVALID_STATE,
    )
    validate_error(
        api.approve_grower_lot(rejected["id"], QA_MANAGER_HEADERS),
        ApiErrorId.GROWER_LOT_INVALID_STATE,
    )


def _clean_failing_on_atp(api, world):
    """Submit a clean measuring 250 RLU against a 200 RLU line, then pass it."""
    event = fx.schedule_sanitation(api, world.line_id)
    fx.start_sanitation(api, event["id"], USER_SANITATION_TECH_A)
    submitted = fx.submit_sanitation(
        api, event["id"], USER_SANITATION_TECH_A, atp_rlu=FAILING_ATP_RLU
    )
    assert submitted["status"] == c.SANITATION_AWAITING_VALIDATION, (
        "the failing measurement is recorded and only judged at validation"
    )
    return fx.validate_sanitation(api, event["id"], c.OUTCOME_PASS, USER_QA_TECH_A)


def test_a_passing_verdict_cannot_override_the_measurement_and_drags_four_rows_down(api):
    """One failed validation restricts the line, dumps the flume and cancels a run.

    PRD: The event moves `AWAITING_VALIDATION → FAILED` when the outcome is `FAIL`, and equally when the outcome is `PASS` but `atp_rlu` exceeds `max_atp_rlu` or `allergen_swab_result` is `POSITIVE` — a passing verdict cannot override the measurements.
    PRD: The failure opens a corrective action against the line with `source_type` of `SANITATION_FAILURE`, `source_ref_id` pointing at the failed event, `severity` of `MAJOR`, and increments the line's `open_corrective_action_count`.
    PRD: The restricted posture then reaches the water: every wash system referenced by a run on this line whose `run_status` is `SETUP` or `RUNNING` moves `IN_SERVICE → DUMP_REQUIRED`, processed in `created_at` ascending order.
    PRD: Cancellation leaves `disposition_status` untouched at `UNRESTRICTED`, which is the clearest demonstration that the two dimensions are genuinely independent, and because no case has been packed yet, no case cascade fires.

    Design: Corner/state_machines/corner_sanitation_validation_failure_cascade_fires_all_five_hops
    """
    world = fx.build_world(api, stop_after=fx.STOP_RECEIPT_ACCEPTED)
    run = fx.plan_run(
        api, world.line_id, world.product_id, world.spec_id, world.wash_system_id
    )

    failed = _clean_failing_on_atp(api, world)
    assert failed["status"] == c.SANITATION_FAILED
    assert failed["failed_reason"] == c.FAILED_ATP_ABOVE_LIMIT
    assert failed["validated_at"] is None

    line = fx.read_line(api, world.line_id)
    assert line["posture"] == c.POSTURE_RESTRICTED
    assert line["open_corrective_action_count"] == 1

    actions = fx.list_line_corrective_actions(api, world.line_id)
    assert len(actions) == 1
    assert actions[0]["severity"] == c.SEVERITY_MAJOR
    assert actions[0]["source_type"] == c.SOURCE_SANITATION_FAILURE
    assert actions[0]["source_ref_id"] == failed["id"]
    assert actions[0]["status"] == c.CA_OPEN

    assert fx.read_wash_system(api, world.wash_system_id)["status"] == c.WASH_DUMP_REQUIRED

    cancelled = fx.read_run(api, run["id"])
    assert cancelled["run_status"] == c.RUN_CANCELLED
    assert cancelled["disposition_status"] == c.DISPOSITION_UNRESTRICTED
    assert fx.list_cases(api, run["id"]) == []


def test_a_clean_reclean_that_passes_leaves_the_line_shut_until_the_action_is_verified(api):
    """The revert edge reuses the row, and the open action outranks the fresh pass.

    PRD: Beginning the clean moves the event `SCHEDULED → IN_PROGRESS`, and it is the same operation that re-enters the loop after a failure, moving `FAILED → IN_PROGRESS`.
    PRD: On entry the server stamps `started_at` and `performed_by_user_id` from the acting `X-User-ID`, increments `attempt_count` by 1, and clears the measurement fields: `disassembled_component_count` back to 0, and `atp_rlu`, `allergen_swab_result` and `failed_reason` back to null.
    PRD: Note what does *not* happen: the line stays `RESTRICTED` even after a later clean on it passes validation, because the `MAJOR` corrective action is still unverified.
    PRD: An `outcome` of `PASS` moves the action `VERIFICATION_PENDING → VERIFIED`, stamps `verified_at` and `verified_by_user_id`, decrements the line's `open_corrective_action_count`, and recomputes the posture — which may move the line `FROZEN → RESTRICTED` or `FROZEN → OPEN` depending on what else is still open.

    Design: Corner/state_machines/corner_fresh_pass_does_not_clear_unverified_corrective_action
    """
    world = fx.build_world(api, stop_after=fx.STOP_RECEIPT_ACCEPTED)
    cancelled_run = fx.plan_run(
        api, world.line_id, world.product_id, world.spec_id, world.wash_system_id
    )
    failed = _clean_failing_on_atp(api, world)
    action_id = fx.list_line_corrective_actions(api, world.line_id)[0]["id"]
    next_run = fx.plan_run(
        api,
        world.line_id,
        world.product_id,
        world.spec_id,
        world.wash_system_id,
        planned_start_at=NEXT_DAY_START_AT,
        planned_end_at=NEXT_DAY_END_AT,
    )

    restarted = fx.start_sanitation(api, failed["id"], USER_SANITATION_TECH_B)
    assert restarted["status"] == c.SANITATION_IN_PROGRESS
    assert restarted["attempt_count"] == SECOND_ATTEMPT
    assert restarted["atp_rlu"] is None
    assert restarted["disassembled_component_count"] == RESET_COMPONENT_COUNT
    assert restarted["failed_reason"] is None
    assert restarted["performed_by_user_id"] == USER_SANITATION_TECH_B

    fx.submit_sanitation(api, failed["id"], USER_SANITATION_TECH_B)
    revalidated = fx.validate_sanitation(
        api, failed["id"], c.OUTCOME_PASS, USER_QA_TECH_A
    )
    assert revalidated["status"] == c.SANITATION_VALIDATED
    a.assert_instant(revalidated["validated_at"], "validated_at")

    restricted = fx.read_line(api, world.line_id)
    a.assert_instant_equals(
        restricted["last_validated_sanitation_at"],
        revalidated["validated_at"],
        "last_validated_sanitation_at",
    )
    assert restricted["posture"] == c.POSTURE_RESTRICTED
    validate_error(
        api.start_process_run(next_run["id"], LINE_OPERATOR_HEADERS),
        ApiErrorId.LINE_NOT_OPEN,
    )

    verified = fx.verified_corrective_action(
        api, action_id, implemented_by=USER_QA_TECH_C, verified_by=USER_QA_MANAGER_A
    )
    assert verified["status"] == c.CA_VERIFIED
    a.assert_instant(verified["verified_at"], "verified_at")
    assert verified["verified_by_user_id"] == USER_QA_MANAGER_A

    opened = fx.read_line(api, world.line_id)
    assert opened["open_corrective_action_count"] == 0
    assert opened["posture"] == c.POSTURE_OPEN

    # Opening the line only exposes the next gate; the flume is still dirty.
    validate_error(
        api.start_process_run(next_run["id"], LINE_OPERATOR_HEADERS),
        ApiErrorId.WASH_SYSTEM_DUMP_REQUIRED,
    )
    assert fx.read_run(api, cancelled_run["id"])["run_status"] == c.RUN_CANCELLED, (
        "no sweep in this document is self-reversing"
    )


def test_a_clean_cannot_begin_around_moving_product_but_may_once_the_run_closes(api):
    """The block is keyed on a RUNNING run, so the close releases it.

    PRD: Beginning a clean is also refused while any run on the same line has `run_status` of `RUNNING`, with `ERR_LINE_RUN_IN_PROGRESS` (HTTP 409) — equipment cannot be disassembled around moving product.
    PRD: The server assigns the next `sequence_no` for that line, counting from 1, and creates the event in `SCHEDULED` with `attempt_count` at 0.

    Design: Corner/state_machines/corner_sanitation_start_blocked_while_a_run_is_running
    """
    world = fx.build_world(api, stop_after=fx.STOP_TWO_READINGS)
    assert fx.read_run(api, world.run_id)["run_status"] == c.RUN_RUNNING

    event = fx.schedule_sanitation(
        api,
        world.line_id,
        shift=c.SHIFT_SECOND,
        scheduled_for=SECOND_SHIFT_SCHEDULED_FOR,
    )
    assert event["sequence_no"] == SECOND_EVENT_SEQUENCE
    assert event["status"] == c.SANITATION_SCHEDULED

    validate_error(
        api.start_sanitation_event(
            event["id"], make_sanitation_tech_headers(USER_SANITATION_TECH_B)
        ),
        ApiErrorId.LINE_RUN_IN_PROGRESS,
    )
    a.assert_empty_page(
        api.list_sanitation_events(
            world.line_id,
            make_sanitation_tech_headers(USER_SANITATION_TECH_B),
            {"status": c.SANITATION_IN_PROGRESS},
        )
    )

    fx.set_clock(api, c.CLOCK_CLOSE)
    assert fx.close_run(api, world.run_id)["run_status"] == c.RUN_CLOSED

    started = fx.start_sanitation(api, event["id"], USER_SANITATION_TECH_B)
    assert started["status"] == c.SANITATION_IN_PROGRESS
    assert started["performed_by_user_id"] == USER_SANITATION_TECH_B
    assert started["attempt_count"] == 1


def test_a_swab_cannot_jump_to_confirmed_or_move_again_once_negative(api):
    """The confirmation cascade is unreachable in one hop, and NEGATIVE is terminal.

    PRD: A `PENDING` swab accepts `NEGATIVE` or `PRESUMPTIVE_POSITIVE`.
    PRD: A swab that has already reached `NEGATIVE` or `CONFIRMED_POSITIVE` accepts nothing further. Anything else is refused with `ERR_SWAB_INVALID_RESULT_TRANSITION` (HTTP 409).
    PRD: Every accepted result stamps `resulted_at` from the logical clock and `resulted_by_user_id` from the acting `X-User-ID`, and recomputes the line's posture.

    Design: Corner/state_machines/corner_swab_cannot_skip_the_presumptive_step
    """
    world = fx.master_data_world(api)
    contact = fx.create_swab(api, world.line_id, **CONTACT_SWAB_OVERRIDES)
    drain = fx.create_swab(api, world.line_id, **DRAIN_SWAB_OVERRIDES)

    validate_error(
        api.record_swab_result(
            contact["id"],
            f.swab_result_payload(c.SWAB_RESULT_CONFIRMED_POSITIVE),
            QA_TECHNICIAN_HEADERS,
        ),
        ApiErrorId.SWAB_INVALID_RESULT_TRANSITION,
    )

    resolved = fx.record_swab_result(
        api,
        drain["id"],
        c.SWAB_RESULT_NEGATIVE,
        make_qa_technician_headers(USER_QA_TECH_C),
    )
    assert resolved["result"] == c.SWAB_RESULT_NEGATIVE
    assert resolved["resulted_by_user_id"] == USER_QA_TECH_C
    a.assert_instant_equals(resolved["resulted_at"], c.CLOCK_MASTER_DATA, "resulted_at")

    for repeat in (c.SWAB_RESULT_NEGATIVE, c.SWAB_RESULT_PRESUMPTIVE_POSITIVE):
        validate_error(
            api.record_swab_result(
                drain["id"], f.swab_result_payload(repeat), QA_TECHNICIAN_HEADERS
            ),
            ApiErrorId.SWAB_INVALID_RESULT_TRANSITION,
        )

    rows = a.assert_page(
        api.list_environmental_swabs(world.line_id, QA_TECHNICIAN_HEADERS),
        expected_total=2,
    )
    by_id = {row["id"]: row["result"] for row in rows}
    assert by_id[contact["id"]] == c.SWAB_RESULT_PENDING
    assert by_id[drain["id"]] == c.SWAB_RESULT_NEGATIVE

    # None of the refused calls opened an action, and no clean has passed yet.
    line = fx.read_line(api, world.line_id)
    assert line["posture"] == c.POSTURE_RESTRICTED
    assert line["open_corrective_action_count"] == 0


def test_a_failed_verification_reopens_the_action_and_clears_the_narrative(api):
    """The implement-and-verify cycle is unbounded, and only a PASS ends it.

    PRD: The server writes `failed_reason` by examining three candidate reasons in exactly this order and taking the first that applies: `ATP_ABOVE_LIMIT` when the ATP reading exceeds the line limit, then `ALLERGEN_POSITIVE` when the allergen swab came back positive, then `MANUAL_FAIL`.
    PRD: An `outcome` of `FAIL` moves the action `VERIFICATION_PENDING → IN_PROGRESS`, increments `reopen_count` by 1, clears `action_taken`, and leaves the line's posture exactly as it was.
    PRD: Any of these three operations attempted from the wrong state is refused with `ERR_CORRECTIVE_ACTION_INVALID_STATE` (HTTP 409): taking ownership requires `OPEN`, submitting requires `IN_PROGRESS`, and verifying requires `VERIFICATION_PENDING`.

    Design: Corner/state_machines/corner_corrective_action_verify_fail_reopens_the_cycle
    """
    world = fx.build_world(api, stop_after=fx.STOP_RECEIPT_ACCEPTED)
    # Measurements are compliant (ATP at or under the line limit, allergen swab
    # NEGATIVE), so the explicit FAIL verdict is the only applicable reason and
    # the first two candidates do not apply.
    failed = fx.failed_sanitation(api, world.line_id)
    assert failed["failed_reason"] == c.FAILED_MANUAL_FAIL, (
        "an explicit FAIL is recorded as MANUAL_FAIL"
    )

    action = fx.list_line_corrective_actions(api, world.line_id)[0]
    assert action["status"] == c.CA_OPEN
    assert action["reopen_count"] == 0
    assert action["action_taken"] is None
    implementer = make_qa_technician_headers(USER_QA_TECH_C)

    owned = validate_success(api.start_corrective_action(action["id"], implementer))
    assert owned["status"] == c.CA_IN_PROGRESS
    assert owned["implemented_by_user_id"] == USER_QA_TECH_C
    validate_error(
        api.start_corrective_action(action["id"], implementer),
        ApiErrorId.CORRECTIVE_ACTION_INVALID_STATE,
    )

    submitted = validate_success(
        api.submit_corrective_action_verification(
            action["id"],
            f.corrective_action_submission_payload(action_taken=FIRST_NARRATIVE),
            implementer,
        )
    )
    assert submitted["status"] == c.CA_VERIFICATION_PENDING
    assert submitted["action_taken"] == FIRST_NARRATIVE

    reopened = validate_success(
        api.verify_corrective_action(
            action["id"],
            f.outcome_payload(c.OUTCOME_FAIL),
            make_qa_manager_headers(USER_QA_MANAGER_A),
        )
    )
    assert reopened["status"] == c.CA_IN_PROGRESS
    assert reopened["reopen_count"] == 1
    assert reopened["action_taken"] is None
    assert reopened["verified_at"] is None
    assert reopened["verified_by_user_id"] is None

    still_shut = fx.read_line(api, world.line_id)
    assert still_shut["posture"] == c.POSTURE_RESTRICTED
    assert still_shut["open_corrective_action_count"] == 1

    resubmitted = validate_success(
        api.submit_corrective_action_verification(
            action["id"],
            f.corrective_action_submission_payload(action_taken=SECOND_NARRATIVE),
            implementer,
        )
    )
    assert resubmitted["status"] == c.CA_VERIFICATION_PENDING
    assert resubmitted["action_taken"] == SECOND_NARRATIVE


def test_three_indeterminate_rounds_exhaust_the_hold_and_the_rejection_destroys_the_pack(api):
    """The fourth sample is refused, and the escape hatch keeps the counters summing.

    PRD: It is refused with `ERR_MAX_RETEST_ROUNDS_EXCEEDED` (HTTP 409) unless `test_round` is strictly below 3, so a fourth sample against the same hold is never accepted.
    PRD: A successful submission increments `test_round` by 1, records the assay, clears `latest_test_result`, `latest_apc_cfu_g` and `resulted_by_user_id` from any earlier round, and moves the hold `HELD → UNDER_TEST` or `RETEST_REQUIRED → UNDER_TEST`.
    PRD: A result of `NEGATIVE` or `POSITIVE` leaves the hold in `UNDER_TEST` — a self-loop, so one round can be resulted and then acted on — while a result of `INDETERMINATE` moves the hold `UNDER_TEST → RETEST_REQUIRED` and leaves `test_round` unchanged, which means the next submission consumes one of the three rounds.
    PRD: It stamps `closed_at` and `released_by_user_id`, moves the hold to `REJECTED`, moves the run's disposition to the terminal `REJECTED`, and moves every case of the run with `status` of `ON_HOLD` to `DESTROYED`, recomputing `cases_on_hold` and `cases_destroyed` so that the four counters still sum to `cases_produced`.

    Design: Corner/state_machines/corner_hold_retest_rounds_exhaust_then_reject_destroys_cases
    """
    world = fx.closed_world(api)
    assert world.hold["test_round"] == 0
    assert world.hold["status"] == c.HOLD_HELD
    tester = make_qa_technician_headers(USER_QA_TECH_B)

    for expected_round in (1, 2, 3):
        under_test = fx.submit_sample(api, world.hold_id, c.TEST_LISTERIA, tester)
        assert under_test["test_round"] == expected_round
        assert under_test["status"] == c.HOLD_UNDER_TEST
        assert under_test["latest_test_result"] is None
        assert under_test["latest_apc_cfu_g"] is None

        awaiting_retest = fx.record_result(
            api, world.hold_id, c.RESULT_INDETERMINATE, resulted_by=USER_QA_TECH_B
        )
        assert awaiting_retest["status"] == c.HOLD_RETEST_REQUIRED
        assert awaiting_retest["test_round"] == expected_round, (
            "an indeterminate result does not itself consume a round"
        )

        if expected_round == 1:
            validate_error(
                api.release_hold(
                    world.hold_id, make_qa_manager_headers(USER_QA_MANAGER_A)
                ),
                ApiErrorId.HOLD_INVALID_STATE,
            )

    validate_error(
        api.submit_hold_sample(
            world.hold_id, f.hold_sample_payload(c.TEST_LISTERIA), tester
        ),
        ApiErrorId.MAX_RETEST_ROUNDS_EXCEEDED,
    )

    rejected = fx.reject_hold(api, world.hold_id, rejected_by=USER_QA_MANAGER_A)
    assert rejected["status"] == c.HOLD_REJECTED
    a.assert_instant_equals(rejected["closed_at"], c.CLOCK_CLOSE, "closed_at")
    assert rejected["released_by_user_id"] == USER_QA_MANAGER_A

    run = fx.read_run(api, world.run_id)
    assert run["disposition_status"] == c.DISPOSITION_REJECTED
    a.assert_case_counters(
        run, available=0, on_hold=0, shipped=0, destroyed=c.CLOSE_CASES_PRODUCED
    )
    a.assert_case_counters_conserved(run)
    assert fx.list_cases(api, world.run_id, {"limit": c.MIN_LIMIT})[0]["status"] == (
        c.CASE_DESTROYED
    )

    validate_error(
        api.reject_hold(world.hold_id, make_qa_manager_headers(USER_QA_MANAGER_A)),
        ApiErrorId.HOLD_INVALID_STATE,
    )


def test_the_second_void_learns_the_version_first_and_the_state_second(api):
    """A stale replay reports the version; a current one reports the voided row.

    PRD: The two checks of §2.7 are evaluated after existence and before any state precondition, so a caller holding a stale version learns that before learning anything about the resource's lifecycle state.
    PRD: The void sets `status` to `VOIDED` and stamps `voided_at` from the logical clock, restores the load's `remaining_lb` to exactly its pre-consumption value, lowers the run's `input_lb` by exactly the same pounds, recomputes the wash system's `weighted_load_lb`, `organic_load_index` and `target_free_chlorine_ppm`, and increments the run's `version` by 1. No residue is left behind.

    Design: Corner/state_machines/corner_void_twice_is_refused
    """
    world = fx.build_world(api, stop_after=fx.STOP_RUN_CONSUMED)
    assert world.consumption["status"] == c.CONSUMPTION_ACTIVE
    assert world.consumption["recorded_by_user_id"] == USER_LINE_OPERATOR
    before_version = fx.read_run(api, world.run_id)["version"]

    voided = fx.void_consumption(api, world.consumption_id, before_version)
    assert voided["status"] == c.CONSUMPTION_VOIDED
    a.assert_instant_equals(voided["voided_at"], c.CLOCK_START, "voided_at")
    after_version = fx.read_run(api, world.run_id)["version"]
    assert after_version == before_version + 1

    validate_error(
        api.void_lot_consumption(
            world.consumption_id, f.void_payload(before_version), LINE_OPERATOR_HEADERS
        ),
        ApiErrorId.STALE_PROCESS_RUN_VERSION,
    )
    validate_error(
        api.void_lot_consumption(
            world.consumption_id, f.void_payload(after_version), LINE_OPERATOR_HEADERS
        ),
        ApiErrorId.CONSUMPTION_ALREADY_VOIDED,
    )
    # Neither refusal touched the run again.
    a.assert_version_is(fx.read_run(api, world.run_id), after_version, "process run")


def test_a_rejected_load_holds_no_pounds_and_never_scores_against_the_grower(api):
    """The reject branch leaves both pound fields null rather than zero.

    PRD: A rejected load moves `PENDING_INSPECTION → REJECTED` and its `accepted_lb` and `remaining_lb` are deliberately left null, which is what makes a rejected load permanently unusable rather than merely discouraged.
    PRD: `out_of_spec_receipt_count` is the number of this lot's loads whose `temp_grade` is `OUT_OF_SPEC` and whose `status` is not `REJECTED`; a rejected load never counts against the grower, however warm it arrived.
    PRD: The load must be `PENDING_INSPECTION`; a load already dispositioned or quarantined is refused with `ERR_RECEIPT_NOT_PENDING` (HTTP 409).

    Design: Corner/state_machines/corner_receipt_reject_branch_leaves_no_consumable_pounds
    """
    world = fx.build_world(api, stop_after=fx.STOP_RECEIPT_PENDING)
    assert world.receipt["net_weight_lb"] == c.RECEIPT_NET_WEIGHT_LB
    assert world.receipt["temp_grade"] == c.TEMP_IN_SPEC

    rejected = fx.disposition_receipt(
        api,
        world.receipt_id,
        c.DECISION_REJECT,
        trim_loss_lb=None,
        headers=make_qa_technician_headers(USER_QA_TECH_D),
    )
    assert rejected["status"] == c.RECEIPT_REJECTED
    assert rejected["accepted_lb"] is None
    assert rejected["remaining_lb"] is None
    assert rejected["trim_loss_lb"] is None
    assert rejected["dispositioned_by_user_id"] == USER_QA_TECH_D

    lot = fx.read_grower_lot(api, world.grower_lot_id)
    assert lot["out_of_spec_receipt_count"] == 0
    a.assert_risk_scores(
        lot, preharvest=c.RISK_START, trailing=c.RISK_START, status=c.LOT_APPROVED
    )

    validate_error(
        api.disposition_raw_receipt(
            world.receipt_id,
            f.disposition_payload(c.DECISION_ACCEPT, trim_loss_lb=0.00),
            QA_TECHNICIAN_HEADERS,
        ),
        ApiErrorId.RECEIPT_NOT_PENDING,
    )

    rows = a.assert_page(
        api.list_lot_raw_receipts(
            world.grower_lot_id,
            QA_MANAGER_HEADERS,
            {"status": c.RECEIPT_REJECTED, "limit": c.DEFAULT_LIMIT, "offset": 0},
        ),
        expected_total=1,
    )
    a.assert_row_ids(rows, [world.receipt_id])
