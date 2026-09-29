"""The two translation-unit axes and the three-way triage fork."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users


def _single_unit_market_at_lqa(api, title_code, name):
    world = fx.build_market(api, title_code=title_code, name=name,
                            market_code="JP", scope_tier="TEXT_ONLY",
                            target_rating="TEEN_12", budget_cap_cents=5000000,
                            key_specs=[f.MENU_KEY_SPEC], stage=fx.STAGE_LQA)
    world["unit"] = world["units"]["menu.start"]
    return world


def test_logging_a_functional_defect_moves_only_the_quality_axis(api):
    """A functional finding flags the unit without touching production state.

    "Logging a defect whose derived axis is functional drives the unit to
    `FUNC_FLAGGED`, but only from `NOT_CHECKED` or from `PASSED`; a unit already
    sitting at `LING_FLAGGED` is **not** overwritten by a functional finding."

    "`axis` is `LINGUISTIC` when `bug_class` is `MISTRANSLATION`, `CULTURAL` or
    `LEGAL_TEXT`, and `FUNCTIONAL` when it is `TEXT_OVERFLOW`, `TRUNCATION` or
    `FUNCTIONAL_CRASH`."

    A `TRUNCATION` defect of severity `S3` therefore weighs 2 points, flags the
    unit `FUNC_FLAGGED` and leaves `translation_status` at `DELIVERED`.

    Design: Difficulty/non_linear_state_machine/translation_unit_two_independent_status_axes
    """
    world = _single_unit_market_at_lqa(api, "NOVA-12", "Nova Drift 12")
    qa_pass = fx.open_qa_pass(api, world["plan"]["id"], "FUNCTIONAL", 50)

    bug = validate_success(
        api.create_lqa_bug(
            f.lqa_bug_payload(qa_pass["id"], bug_class="TRUNCATION", severity="S3",
                              summary="Ammo counter clipped at the HUD edge.",
                              translation_unit_id=world["unit"]["id"]),
            users.LQA_LOGGER,
        ),
        expected_status=201,
    )

    assert bug["axis"] == "FUNCTIONAL"
    assert bug["severity_weight"] == 2
    unit = fx.read_unit(api, world["unit"]["id"])
    assert unit["qa_status"] == "FUNC_FLAGGED"
    assert unit["translation_status"] == "DELIVERED"
    assert unit["open_bug_count"] == 1
    A.assert_defect_density(fx.read_qa_pass(api, qa_pass["id"])["defect_density"],
                            0.0400)
    assert fx.read_plan(api, world["plan"]["id"])["delivered_unit_count"] == 1


def test_qa_mark_passed_leaves_the_production_axis_where_it_was(api):
    """Recording a passing inspection never rewinds delivery.

    "A unit may reach `PASSED` from `NOT_CHECKED`, from `LING_FLAGGED` or from
    `FUNC_FLAGGED`, and all three routes carry exactly the same preconditions
    and the same effects: `qa_status` becomes `PASSED` and the unit's `version`
    increments by 1. `translation_status` does not move."

    "This action requires the unit's `translation_status` to be `DELIVERED` — a
    cross-axis guard, reported as `ERR_UNIT_NOT_DELIVERED` when it fails — and
    it may only advance a unit to `PASSED` when the unit's `open_bug_count` is
    zero and its `overflow_chars` is zero."

    Design: Difficulty/non_linear_state_machine/translation_unit_two_independent_status_axes
    """
    world = _single_unit_market_at_lqa(api, "NOVA-12", "Nova Drift 12")
    qa_pass = fx.open_qa_pass(api, world["plan"]["id"], "FUNCTIONAL", 50)
    bug = fx.log_bug(api, qa_pass["id"], bug_class="TRUNCATION", severity="S3",
                     summary="Ammo counter clipped at the HUD edge.",
                     translation_unit_id=world["unit"]["id"])
    flagged = fx.read_unit(api, world["unit"]["id"])
    assert flagged["qa_status"] == "FUNC_FLAGGED"
    fx.resolve_bug(api, bug["id"])
    cleared = fx.read_unit(api, world["unit"]["id"])
    assert cleared["open_bug_count"] == 0
    assert cleared["overflow_chars"] == 0

    marked = validate_success(
        api.qa_mark_translation_unit(world["unit"]["id"], f.qa_mark_payload("PASSED"),
                                     users.LQA_VERIFIER)
    )

    assert marked["qa_status"] == "PASSED"
    assert marked["translation_status"] == "DELIVERED"
    A.assert_version_bumped_by(marked, cleared, 1, "translation_unit")
    assert fx.read_plan(api, world["plan"]["id"])["delivered_unit_count"] == 1


def _pass_with_three_defects(api):
    world = _single_unit_market_at_lqa(api, "NOVA-14", "Nova Drift 14")
    qa_pass = fx.open_qa_pass(api, world["plan"]["id"], "FUNCTIONAL", 200)
    b1 = fx.log_bug(api, qa_pass["id"], bug_class="FUNCTIONAL_CRASH", severity="S1",
                    summary="Hard crash on the localized boot screen.")
    b2 = fx.log_bug(api, qa_pass["id"], bug_class="TRUNCATION", severity="S2",
                    summary="Ammo counter clipped at the HUD edge.")
    b3 = fx.log_bug(api, qa_pass["id"], headers=users.LQA_CLOSER,
                    bug_class="TRUNCATION", severity="S2",
                    summary="Ammo counter clipped - reported again by a second tester.")
    return world, qa_pass, b1, b2, b3


def test_accepting_a_defect_keeps_it_inside_the_open_set(api):
    """Triage by acceptance does not lower the density.

    "`ACCEPT` moves the defect `NEW → TRIAGED`. The pass's
    `weighted_defect_points` and `defect_density` are recomputed, and the
    figures do not fall, because a triaged defect stays in the open set."

    "Severity carries weight: `S1` weighs 8 points, `S2` weighs 4, `S3` weighs 2
    and `S4` weighs 1."

    One `S1` and two `S2` defects over 200 inspected units are 16 weighted
    points and a density of 0.0800, and accepting one of them leaves both
    figures exactly where they were.

    Design: Difficulty/non_linear_state_machine/lqa_bug_triage_fork_three_way_branch_with_terminal_lockdown
    """
    _world, qa_pass, b1, _b2, _b3 = _pass_with_three_defects(api)
    before = fx.read_qa_pass(api, qa_pass["id"])
    assert before["weighted_defect_points"] == 16
    A.assert_defect_density(before["defect_density"], 0.0800)

    triaged = validate_success(
        api.triage_lqa_bug(b1["id"], f.triage_payload("ACCEPT"), users.LQA_OPENER)
    )

    assert triaged["status"] == "TRIAGED"
    after = fx.read_qa_pass(api, qa_pass["id"])
    assert after["weighted_defect_points"] == 16
    A.assert_defect_density(after["defect_density"], 0.0800)


def test_rejecting_and_duplicating_both_drop_out_of_the_open_set(api):
    """The two terminal branches each lower the density.

    "`REJECT` moves the defect `NEW → REJECTED`. The pass's
    `weighted_defect_points` and `defect_density` are recomputed and drop,
    because the defect leaves the open set."

    "`DUPLICATE` moves the defect `NEW → DUPLICATE` and additionally requires a
    `duplicate_of_bug_id` in the payload."

    Rejecting one `S2` takes 16 points to 12 and 0.0800 to 0.0600; resolving the
    second `S2` as a duplicate of the `S1` takes them to 8 and 0.0400.

    Design: Difficulty/non_linear_state_machine/lqa_bug_triage_fork_three_way_branch_with_terminal_lockdown
    """
    _world, qa_pass, b1, b2, b3 = _pass_with_three_defects(api)
    fx.triage_bug(api, b1["id"], "ACCEPT", headers=users.LQA_OPENER)

    rejected = validate_success(
        api.triage_lqa_bug(b2["id"], f.triage_payload("REJECT"), users.LQA_OPENER)
    )
    assert rejected["status"] == "REJECTED"
    after_reject = fx.read_qa_pass(api, qa_pass["id"])
    assert after_reject["weighted_defect_points"] == 12
    A.assert_defect_density(after_reject["defect_density"], 0.0600)

    duplicated = validate_success(
        api.triage_lqa_bug(b3["id"], f.triage_payload("DUPLICATE", b1["id"]),
                           users.LQA_OPENER)
    )
    assert duplicated["status"] == "DUPLICATE"
    assert duplicated["duplicate_of_bug_id"] == b1["id"]
    after_duplicate = fx.read_qa_pass(api, qa_pass["id"])
    assert after_duplicate["weighted_defect_points"] == 8
    A.assert_defect_density(after_duplicate["defect_density"], 0.0400)


def test_fix_submission_holds_the_density_and_verification_clears_it(api):
    """A claimed fix stays open; only verification leaves the open set.

    "The pass's density is recomputed but does not change, because
    `FIX_SUBMITTED` is still inside the open set."

    "On success `verified_by_user_id` is set to the acting `X-User-ID`, the
    pass's `weighted_defect_points` and `defect_density` are recomputed and drop
    because the defect leaves the open set, the linked unit's `open_bug_count`
    is recomputed, and the defect's `version` increments by 1."

    Design: Difficulty/non_linear_state_machine/lqa_bug_triage_fork_three_way_branch_with_terminal_lockdown
    """
    _world, qa_pass, b1, b2, b3 = _pass_with_three_defects(api)
    fx.triage_bug(api, b1["id"], "ACCEPT", headers=users.LQA_OPENER)
    fx.triage_bug(api, b2["id"], "REJECT", headers=users.LQA_OPENER)
    fx.triage_bug(api, b3["id"], "DUPLICATE", b1["id"], headers=users.LQA_OPENER)

    claimed = validate_success(
        api.submit_fix_lqa_bug(b1["id"], users.VENDOR, f.submit_fix_payload())
    )
    assert claimed["status"] == "FIX_SUBMITTED"
    A.assert_defect_density(fx.read_qa_pass(api, qa_pass["id"])["defect_density"],
                            0.0400)

    verified = validate_success(api.verify_lqa_bug(b1["id"], users.LQA_VERIFIER))

    assert verified["status"] == "VERIFIED"
    assert verified["verified_by_user_id"] == users.LQA_VERIFIER["X-User-ID"]
    closed_out = fx.read_qa_pass(api, qa_pass["id"])
    assert closed_out["weighted_defect_points"] == 0
    A.assert_defect_density(closed_out["defect_density"], 0.0000)


def test_a_terminal_defect_refuses_a_second_triage(api):
    """`REJECTED` accepts nothing further.

    "Both `REJECTED` and `DUPLICATE` are terminal: a defect in either accepts
    nothing further."

    "In all three branches the defect must be in `NEW` (else
    `ERR_BUG_STATE_INVALID`) and the owning pass must be `OPEN` (else
    `ERR_QA_PASS_NOT_OPEN`), and in all three the defect's `version` increments
    by 1."

    Design: Difficulty/non_linear_state_machine/lqa_bug_triage_fork_three_way_branch_with_terminal_lockdown
    """
    _world, _qa_pass, _b1, b2, _b3 = _pass_with_three_defects(api)
    fx.triage_bug(api, b2["id"], "REJECT", headers=users.LQA_OPENER)
    rejected = fx.read_bug(api, b2["id"])

    response = api.triage_lqa_bug(b2["id"], f.triage_payload("ACCEPT"),
                                  users.LQA_OPENER)

    validate_error(response, E.ERR_BUG_STATE_INVALID)
    after = fx.read_bug(api, b2["id"])
    assert after["status"] == "REJECTED"
    A.assert_unchanged_row(after, rejected, "lqa_bug")
