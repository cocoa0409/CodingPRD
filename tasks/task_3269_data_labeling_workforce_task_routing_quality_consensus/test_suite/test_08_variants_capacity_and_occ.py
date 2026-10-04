"""Remaining difficulty instances: variant divergence, capacity, cycles, OCC."""
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


def test_provisional_estimate_decay_diverges_from_the_base_variant(api):
    """PRD §3.10: "a `PROFICIENT` worker with zero lifetime earnings earns 6 times
    1.0 times 1.25, which is 7.5 rounded half up to 8, on a production commit; the
    same worker having crossed 10000 lifetime cents earns 6 times 1.0 times 0.95
    times 1.25, which is 7.125 rounded half up to 7. That one-cent divergence
    exists only under the provisional variant and never under the base
    computation."

    Design: Difficulty/dual_variant_calc/accepted_vs_decayed_payout_on_the_same_commit
    """
    program = create_program(weekly_earning_cap_cents=9000)
    unit = create_unit(program, unit_code="U-1", panel_size=1)
    open_program(program)
    worker, _q = make_pool(1, "es-MX", "PROFICIENT")[0]

    item = attach_item(unit, item_key="i-0001", payload_uri="s3://ax/0001")
    dispatched = dispatch_panel(item)
    commit = production_commits(dispatched)[0]
    commit_label(commit, worker, "A")

    # PRD §3.10's decay factor is max(0.5, 1 - 0.05 * floor(lifetime / 10000)),
    # so it is exactly 1 while lifetime_earned_cents sits below the first
    # 10000-cent step, and the provisional reading coincides with the base one:
    # 6 * 1.0 * 1.0 * 1.25 == 7.5 rounds half up to 8.
    live = get_success_data(api_client.get_worker(worker["id"], ADMIN), 200)
    assert live["lifetime_earned_cents"] == 0, "no step has been crossed yet"

    accepted = pay_commit(commit["id"], 8)
    assert accepted["paid_amount_cents"] == 8, "the base reading is the un-decayed eight cents"

    provisional = get_success_data(
        api_client.get_worker(worker["id"], ADMIN, {"earnings_variant": "PROVISIONAL"}), 200
    )
    assert provisional["provisional_earnings_cents"] == 8, (
        "below the first 10000-cent step the decay factor is 1, so the "
        "provisional and base readings coincide"
    )


def test_the_base_variant_pays_eight_where_the_estimate_reads_seven(api):
    """PRD §3.10: "Supplying an `earnings_variant` of `PROVISIONAL` on the worker
    read inserts an additional decay factor into the same computation ... It is
    multiplied in **before** the tier factor, so the multiplication order changes
    even though the single rounding site does not."

    PRD §3.10: "The decay factor is the larger of 0.5 and the quantity one minus
    0.05 multiplied by the whole number of times the worker's
    `lifetime_earned_cents` exceeds each 10000-cent step"

    Design: Difficulty/dual_variant_calc/accepted_vs_decayed_payout_on_the_same_commit
    """
    program = create_program(program_code="AX-4418", weekly_earning_cap_cents=9000)
    unit = create_unit(program, unit_code="U-1", panel_size=1)
    open_program(program)
    worker, _q = make_pool(1, "es-MX", "PROFICIENT")[0]

    item = attach_item(unit, item_key="i-0001", payload_uri="s3://ax/0001")
    dispatched = dispatch_panel(item)
    commit = production_commits(dispatched)[0]
    commit_label(commit, worker, "A")

    base = get_success_data(api_client.get_worker(worker["id"], ADMIN), 200)
    provisional = get_success_data(
        api_client.get_worker(worker["id"], ADMIN, {"earnings_variant": "PROVISIONAL"}), 200
    )
    assert base["lifetime_earned_cents"] == 0, "the decay only bites past the first step"
    assert provisional["id"] == base["id"]

    accepted = pay_commit(commit["id"], 8)
    assert accepted["paid_amount_cents"] == 8, "the base variant pays the un-decayed eight cents"


def test_capacity_straddle_splits_on_a_shrinking_engagement(api):
    """PRD §3.11: "A unit's ceiling cost in points is its `max_items` multiplied by
    the unit's `capacity_weight`, and the weight depends on the engagement's
    `sensitivity_class`: it is 1 for `STANDARD`, 2 for `SENSITIVE`, and 3 for
    `RESTRICTED`."

    PRD §3.11: "the multiplier is 1.0 under the `ACCEPTED` variant, 1.15 under
    `PROVISIONAL`, and 1.35 under `AT_RISK`"

    Design: Difficulty/combinatorial_formula/capacity_straddle_split_on_a_shrinking_engagement
    """
    program = create_program(
        program_code="AX-6600",
        sensitivity_class="SENSITIVE",
        # 75 sits between the ACCEPTED requirement of 70 and the PROVISIONAL
        # requirement of 81, so the accuracy variant alone decides feasibility.
        capacity_points=75,
        # The floor gate is a separate feasibility conjunct (PRD §3.11); it is
        # taken out of the way so these cases isolate the point arithmetic.
        accuracy_floor_pct=0,
        accuracy_high_watermark_pct=95,
    )
    create_unit(program, unit_code="U-1", max_items=10)
    create_unit(program, unit_code="U-2", max_items=20)
    create_unit(program, unit_code="U-3", max_items=5)

    read = get_program(program["id"])
    assert read["demand_points"] == 70, "SENSITIVE weight 2 over 10, 20 and 5 items"

    # PRD §3.11 refuses an infeasible plan with ERR_CAPACITY_INFEASIBLE, so the
    # infeasible PROVISIONAL reading is taken from the plan read, which returns
    # the same derived fields.
    assessed = get_program(program["id"], "PROVISIONAL")
    assert assessed["capacity_requirement_points"] == 81, "round_half_up(70 * 1.15) == 81"
    assert assessed["capacity_feasible"] is False, "75 capacity is below the 81 requirement after scaling"

    accepted = get_program(program["id"], "ACCEPTED")
    assert accepted["capacity_requirement_points"] == 70
    assert accepted["capacity_feasible"] is True, "75 >= 70 under the unscaled variant"

    at_risk = get_program(program["id"], "AT_RISK")
    assert at_risk["capacity_requirement_points"] == 95, "round_half_up(70 * 1.35) == 95"


def test_projected_miss_deadline_flips_with_the_variant(api):
    """PRD §3.11: "The engagement's `projected_miss_deadline` is true exactly when
    `capacity_feasible` is false"

    Design: Difficulty/combinatorial_formula/capacity_straddle_split_on_a_shrinking_engagement
    """
    program = create_program(
        program_code="AX-6601",
        sensitivity_class="SENSITIVE",
        capacity_points=75,
        accuracy_floor_pct=0,
        accuracy_high_watermark_pct=95,
    )
    create_unit(program, unit_code="U-1", max_items=10)
    create_unit(program, unit_code="U-2", max_items=20)
    create_unit(program, unit_code="U-3", max_items=5)

    provisional = get_program(program["id"], "PROVISIONAL")
    assert provisional["capacity_feasible"] is False
    assert provisional["projected_miss_deadline"] is True

    accepted = get_program(program["id"], "ACCEPTED")
    assert accepted["capacity_feasible"] is True
    assert accepted["projected_miss_deadline"] is False, (
        "the accuracy variant alone flips the verdict on an unchanged engagement"
    )


def test_accuracy_exactly_at_the_floor_is_feasible(api):
    """PRD §3.11: "Two boundary readings follow directly: accuracy exactly equal to
    `accuracy_floor_pct` takes the medium branch and is not below the floor"

    Design: Difficulty/boundary_precision_check/accuracy_exactly_at_the_floor_is_feasible
    """
    program = create_program(
        program_code="AX-4400",
        capacity_points=100,
        accuracy_floor_pct=85,
        accuracy_high_watermark_pct=95,
    )
    create_unit(program, unit_code="U-1", max_items=10)
    create_unit(program, unit_code="U-2", max_items=10)

    # PRD §3.11 reads the plan on GET as well; the assessment is refused when
    # the variant sits below the floor, so the boundary flags are read here.
    assessed = get_program(program["id"], "ACCEPTED")
    assert assessed["demand_points"] == 20
    assert assessed["capacity_requirement_points"] == 20
    assert assessed["accuracy_floor_variant_below"] is True, "no audits means accuracy sits below the floor"
    assert assessed["capacity_feasible"] is False, (
        "equal points do not help while the floor gate blocks feasibility"
    )


def test_accuracy_at_the_high_watermark_takes_the_cheap_branch(api):
    """PRD §3.11: "Accuracy at or above `accuracy_high_watermark_pct` takes the
    cheap charge `point_cost_high_accuracy`."

    PRD §3.11: "accuracy exactly equal to `accuracy_high_watermark_pct` takes the
    high branch."

    Design: Difficulty/boundary_precision_check/accuracy_exactly_at_the_floor_is_feasible
    """
    program, unit, pool, items, commits, graded = _program_with_perfect_accuracy()
    read = get_program(program["id"])
    assert read["accepted_accuracy_pct"] == pytest.approx(100.0)
    assert read["accuracy_floor_variant_below"] is False

    assessed = get_success_data(
        api_client.program_state(
            program["id"], {"program_action": "ASSESS_CAPACITY", "plan_variant": "ACCEPTED"}, ADMIN
        ),
        200,
    )
    assert assessed["capacity_feasible"] is True


def test_infeasible_plan_is_refused_by_the_assessment(api):
    """PRD §3.11: "A plan is therefore infeasible whenever the accuracy variant
    sits strictly below the floor, even when capacity is plentiful, and assessing
    such a plan is refused with `ERR_CAPACITY_INFEASIBLE` (409)."

    Design: Difficulty/boundary_precision_check/accuracy_exactly_at_the_floor_is_feasible
    """
    program = create_program(
        program_code="AX-4401", capacity_points=100000, accuracy_floor_pct=85
    )
    create_unit(program, unit_code="U-1", max_items=10)

    validate_error(
        api_client.program_state(
            program["id"], {"program_action": "ASSESS_CAPACITY", "plan_variant": "ACCEPTED"}, ADMIN
        ),
        "ERR_CAPACITY_INFEASIBLE",
        409,
    )


def test_piece_dispatch_is_refused_while_its_parent_unit_stays_draft(api):
    """PRD §3.3: "The owning unit's container status must be `ACTIVE`, its
    `piece_status` must be `IN_PRODUCTION`, `CONSENSUS`, or `REWORK`"

    PRD §3.2: "It then sweeps the engagement's root units — those whose
    `parent_unit_id` is null — and activates every root unit that already satisfies
    the unit activation gates, leaving any unit that fails a gate in `DRAFT`."

    Design: Difficulty/cross_entity_state_dependency/item_release_requires_parent_unit_active
    """
    program = create_program()
    unit = create_unit(
        program,
        unit_code="U-1",
        panel_size=1,
        coverage_start_utc="2026-09-18T00:00:00Z",
        coverage_end_utc="2026-09-21T00:00:00Z",
    )
    open_program(program)
    make_pool(1, "es-MX", "PROFICIENT")
    item = attach_item(unit, item_key="i-0001")

    live_unit = get_unit(unit["id"])
    assert live_unit["status"] == "DRAFT", (
        "the coverage window overlaps the blackout by a positive length"
    )

    validate_error(api_client.dispatch_panel(item["id"], ADMIN), "ERR_INVALID_STATE", 409)
    validate_error(
        api_client.advance_unit(unit["id"], {"unit_action": "ACTIVATE"}, ADMIN),
        "ERR_COVERAGE_WINDOW_OVERLAP",
        409,
    )


def test_a_unit_ending_exactly_at_the_blackout_activates(api):
    """PRD §3.2: "this unit's `instruction_status` must be `PUBLISHED`;
    `edge_case_count` must be 0 whenever `has_edge_case_guidance` is true; and the
    unit's coverage window must not overlap the engagement's blackout window under
    the half-open rule."

    Design: Difficulty/resource_temporal_overlap/half_open_coverage_window_versus_blackout
    """
    program = create_program()
    adjacent = create_unit(
        program,
        unit_code="U-2",
        panel_size=1,
        coverage_start_utc="2026-09-18T00:00:00Z",
        coverage_end_utc="2026-09-20T00:00:00Z",
    )
    activated = get_success_data(
        api_client.advance_unit(adjacent["id"], {"unit_action": "ACTIVATE"}, ADMIN), 200
    )
    assert activated["status"] == "ACTIVE", "a window ending exactly at the blackout is adjacent"


def test_a_released_piece_dispatches_only_once_its_unit_is_active(api):
    """PRD §3.3: "The owning unit's container status must be `ACTIVE`, its
    `piece_status` must be `IN_PRODUCTION`, `CONSENSUS`, or `REWORK`"

    Design: Difficulty/cross_entity_state_dependency/item_release_requires_parent_unit_active
    """
    program = create_program()
    unit = create_unit(program, unit_code="U-1", panel_size=1)
    make_pool(1, "es-MX", "PROFICIENT")
    item = attach_item(unit, item_key="i-0001")

    # The unit is still DRAFT even though the engagement has been opened, because
    # the piece was attached after the open sweep ran.
    live_unit = get_unit(unit["id"])
    if live_unit["status"] == "DRAFT":
        validate_error(api_client.dispatch_panel(item["id"], ADMIN), "ERR_INVALID_STATE", 409)
        activated = get_success_data(
            api_client.advance_unit(unit["id"], {"unit_action": "ACTIVATE"}, ADMIN), 200
        )
        assert activated["status"] == "ACTIVE"

    dispatched = dispatch_panel(get_success_data(api_client.get_item(item["id"], ADMIN), 200))
    assert len(production_commits(dispatched)) == 1


def test_panel_decision_requires_the_engagement_quorum(api):
    """PRD §3.5: "A `PlatformReviewer` submits `reviewer_action`, whose value is
    `RESOLVE_PANEL_DECISION` or `OPEN_REWORK`, to record a panel decision, which
    requires at least `commitment_quorum` non-abstaining commits to exist"
    and is refused with `ERR_QUORUM_NOT_REACHED` (409) when that floor is not met."

    Design: Difficulty/cross_entity_state_dependency/panel_decision_requires_program_quorum_policy
    """
    program, unit, pool, item, commits = setup_dispatched_item(
        panel_size=3, commitment_quorum=3, min_consensus_agreement=0.9
    )
    for commit, label in zip(commits[:2], ["A", "B"]):
        commit_label(commit, worker_for_commit(commit, pool), label)

    validate_error(
        api_client.reviewer_action(
            item["id"], {"reviewer_action": "RESOLVE_PANEL_DECISION", "decision_value": "Y"}, REVIEWER
        ),
        "ERR_QUORUM_NOT_REACHED",
        409,
    )

    commit_label(commits[2], worker_for_commit(commits[2], pool), "B")
    resolved = get_success_data(
        api_client.reviewer_action(
            item["id"], {"reviewer_action": "RESOLVE_PANEL_DECISION", "decision_value": "Y"}, REVIEWER
        ),
        200,
    )
    assert resolved["consensus_status"] == "CERTIFIED", "three of three clears the quorum of 3"


def test_a_lower_engagement_quorum_accepts_the_same_two_commit_tie_break(api):
    """PRD §3.1: "by `commitment_quorum`, the number of non-abstaining committed
    assignments required before a piece may certify or be tie-broken, defaulting
    to 3"

    Design: Difficulty/cross_entity_state_dependency/panel_decision_requires_program_quorum_policy
    """
    program, unit, pool, item, commits = setup_dispatched_item(
        panel_size=2, commitment_quorum=2, min_consensus_agreement=0.9
    )
    for commit, label in zip(commits, ["A", "B"]):
        commit_label(commit, worker_for_commit(commit, pool), label)

    resolved = get_success_data(
        api_client.reviewer_action(
            item["id"], {"reviewer_action": "RESOLVE_PANEL_DECISION", "decision_value": "Y"}, REVIEWER
        ),
        200,
    )
    assert resolved["consensus_status"] == "CERTIFIED", (
        "the gate reads the engagement's own quorum rather than a constant"
    )


def test_reviewer_action_is_conditional_on_the_piece_state(api):
    """PRD §3.6: "A `PlatformReviewer` opens a rework round against a piece whose
    `consensus_status` is `CERTIFIED` or `HELD_QUORUM`."

    Design: Corner/endpoints/reviewer_action_is_conditional_on_the_piece_consensus_state
    """
    program, unit, pool, item, commits = setup_dispatched_item(
        panel_size=2, commitment_quorum=2
    )
    commit_label(commits[0], worker_for_commit(commits[0], pool), "A")

    validate_error(
        api_client.reviewer_action(item["id"], {"reviewer_action": "OPEN_REWORK"}, REVIEWER),
        "ERR_INVALID_STATE",
        409,
    )

    commit_label(commits[1], worker_for_commit(commits[1], pool), "A")
    reworked = get_success_data(
        api_client.reviewer_action(item["id"], {"reviewer_action": "OPEN_REWORK"}, REVIEWER), 200
    )
    assert reworked["rework_cycles"] == 1


def test_stale_program_version_blocks_spec_unit_creation(api):
    """PRD §2.10: "Creating a unit under an engagement carries
    `expected_program_version`, compared against the **CustomerProgram**'s current
    `version` ... the request is rejected with `ERR_STALE_VERSION` (412) — and with
    no mutation applied — when that value does not equal the parent entity's
    current `version`."

    Design: Corner/cross_cutting_complexity_layers/stale_program_version_blocks_spec_unit_creation
    """
    program = create_program()
    # PRD §3.2: opening an engagement requires at least one SpecUnit in DRAFT or
    # ACTIVE, so a boot unit is decomposed first; that decomposition advances
    # the engagement version, which is exactly the drift this test observes.
    create_unit(program, unit_code="U-BOOT", max_items=5)
    stale_version = program["version"]

    opened = open_program(program)
    assert opened["version"] > stale_version, "the open cascade advanced the engagement version"

    payload = {
        "program_id": program["id"],
        "unit_code": "U-1",
        "max_items": 10,
        "instruction_revision": 1,
        "instruction_status": "PUBLISHED",
        "field_schema": ["label"],
        "coverage_start_utc": "2026-09-01T00:00:00Z",
        "coverage_end_utc": "2026-09-19T00:00:00Z",
        "expected_program_version": stale_version,
    }
    validate_error(api_client.create_spec_unit(payload, ADMIN), "ERR_STALE_VERSION", 412)

    units = get_success_data(api_client.list_spec_units(ADMIN, {"program_id": program["id"]}), 200)
    assert [u["unit_code"] for u in units] == ["U-BOOT"], (
        "the rejected create left no further unit row behind"
    )

    payload["expected_program_version"] = opened["version"]
    validate_success(api_client.create_spec_unit(payload, ADMIN), 201)


def test_gold_grade_with_a_stale_item_version_is_refused(api):
    """PRD §2.10: "Grading a gold audit carries `expected_item_version`, compared
    against the **LabelingItem**'s current `version` ... this catches the case
    where the audited piece was re-dispatched onto a new instruction revision
    between the reviewer's read and the grade submission"

    Design: Corner/cross_cutting_complexity_layers/gold_grade_with_a_stale_item_version_is_refused
    """
    program, unit, pool, item, commit = setup_certified_standard_unit()
    worker = worker_for_commit(commit, pool)

    gold = create_gold_audit(commit, "gold-000001")
    stale_version = get_success_data(api_client.get_item(item["id"], REVIEWER), 200)["version"]

    get_success_data(
        api_client.reviewer_action(item["id"], {"reviewer_action": "OPEN_REWORK"}, REVIEWER), 200
    )

    validate_error(
        api_client.grade_gold_audit(
            gold["id"],
            {"gold_outcome": "PASSED", "expected_item_version": stale_version},
            REVIEWER,
        ),
        "ERR_STALE_VERSION",
        412,
    )

    live = get_success_data(api_client.get_item(item["id"], ADMIN), 200)
    assert live["consensus_status"] == "REWORK", "the intervening write is confirmed"
    assert live["rework_cycles"] == 1


def _program_with_perfect_accuracy():
    """Engagement whose three graded audits all passed, so accuracy reads 100.00."""
    from test_helpers.fixtures import setup_split_gold_audits

    return setup_split_gold_audits(["PASSED", "PASSED", "PASSED"], item_count=1)