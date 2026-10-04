"""Gold-standard audits, accuracy variants, rotation and qualification cycles."""
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
    production_commits,
    setup_certified_item,
    setup_dispatched_item,
    setup_graded_gold_audits,
    setup_program_with_unit,
    setup_rotated_item,
    setup_split_gold_audits,
    verify_qualification,
    worker_for_commit,
)


def test_accepted_and_provisional_accuracy_split_on_the_same_audit_set(api):
    """PRD §3.8: "The **accepted** variant counts only `PASSED` as a success, so a
    flagged audit lowers it. The **provisional** variant counts `PASSED` and
    `FLAGGED` together, so it is greater than or equal to the accepted variant on
    every possible input."

    Design: Difficulty/dual_variant_calc/accepted_vs_provisional_program_accuracy_split
    """
    program, unit, pool, items, commits, graded = setup_split_gold_audits(
        ["PASSED", "FLAGGED", "FLAGGED", "FLAGGED", "FAILED"],
        item_count=3,
        instruction_model="SAFETY_CLASSIFICATION",
    )
    read = get_program(program["id"])

    assert read["accuracy_denominator_count"] == 5, "PASSED and FAILED audits form the denominator"
    assert read["accepted_accuracy_pct"] == pytest.approx(20.0), "one PASSED of five"
    assert read["provisional_accuracy_pct"] == pytest.approx(80.0), "PASSED and FLAGGED of five"


def test_provisional_accuracy_is_never_below_accepted(api):
    """PRD §3.8: "The **provisional** variant counts `PASSED` and `FLAGGED`
    together, so it is greater than or equal to the accepted variant on every
    possible input."

    Design: Difficulty/dual_variant_calc/accepted_vs_provisional_program_accuracy_split
    """
    program, unit, pool, items, commits, graded = setup_split_gold_audits(
        ["PASSED", "FLAGGED", "FAILED"],
        item_count=1,
        instruction_model="SAFETY_CLASSIFICATION",
    )
    read = get_program(program["id"])

    assert read["accuracy_denominator_count"] == 3
    assert read["provisional_accuracy_pct"] >= read["accepted_accuracy_pct"]
    assert read["accepted_accuracy_pct"] == pytest.approx(33.33), "one PASSED of three, half up"


def test_cataloguing_an_audit_removes_it_from_both_variants(api):
    """PRD §3.7: "Because both accuracy variants draw their denominator from audits
    graded `PASSED` or `FAILED`, an audit graded `EXCLUDED_FROM_ACCURACY` sits
    outside both the numerator and the denominator, and so does an audit whose
    `gold_outcome` is still null."

    PRD §3.7: "Grading an audit `EXCLUDED_FROM_ACCURACY` therefore removes it from
    both variants rather than counting it as a failure or a success."

    Design: Corner/calculations/program_accuracy_excludes_catalogued_and_ungraded_audits
    """
    program, unit, pool, item, commits = setup_dispatched_item(panel_size=1, pool_size=3, gold_rate=1.0)
    commit = commits[0]
    commit_label(commit, worker_for_commit(commit, pool), "A")

    first = create_gold_audit(commit, "gold-000001")
    create_gold_audit(commit, "gold-000002")

    grade_gold_audit(first["id"], "EXCLUDED_FROM_ACCURACY", item["id"])

    read = get_program(program["id"])
    assert read["accuracy_denominator_count"] == 0, (
        "the catalogued audit and the still dispatched audit are both outside the denominator"
    )
    assert read["accepted_accuracy_pct"] == pytest.approx(0.0), (
        "an empty denominator reads zero rather than raising"
    )

    gold_commits = [
        c for c in get_success_data(api_client.list_commits(item["id"], REVIEWER, {"kind": "GOLD"}), 200)
        if c.get("kind") == "GOLD"
    ]
    pending = [c for c in gold_commits if c.get("gold_outcome") is None]
    assert len(pending) == 1, "the ungraded audit is still awaiting its grade"

    grade_gold_audit(pending[0]["id"], "PASSED", item["id"])

    read = get_program(program["id"])
    assert read["accuracy_denominator_count"] == 1
    assert read["accepted_accuracy_pct"] == pytest.approx(100.0)


def test_two_decimal_half_up_rounding_on_accuracy(api):
    """PRD §2.8: "The accuracy percentages `accepted_accuracy_pct`,
    `provisional_accuracy_pct`, `accuracy_pct`, `provisional_accuracy_pct` on a
    qualification, `unit_accuracy_pct`, and `unit_provisional_accuracy_pct` are
    rounded half up to exactly 2 decimal places"

    Design: Corner/calculations/accuracy_uses_two_decimal_half_up_rounding
    """
    program, unit, pool, items, commits, graded = setup_split_gold_audits(
        ["PASSED", "PASSED", "FAILED"], item_count=1
    )
    read = get_program(program["id"])
    assert read["accepted_accuracy_pct"] == pytest.approx(66.67, abs=1e-9), "two of three, half up"
    assert read["accepted_accuracy_pct"] == round(read["accepted_accuracy_pct"], 2), (
        "exactly two decimal places, never more"
    )


def test_a_perfect_program_reads_exactly_one_hundred(api):
    """PRD §2.8: "The accuracy percentages `accepted_accuracy_pct`,
    `provisional_accuracy_pct`, `accuracy_pct`, `provisional_accuracy_pct` on a
    qualification, `unit_accuracy_pct`, and `unit_provisional_accuracy_pct` are
    rounded half up to exactly 2 decimal places, and each of them reads 0 when its
    denominator is zero rather than raising."

    Design: Difficulty/dual_variant_calc/accepted_vs_provisional_program_accuracy_split
    """
    program, unit, pool, items, commits, graded = setup_split_gold_audits(
        ["PASSED", "PASSED", "PASSED"], item_count=1
    )
    read = get_program(program["id"])
    assert read["accuracy_denominator_count"] == 3
    assert read["accepted_accuracy_pct"] == pytest.approx(100.0)
    assert read["provisional_accuracy_pct"] == pytest.approx(100.0)


def test_gold_rotation_blocks_a_fourth_audit_this_week(api):
    """PRD §3.7: "the flag is true while `gold_audits_this_week` is at or above 3
    and the piece's `consensus_status` is not `REWORK`. A piece with
    `gold_rotation` true cannot be dispatched back into a production panel, which
    is the `ERR_GOLD_ROTATION_ACTIVE` (409) refusal of §3.3."

    Design: Difficulty/boundary_precision_check/gold_rotation_boundary_at_exactly_three_audits
    """
    program, unit, pool, item, commits = setup_dispatched_item(panel_size=1, pool_size=3, gold_rate=1.0)
    commit = commits[0]
    commit_label(commit, worker_for_commit(commit, pool), "A")

    setup_rotated_item(commit, item, count=3)
    live = get_success_data(api_client.get_item(item["id"], ADMIN), 200)
    assert live["gold_audits_this_week"] == 3
    assert live["gold_rotation"] is True

    validate_error(
        api_client.create_gold_audit(commit["id"], {"gold_task_key": "gold-000004"}, REVIEWER),
        "ERR_GOLD_ROTATION_ACTIVE",
        409,
    )


def test_the_third_gold_audit_is_admitted_rather_than_the_fourth(api):
    """PRD §3.7: "`gold_audits_this_week` counts the gold audits dispatched against
    this piece since the current week epoch began, and `gold_rotation` is derived
    from it"

    Design: Difficulty/boundary_precision_check/gold_rotation_boundary_at_exactly_three_audits
    """
    program, unit, pool, item, commits = setup_dispatched_item(panel_size=1, pool_size=3, gold_rate=1.0)
    commit = commits[0]
    commit_label(commit, worker_for_commit(commit, pool), "A")

    for index in range(2):
        create_gold_audit(commit, f"gold-{index + 1:06d}")
    live = get_success_data(api_client.get_item(item["id"], ADMIN), 200)
    assert live["gold_audits_this_week"] == 2
    assert live["gold_rotation"] is False

    third = create_gold_audit(commit, "gold-000003")
    assert third["kind"] == "GOLD"
    live = get_success_data(api_client.get_item(item["id"], ADMIN), 200)
    assert live["gold_audits_this_week"] == 3, "the boundary is reached at exactly three"


def test_week_roll_resets_the_gold_rotation_counter(api):
    """PRD §2.9: "every piece's `gold_audits_this_week` returns to 0, and
    rehabilitation eligibility is measured against the new epoch index."

    Design: Corner/state_machines/gold_rotation_blocks_a_fourth_audit_this_week
    """
    program, unit, pool, item, commits = setup_dispatched_item(panel_size=1, pool_size=3, gold_rate=1.0)
    commit = commits[0]
    commit_label(commit, worker_for_commit(commit, pool), "A")

    setup_rotated_item(commit, item, count=3)
    live = get_success_data(api_client.get_item(item["id"], ADMIN), 200)
    assert live["gold_rotation"] is True

    get_success_data(api_client.set_clock("2026-09-08T00:00:00Z", ADMIN), 200)

    live = get_success_data(api_client.get_item(item["id"], ADMIN), 200)
    assert live["gold_audits_this_week"] == 0, "the weekly accumulator resets at the boundary"
    assert live["gold_rotation"] is False

    admitted = create_gold_audit(commit, "gold-000004")
    assert admitted["kind"] == "GOLD", "a fourth audit is admitted in the new epoch"


def test_two_failed_gold_audits_demote_a_qualified_worker_to_probation(api):
    """PRD §3.9: "When a gold audit is graded `FAILED` and the resulting
    `gold_fail_streak` is at or above 2 — that is, the grade that pushes the streak
    to two clears the threshold — the qualification's status becomes `PROBATION`.
    A single failed audit does not demote a qualified worker."

    Design: Difficulty/transitive_cascade/gold_failure_streak_suspension_cascade_depth_two
    """
    program, unit, pool, item, commits = setup_dispatched_item(panel_size=1, pool_size=3, gold_rate=1.0)
    commit = commits[0]
    worker = worker_for_commit(commit, pool)
    commit_label(commit, worker, "A")

    first = create_gold_audit(commit, "gold-000001")
    grade_gold_audit(first["id"], "FAILED", item["id"])
    qualifications = get_success_data(api_client.list_worker_qualifications(worker["id"], ADMIN), 200)
    assert qualifications[0]["gold_fail_streak"] == 1
    assert qualifications[0]["status"] == "QUALIFIED", "a single failure does not demote"

    second = create_gold_audit(commit, "gold-000002")
    grade_gold_audit(second["id"], "FAILED", item["id"])
    qualifications = get_success_data(api_client.list_worker_qualifications(worker["id"], ADMIN), 200)
    assert qualifications[0]["gold_fail_streak"] == 2
    assert qualifications[0]["status"] == "PROBATION"


def test_reviewer_holding_a_commit_cannot_grade_its_audit(api):
    """PRD §2.1: "That single guard covers reviewer tie-breaking on a held panel,
    gold-audit grading, and both the proposal and concurrence steps of the appeal
    lifecycle."

    Design: Difficulty/non_linear_state_machine/appeal_claim_reviewer_to_reviewer_cycle
    """
    program, unit, pool, item, commits = setup_dispatched_item(panel_size=1, pool_size=3, gold_rate=1.0)
    commit = commits[0]
    worker = worker_for_commit(commit, pool)
    commit_label(commit, worker, "A")

    gold = create_gold_audit(commit, "gold-000001")
    live = get_success_data(api_client.get_item(item["id"], ADMIN), 200)

    # The reviewer identity that owns the committed member carries the
    # PlatformReviewer role but is resolved by the same id the Commit carries,
    # so the segregation rule of PRD §2.1 — which "covers ... gold-audit
    # grading" — refuses it.
    from test_helpers import make_reviewer_headers

    own_reviewer = make_reviewer_headers(worker["id"])
    resp = api_client.grade_gold_audit(
        gold["id"], {"gold_outcome": "PASSED", "expected_item_version": live["version"]}, own_reviewer
    )
    validate_error(resp, "ERR_SEGREGATION_OF_DUTIES", 403)


def test_revoked_qualification_is_unroutable_and_blocked_at_verification(api):
    """PRD §3.9: "When the deterministic `qualification_score` is strictly below
    `tier_min_score` for the declared tier, the qualification's status becomes
    `REVOKED`, and every uncommitted **Commit** on that qualification is
    withdrawn."

    Design: Corner/state_machines/revoked_qualification_is_terminal_and_blocks_dispatch
    """
    program = create_program()
    unit = create_unit(program, unit_code="U-1", panel_size=1)
    open_program(program)
    worker = validate_success(
        api_client.register_worker({"handle": "sara-kowalski"}, TEST_USERS["anonymous_headers"]), 201
    )
    # sara-kowalski's deterministic es-MX score is 6390 (PRD §2.6), below the
    # PROFICIENT minimum of 6500, so the verification of the declared tier is
    # refused outright by PRD §2.6 as ERR_QUALIFICATION_SCORE_BELOW_TIER and the
    # qualification never reaches a routable status.
    enrollment = enroll_qualification(worker, "es-MX", "PROFICIENT", training_required_count=0)
    assert enrollment["status"] == "IN_TRAINING"
    assert enrollment["qualification_score"] == 6390

    item = attach_item(unit, item_key="i-0001")

    validate_error(
        api_client.worker_qualification_action(
            worker["id"],
            {"language_code": "es-MX", "tier": "PROFICIENT", "qualification_action": "VERIFY"},
            ADMIN,
        ),
        "ERR_QUALIFICATION_SCORE_BELOW_TIER",
        422,
    )

    # The qualification is still unroutable, so a dispatch finds no candidate.
    validate_error(api_client.dispatch_panel(item["id"], ADMIN), "ERR_NO_ELIGIBLE_WORKER", 422)

    # The same handle verified at NOVICE clears the lower minimum.
    novice = verify_qualification(worker, "es-MX", "NOVICE")
    assert novice["status"] == "QUALIFIED"
    assert novice["tier_min_score"] == 5000


def test_verification_requires_the_training_count(api):
    """PRD §2.6: "The `VERIFY` action enforces two gates: `training_passed_count`
    must be at least `training_required_count`, and `qualification_score` must be
    at or above `tier_min_score`"

    Design: Corner/state_machines/revoked_qualification_is_terminal_and_blocks_dispatch
    """
    from test_helpers import create_worker_payload

    worker = validate_success(
        api_client.register_worker(create_worker_payload(handle="mira-vega"), TEST_USERS["anonymous_headers"]),
        201,
    )
    enrolled = enroll_qualification(worker, "es-MX", "PROFICIENT", training_required_count=3)
    assert enrolled["status"] == "IN_TRAINING"
    assert enrolled["training_required_count"] == 3
    assert enrolled["training_passed_count"] == 0

    # PRD §2.6: the training gate refuses the ascent while training_passed_count
    # still trails training_required_count, so the qualification stays enrolled.
    validate_error(
        api_client.worker_qualification_action(
            worker["id"],
            {"language_code": "es-MX", "tier": "PROFICIENT", "qualification_action": "VERIFY"},
            ADMIN,
        ),
        "ERR_INVALID_STATE",
        409,
    )
    qualifications = get_success_data(api_client.list_worker_qualifications(worker["id"], ADMIN), 200)
    assert qualifications[0]["status"] == "IN_TRAINING"