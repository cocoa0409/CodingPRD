"""Remaining coverage: suspension withdrawal, rework ceiling, freeze saga."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    get_success_data,
    make_worker_headers,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    REVIEWER,
    REVIEWER_TWO,
    attach_item,
    commit_label,
    create_gold_audit,
    create_program,
    create_unit,
    dispatch_panel,
    enroll_qualification,
    get_program,
    get_unit,
    grade_gold_audit,
    make_pool,
    open_program,
    pay_commit,
    production_commits,
    register_worker,
    setup_certified_standard_unit,
    setup_dispatched_item,
    verify_qualification,
    worker_for_commit,
)


def test_a_worker_role_cannot_reach_a_reviewer_exclusive_endpoint(api):
    """PRD §2.1: "Once headers are present, the acting role must be one of the
    roles the endpoint declares; a well-formed request from a role the endpoint
    does not admit is refused with `ERR_UNAUTHORIZED` (403)."

    Design: Corner/validations/worker_role_cannot_grade_a_gold_audit
    """
    from test_helpers import NON_EXISTENT_UUID

    worker = validate_success(
        api_client.register_worker({"handle": "nadia-hassan"}, TEST_USERS["anonymous_headers"]), 201
    )
    validate_error(
        api_client.reviewer_action(
            NON_EXISTENT_UUID,
            {"reviewer_action": "OPEN_REWORK"},
            make_worker_headers(worker["id"]),
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api_client.reviewer_action(
            NON_EXISTENT_UUID, {"reviewer_action": "OPEN_REWORK"}, REVIEWER
        ),
        "ERR_ITEM_NOT_FOUND",
        404,
    )


def test_rework_round_ceiling_leaves_the_point_ceiling_conserved(api):
    """PRD §3.11: "the multiplier is 1.0 normally and 1.2 while the unit holds at
    least one item whose `consensus_status` is `REWORK`, and the effective cost is
    the ceiling multiplied by that multiplier and rounded half up to a whole number
    of points."

    Design: Difficulty/compensating_invariant/rework_round_ceiling_leaves_conserved_quantity_fixed
    """
    program, unit, pool, item, commit = setup_certified_standard_unit(
        max_items=10, sensitivity_class="SENSITIVE"
    )
    before = get_unit(unit["id"])
    assert before["unit_ceiling_points"] == 20, "max_items 10 times the SENSITIVE weight of 2"
    assert before["unit_effective_points"] == 20, "no item is in REWORK yet"

    get_success_data(
        api_client.reviewer_action(item["id"], {"reviewer_action": "OPEN_REWORK"}, REVIEWER), 200
    )
    during = get_unit(unit["id"])
    assert during["rework_point_multiplier"] == pytest.approx(1.2)
    assert during["unit_effective_points"] == 24, "round_half_up(20 * 1.2) == 24"


def test_the_rework_surcharge_leaves_no_drift_once_the_round_lapses(api):
    """PRD §3.11: "the effective cost is the ceiling multiplied by that multiplier
    and rounded half up to a whole number of points. Both derived values are
    exposed on the unit as `unit_ceiling_points`, `unit_effective_points`, and
    `rework_point_multiplier`."

    PRD §3.11: "the engagement's `demand_points` is recomputed from
    `unit_effective_points`"

    Design: Difficulty/compensating_invariant/rework_round_ceiling_leaves_conserved_quantity_fixed
    """
    program, unit, pool, item, commit = setup_certified_standard_unit(
        max_items=10, sensitivity_class="SENSITIVE"
    )
    assert get_unit(unit["id"])["unit_effective_points"] == 20

    get_success_data(
        api_client.reviewer_action(item["id"], {"reviewer_action": "OPEN_REWORK"}, REVIEWER), 200
    )
    assert get_unit(unit["id"])["unit_effective_points"] == 24

    # Let the rework round lapse three times; PRD §3.6 gives one roll per
    # lapsed window, so each advance must clear the freshly reset 900s window,
    # and the third drives the piece to REJECTED.
    for minute in (16, 32, 48):
        get_success_data(
            api_client.set_clock(f"2026-09-01T00:{minute:02d}:00Z", ADMIN), 200
        )

    live = get_success_data(api_client.get_item(item["id"], ADMIN), 200)
    assert live["consensus_status"] == "REJECTED"
    assert live["holds_quorum"] is False

    after = get_unit(unit["id"])
    assert after["unit_effective_points"] == after["unit_ceiling_points"], (
        "with no item in REWORK the effective cost returns to the ceiling"
    )


def test_three_expired_rounds_drive_the_piece_to_rejected(api):
    """PRD §3.6: "when the same timeout occurs and `rework_cycles` is already **at**
    the round limit, the piece is not given another window: its `consensus_status`
    becomes `REJECTED`, `holds_quorum` becomes false, the container `status`
    becomes `RESOLVED`, and the `item_status` becomes `COMPLETED`. The
    `rework_round_limit` defaults to 3"

    Design: Difficulty/compensating_invariant/rework_round_ceiling_leaves_conserved_quantity_fixed
    """
    program, unit, pool, item, commit = setup_certified_standard_unit(
        max_items=10, rework_window_seconds=900
    )
    reworked = get_success_data(
        api_client.reviewer_action(item["id"], {"reviewer_action": "OPEN_REWORK"}, REVIEWER), 200
    )
    assert reworked["rework_cycles"] == 1
    assert reworked["rework_round_limit"] == 3

    for minute in (16, 32, 48):
        get_success_data(
            api_client.set_clock(f"2026-09-01T00:{minute:02d}:00Z", ADMIN), 200
        )

    live = get_success_data(api_client.get_item(item["id"], ADMIN), 200)
    assert live["consensus_status"] == "REJECTED"
    assert live["status"] == "RESOLVED"
    assert live["item_status"] == "COMPLETED"


def test_the_freeze_compensates_the_whole_production_state(api):
    """PRD §3.13: "Every **SpecUnit** under the engagement transitions to status
    `REJECTED` and `piece_status` `REJECTED`. Every **LabelingItem** under those
    units transitions to container `status` `RESOLVED`, `item_status`
    `COMPLETED`, and `consensus_status` `REJECTED`"

    Design: Corner/consistency_model/program_freeze_compensates_the_whole_production_state
    """
    program = create_program(commitment_quorum=2)
    unit = create_unit(program, unit_code="U-1", panel_size=2)
    open_program(program)
    # Four eligible workers so two consecutive panels can each be filled: the
    # second panel's members must not be the ones the first panel left in a
    # DISPATCHED lane, which PRD §3.4 excludes.
    pool = make_pool(4, "es-MX", "PROFICIENT")

    first = attach_item(unit, item_key="i-0001", payload_uri="s3://ax/0001")
    second = attach_item(unit, item_key="i-0002", payload_uri="s3://ax/0002")

    dispatched_first = dispatch_panel(first)
    member = production_commits(dispatched_first)[0]
    commit_label(member, worker_for_commit(member, pool), "A")

    dispatched_second = dispatch_panel(second)
    assert len(production_commits(dispatched_second)) == 2

    frozen = get_success_data(
        api_client.program_state(program["id"], {"program_action": "FREEZE"}, ADMIN), 200
    )
    assert frozen["status"] == "FROZEN"

    live_unit = get_unit(unit["id"])
    assert live_unit["status"] == "REJECTED"

    for item in (first, second):
        live = get_success_data(api_client.get_item(item["id"], ADMIN), 200)
        assert live["consensus_status"] == "REJECTED"
        assert live["status"] == "RESOLVED"


def test_the_freeze_expires_outstanding_assignments_but_keeps_committed_ones(api):
    """PRD §3.13: "every **Commit** on those pieces still in `DISPATCHED`
    transitions to `COMMIT_EXPIRED`."

    Design: Corner/consistency_model/program_freeze_compensates_the_whole_production_state
    """
    program = create_program(commitment_quorum=2)
    unit = create_unit(program, unit_code="U-1", panel_size=2)
    open_program(program)
    # Four eligible workers so two consecutive panels can each be filled: the
    # second panel's members must not be the ones the first panel left in a
    # DISPATCHED lane, which PRD §3.4 excludes.
    pool = make_pool(4, "es-MX", "PROFICIENT")

    first = attach_item(unit, item_key="i-0001", payload_uri="s3://ax/0001")
    second = attach_item(unit, item_key="i-0002", payload_uri="s3://ax/0002")

    dispatched_first = dispatch_panel(first)
    member = production_commits(dispatched_first)[0]
    committed = commit_label(member, worker_for_commit(member, pool), "A")

    dispatched_second = dispatch_panel(second)
    outstanding = production_commits(dispatched_second)

    get_success_data(api_client.program_state(program["id"], {"program_action": "FREEZE"}, ADMIN), 200)

    survivor = get_success_data(api_client.get_commit(member["id"], ADMIN), 200)
    assert survivor["status"] == "COMMITTED", "a committed answer is not rewound by the freeze"

    for commit in outstanding:
        live = get_success_data(api_client.get_commit(commit["id"], ADMIN), 200)
        assert live["status"] == "COMMIT_EXPIRED"


def test_a_third_failed_audit_suspends_and_withdraws_outstanding_work(api):
    """PRD §3.9: "A `PlatformReviewer` resets a qualification out of `PROBATION`,
    and that action requires that a **ConfidentialityIncident** naming the
    qualification's owner exists with status `OPEN`. Success sets the status to
    `SUSPENDED`"

    PRD §3.9: "every **Commit** owned by that worker which is still `DISPATCHED` on
    a non-terminal piece is withdrawn, the piece's `non_abstaining_commit_count` is
    decremented accordingly, and the piece is returned to `AWAITING_CONSENSUS` when
    the withdrawn assignment was the last outstanding one on it."

    Design: Difficulty/transitive_cascade/gold_failure_streak_suspension_cascade_depth_two
    """
    program = create_program(commitment_quorum=3)
    unit = create_unit(program, unit_code="U-1", panel_size=1, gold_rate=1.0)
    open_program(program)
    # Three eligible workers: a gold audit's ground truth comes from the piece's
    # own member, so the pool needs a second member to serve it, and the second
    # piece then needs a member whose lane the first dispatch window does not
    # already touch (PRD §3.4).
    pool = make_pool(3, "es-MX", "PROFICIENT")

    first = attach_item(unit, item_key="i-0001", payload_uri="s3://ax/0001")
    dispatched = dispatch_panel(first)
    commit = production_commits(dispatched)[0]
    worker = worker_for_commit(commit, pool)
    qualification = [q for w, q in pool if w["id"] == worker["id"]][0]
    commit_label(commit, worker, "A")

    for index in range(2):
        gold = create_gold_audit(commit, f"gold-{index + 1:06d}")
        grade_gold_audit(gold["id"], "FAILED", first["id"])

    qualifications = get_success_data(api_client.list_worker_qualifications(worker["id"], ADMIN), 200)
    assert qualifications[0]["gold_fail_streak"] == 2
    assert qualifications[0]["status"] == "PROBATION"
    assert qualifications[0]["tier_multiplier"] == pytest.approx(1.25), (
        "the demotion does not change the tier multiplier"
    )

    # A second piece whose assignment is still outstanding for this worker.
    second = attach_item(unit, item_key="i-0002", payload_uri="s3://ax/0002")
    outstanding = production_commits(dispatch_panel(second))
    assert len(outstanding) == 1
    assert outstanding[0]["worker_id"] == worker["id"]

    # The reviewer reset needs an open incident naming the qualification owner.
    get_success_data(
        api_client.create_incident(
            worker["id"],
            {
                "program_code": "AX-4410",
                "category": "PII_EXPOSURE",
                "severity": "MINOR",
                "description_text": "Observed breach.",
                "incident_action": "REPORT",
            },
            ADMIN,
        ),
        201,
    )

    suspended = get_success_data(
        api_client.worker_qualification_action(
            worker["id"],
            {"language_code": "es-MX", "tier": "PROFICIENT", "qualification_action": "RESET"},
            REVIEWER,
        ),
        200,
    )
    assert suspended["status"] == "SUSPENDED"
    assert suspended["gold_fail_streak"] == 0

    live_second = get_success_data(api_client.get_item(second["id"], ADMIN), 200)
    assert live_second["non_abstaining_commit_count"] == 0, "the outstanding assignment was withdrawn"
    assert live_second["consensus_status"] == "AWAITING_CONSENSUS"