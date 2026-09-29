"""Validation corners: uniqueness, windows, coverage, branch discipline and the
fixed refusal order of PRD §2.10."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, constants, factories, fixtures
from test_helpers.api_errors import *  # noqa: F401,F403
from test_helpers.test_users import (
    make_program_chair_headers,
    make_provost_proposer_headers,
    make_provost_ratifier_headers,
    make_review_coordinator_headers,
)


def _read_self_study(api, cycle_id):
    """The only read channel for a self-study is its cycle's list (§4)."""
    rows = assertions.validate_unpaginated_list(
        api.list_self_studies(cycle_id, make_review_coordinator_headers())
    )
    assert len(rows) == 1, f"a cycle holds at most one self-study, got {len(rows)}"
    return rows[0]


def test_duplicate_program_code_rejected(api):
    """§2.10 check 14: ``AcademicProgram.code`` is unique across all programs.

    §3.1 scopes the uniqueness to the code alone, not to the department, so a
    second HIST-BA in another department under another name and another award
    level is still refused, and the refusal leaves the first row untouched.

    Design: Corner/validations/duplicate_program_code_rejected
    """
    coordinator = make_review_coordinator_headers()
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)

    first = validate_success(
        api.create_program(
            factories.program_payload(
                code="HIST-BA",
                name="History BA",
                degree_level="UNDERGRADUATE",
                department_code="HIST",
            ),
            coordinator,
        ),
        201,
    )
    assertions.assert_program_registration_defaults(first)

    # A different department, name and degree_level; the code alone collides.
    duplicate = api.create_program(
        factories.program_payload(
            code="HIST-BA",
            name="History of Art BA",
            degree_level="GRADUATE",
            department_code="ARTH",
        ),
        coordinator,
    )
    validate_error(duplicate, ERR_DUPLICATE_PROGRAM_CODE, 409)

    rows, meta = validate_paginated(api.list_programs(coordinator))
    assert meta["total_count"] == 1, "the refused create must not persist a second row"
    assert rows[0]["id"] == first["id"]
    assert rows[0]["name"] == "History BA"
    assert rows[0]["department_code"] == "HIST"
    assert rows[0]["degree_level"] == "UNDERGRADUATE"

    survivor = fixtures.read_program(api, first["id"])
    # §2.4: version begins at 1; the refused create mutated nothing.
    assert survivor["version"] == 1, "the refused create must not bump the existing row"


def test_duplicate_term_snapshot_rejected(api):
    """§2.10 check 15: ``term_index`` is unique within one program's snapshot set.

    The scope is per program, so the identical term_index is accepted on a second
    program, and the refused re-post leaves the first program's rollups — §3.1's
    rolling cost figure and §3.2's composite and band — exactly as they were.

    Design: Corner/validations/duplicate_term_snapshot_rejected
    """
    coordinator = make_review_coordinator_headers()
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)

    program = fixtures.create_program(
        api, code="HIST-BA", name="History BA", department_code="HIST"
    )
    other = fixtures.create_program(
        api, code="PHIL-BA", name="Philosophy BA", department_code="PHIL"
    )
    first_snapshot = {
        "term_code": "2025FA",
        "term_index": 1,
        "enrollment_headcount": 30,
        "credit_hours": 300,
        "direct_cost_cents": 12000000,
        "completions_count": 4,
        "market_demand_index": 42,
    }
    fixtures.append_snapshots(api, program["id"], [first_snapshot])

    clash = api.create_metric_snapshot(
        program["id"],
        factories.metric_snapshot_payload(
            term_code="2025FB",
            term_index=1,
            enrollment_headcount=99,
            credit_hours=900,
            direct_cost_cents=1,
            completions_count=99,
            market_demand_index=99,
        ),
        coordinator,
    )
    validate_error(clash, ERR_DUPLICATE_TERM_SNAPSHOT, 409)

    # §3.1: 12000000 / 300 = 40000 cents, rolling and latest alike on one row.
    # §3.2: factors 50 / 33.33 / 42 / 75 weight to 49.2333, but the window
    # enrolled 30 heads (< 60) so the small-program override replaces it with
    # 39.99, which bands NONVIABLE because 39.99 is below 40.00.
    reread = fixtures.read_program(api, program["id"])
    assert reread["snapshot_count"] == 1, "none of the 99s were applied"
    assertions.assert_viability(reread, 40000, 40000, 39.99, "NONVIABLE")

    # The same term_index on a DIFFERENT program is legal.
    accepted = validate_success(
        api.create_metric_snapshot(
            other["id"], factories.metric_snapshot_payload(**first_snapshot), coordinator
        ),
        201,
    )
    assertions.assert_append_only_stamps(accepted, "ViabilityMetricSnapshot")
    other_reread = fixtures.read_program(api, other["id"])
    assert other_reread["snapshot_count"] == 1
    assertions.assert_viability(other_reread, 40000, 40000, 39.99, "NONVIABLE")


def test_second_self_study_on_one_cycle_rejected(api):
    """§2.10 check 16: a review cycle holds at most one self-study.

    §3.3 states the rule without reference to the document's state, so the
    second attempt is refused while the first is still `DRAFT` — it is not a
    state check in disguise — and the first document is left untouched.

    Design: Corner/validations/second_self_study_on_one_cycle_rejected
    """
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    program = fixtures.create_program(
        api, code="HIST-BA", name="History BA", department_code="HIST"
    )
    chair = make_program_chair_headers(program["id"])
    cycle = fixtures.open_cycle(
        api,
        program["id"],
        cycle_year=2026,
        self_study_due_at="2026-09-01T00:00:00Z",
        required_section_codes=["S1"],
    )
    first = fixtures.create_self_study(
        api, cycle["id"], program["id"], narrative="First draft", section_codes=["S1"]
    )
    assert first["state"] == "DRAFT"

    second = api.create_self_study(
        cycle["id"],
        factories.self_study_payload(narrative="Second draft", section_codes=["S1"]),
        chair,
    )
    validate_error(second, ERR_SELF_STUDY_ALREADY_EXISTS, 409)

    surviving = _read_self_study(api, cycle["id"])
    assert surviving["id"] == first["id"]
    assert surviving["narrative"] == "First draft"
    assert surviving["state"] == "DRAFT"
    assert surviving["version"] == 1, "the refused create mutated nothing"


def test_second_open_cycle_on_one_program_rejected(api):
    """§2.10 check 17: a program holds at most one cycle that is not `CLOSED`.

    §3.3 bounds the rule on the cycle's state rather than on its `cycle_year`, so
    asking for a different academic year is not a way around it, and the refusal
    does not re-run the `ACTIVE → UNDER_REVIEW` cascade.

    Design: Corner/validations/second_open_cycle_on_one_program_rejected
    """
    coordinator = make_review_coordinator_headers()
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    program = fixtures.create_program(
        api, code="HIST-BA", name="History BA", department_code="HIST"
    )
    first = fixtures.open_cycle(
        api,
        program["id"],
        cycle_year=2026,
        self_study_due_at="2026-09-01T00:00:00Z",
        required_section_codes=["S1"],
    )
    assert first["state"] == "SELF_STUDY_OPEN"

    second = api.create_review_cycle(
        program["id"],
        factories.review_cycle_payload(
            cycle_year=2027,
            self_study_due_at="2027-09-01T00:00:00Z",
            required_section_codes=["S1"],
        ),
        coordinator,
    )
    validate_error(second, ERR_OPEN_CYCLE_EXISTS, 409)

    rows, meta = validate_paginated(api.list_review_cycles(program["id"], coordinator))
    assert meta["total_count"] == 1
    assert rows[0]["cycle_year"] == 2026

    reread = fixtures.read_program(api, program["id"])
    assertions.assert_axes(reread, lifecycle_state="UNDER_REVIEW")
    # 1 on registration, +1 for the one accepted cycle; the refusal added nothing.
    assert reread["version"] == 2


def test_self_study_submit_passes_at_the_deadline_and_fails_one_second_later(api):
    """§2.10 check 19 with §2.5's inclusive boundary on `self_study_due_at`.

    §2.5 says a self-study may be submitted while the clock is at or before the
    due instant and that one instant later the submission is refused. The late
    attempt is exercised first because a successful submission would leave the
    document out of `DRAFT` and check 12 would then answer ahead of check 19.

    Design: Corner/validations/self_study_submit_passes_at_the_deadline_and_fails_one_second_later
    """
    due_at = "2026-09-01T00:00:00Z"
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    program = fixtures.create_program(
        api, code="HIST-BA", name="History BA", department_code="HIST"
    )
    chair = make_program_chair_headers(program["id"])
    cycle = fixtures.open_cycle(
        api,
        program["id"],
        cycle_year=2026,
        self_study_due_at=due_at,
        required_section_codes=["S1"],
    )
    study = fixtures.create_self_study(
        api, cycle["id"], program["id"], section_codes=["S1"]
    )

    # One second past the deadline: refused.
    fixtures.set_clock(api, "2026-09-01T00:00:01Z")
    late = api.transition_self_study(
        study["id"], factories.self_study_submit_payload(), chair
    )
    validate_error(late, ERR_SELF_STUDY_WINDOW_CLOSED, 409)

    after_refusal = _read_self_study(api, cycle["id"])
    assert after_refusal["state"] == "DRAFT"
    assert after_refusal["submitted_at"] is None
    assert after_refusal["revision_round"] == 0

    # Exactly at the deadline: equality is permitted.
    fixtures.set_clock(api, due_at)
    submitted = validate_success(
        api.transition_self_study(
            study["id"], factories.self_study_submit_payload(), chair
        )
    )
    assert submitted["state"] == "SUBMITTED"
    assertions.assert_instant_equals(
        submitted["submitted_at"], due_at, "self_study.submitted_at"
    )
    assert submitted["revision_round"] == 0

    # §3.3: only ACCEPT cascades onto the cycle, so submission leaves it open.
    assert fixtures.read_cycle(api, cycle["id"])["state"] == "SELF_STUDY_OPEN"


def test_self_study_submit_with_missing_sections_rejected_then_patched(api):
    """§2.10 check 20: coverage must be complete before a self-study is submitted.

    §3.3 requires `missing_section_codes` to be empty and `section_codes` to be
    non-empty, and it puts the shortfall on `missing_section_codes` in the
    cycle's declared order. Extra codes the cycle never asked for are harmless.

    Design: Corner/validations/self_study_submit_with_missing_sections_rejected_then_patched
    """
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    program = fixtures.create_program(
        api, code="HIST-BA", name="History BA", department_code="HIST"
    )
    chair = make_program_chair_headers(program["id"])
    cycle = fixtures.open_cycle(
        api,
        program["id"],
        cycle_year=2026,
        self_study_due_at="2026-09-01T00:00:00Z",
        required_section_codes=["S1", "S2", "S3"],
    )
    study = fixtures.create_self_study(
        api, cycle["id"], program["id"], section_codes=["S1", "S3", "S9"]
    )
    # S9 is not required, so it neither covers S2 nor causes a failure.
    assert study["missing_section_codes"] == ["S2"]

    refused = api.transition_self_study(
        study["id"], factories.self_study_submit_payload(), chair
    )
    validate_error(refused, ERR_SELF_STUDY_SECTIONS_INCOMPLETE, 422)
    assert _read_self_study(api, cycle["id"])["state"] == "DRAFT"

    patched = validate_success(
        api.patch_self_study(
            study["id"],
            factories.self_study_patch_payload(section_codes=["S1", "S2", "S3", "S9"]),
            chair,
        )
    )
    assert patched["section_codes"] == ["S1", "S2", "S3", "S9"]
    assert patched["missing_section_codes"] == []
    assert patched["state"] == "DRAFT", "a PATCH is an edit, not a transition"

    submitted = validate_success(
        api.transition_self_study(
            study["id"], factories.self_study_submit_payload(), chair
        )
    )
    assert submitted["state"] == "SUBMITTED"
    assertions.assert_instant_equals(
        submitted["submitted_at"],
        constants.CLOCK_STARTUP_DEFAULT,
        "self_study.submitted_at",
    )
    assert submitted["revision_round"] == 0, "no RETURN has happened"


def test_reviewer_with_a_conflict_cannot_be_scheduled_on_that_program(api):
    """§2.10 check 21: a reviewer declaring the program's code may not visit it.

    §3.4 matches `conflict_program_codes` against the reviewed program's `code`,
    so the refusal is a property of the pair rather than of the reviewer, and a
    second reviewer with no declared conflict schedules the same window fine.

    Design: Corner/validations/reviewer_with_a_conflict_cannot_be_scheduled_on_that_program
    """
    coordinator = make_review_coordinator_headers()
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    program = fixtures.create_program(
        api, code="HIST-BA", name="History BA", department_code="HIST"
    )
    cycle = fixtures.open_cycle(api, program["id"], required_section_codes=["S1"])
    study = fixtures.create_self_study(
        api, cycle["id"], program["id"], section_codes=["S1"]
    )
    fixtures.accept_self_study(api, study["id"], program["id"])
    assert fixtures.read_cycle(api, cycle["id"])["state"] == "SELF_STUDY_ACCEPTED"

    conflicted = fixtures.register_reviewer(
        api,
        full_name="Dr Ravi Bell",
        institution="Eastgate College",
        specialty_code="HIST",
        conflict_program_codes=["HIST-BA"],
    )
    clean = fixtures.register_reviewer(
        api,
        full_name="Dr Mira Cole",
        institution="Westgate College",
        specialty_code="HIST",
    )
    # §3.4: the buffer defaults to 48 hours when the payload omits it.
    assert clean["travel_buffer_hours"] == 48

    refused = api.create_reviewer_visit(
        factories.reviewer_visit_payload(
            cycle["id"],
            conflicted["id"],
            fixtures.VISIT_WINDOW_START,
            fixtures.VISIT_WINDOW_END,
        ),
        coordinator,
    )
    validate_error(refused, ERR_REVIEWER_CONFLICT_OF_INTEREST, 409)

    _rows, meta = validate_paginated(
        api.list_reviewer_visits(coordinator, params={"reviewer_id": conflicted["id"]})
    )
    assert meta["total_count"] == 0, "the refused visit must not persist"
    assert fixtures.read_cycle(api, cycle["id"])["state"] == "SELF_STUDY_ACCEPTED"

    visit = fixtures.schedule_visit(api, cycle["id"], clean["id"])
    assert visit["state"] == "SCHEDULED"
    assert visit["report_count"] == 0
    assert visit["completed_at"] is None

    clean_rows, clean_meta = validate_paginated(
        api.list_reviewer_visits(coordinator, params={"reviewer_id": clean["id"]})
    )
    assert clean_meta["total_count"] == 1
    assert clean_rows[0]["id"] == visit["id"]
    assert fixtures.read_cycle(api, cycle["id"])["state"] == "VISIT_SCHEDULED"


def test_a_second_team_member_satisfies_all_three_visit_guards(api):
    """§2.10 checks 21, 22 and 23 all pass for a second reviewer on one window.

    §3.4's conflict check is per reviewer, its overlap check is per reviewer, and
    only its capacity check counts the whole team — so with
    `host_capacity_per_day` at 2 a second conflict-free reviewer is scheduled into
    the identical window, and the cycle stays in `VISIT_SCHEDULED`.

    Design: Corner/validations/a_second_team_member_satisfies_all_three_visit_guards
    """
    coordinator = make_review_coordinator_headers()
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    program = fixtures.create_program(
        api,
        code="HIST-BA",
        name="History BA",
        department_code="HIST",
        host_capacity_per_day=2,
    )
    cycle = fixtures.open_cycle(api, program["id"], required_section_codes=["S1"])
    study = fixtures.create_self_study(
        api, cycle["id"], program["id"], section_codes=["S1"]
    )
    fixtures.accept_self_study(api, study["id"], program["id"])

    first_reviewer = fixtures.register_reviewer(
        api, full_name="Dr Mira Cole", institution="Westgate College", specialty_code="HIST"
    )
    second_reviewer = fixtures.register_reviewer(
        api, full_name="Dr Sam Ives", institution="Southgate College", specialty_code="HIST"
    )
    first_visit = fixtures.schedule_visit(api, cycle["id"], first_reviewer["id"])
    assert first_visit["state"] == "SCHEDULED"

    second_visit = validate_success(
        api.create_reviewer_visit(
            factories.reviewer_visit_payload(
                cycle["id"],
                second_reviewer["id"],
                fixtures.VISIT_WINDOW_START,
                fixtures.VISIT_WINDOW_END,
            ),
            coordinator,
        ),
        201,
    )
    assert second_visit["state"] == "SCHEDULED"
    assert second_visit["report_count"] == 0
    assertions.assert_iso_date(second_visit["span_start_date"], "span_start_date")
    assertions.assert_iso_date(second_visit["span_end_date"], "span_end_date")
    assert second_visit["span_start_date"] == "2026-08-20"
    assert second_visit["span_end_date"] == "2026-08-22"

    rows, meta = validate_paginated(
        api.list_reviewer_visits(coordinator, params={"cycle_id": cycle["id"]})
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {first_visit["id"], second_visit["id"]}

    # §3.4: the cycle waits in VISIT_SCHEDULED until the last visit completes.
    assert fixtures.read_cycle(api, cycle["id"])["state"] == "VISIT_SCHEDULED"


def test_disputed_finding_code_must_come_from_a_filed_report(api):
    """§2.10 check 26: a disputed code must be a subset of the newest report's codes.

    §3.5 makes the filed report the only source of disputable codes, so an
    invented code is refused and the refusal leaves the cycle in `REPORT_RECEIVED`
    with `addendum_round` still 0 and no response stored at all.

    Design: Corner/validations/disputed_finding_code_must_come_from_a_filed_report
    """
    response_clock = "2026-08-23T00:00:00Z"
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    program = fixtures.create_program(
        api, code="HIST-BA", name="History BA", department_code="HIST"
    )
    chair = make_program_chair_headers(program["id"])
    cycle = fixtures.open_cycle(api, program["id"], required_section_codes=["S1"])
    study = fixtures.create_self_study(
        api, cycle["id"], program["id"], section_codes=["S1"]
    )
    fixtures.accept_self_study(api, study["id"], program["id"])
    reviewer = fixtures.register_reviewer(
        api, full_name="Dr Mira Cole", institution="Westgate College", specialty_code="HIST"
    )
    visit = fixtures.schedule_visit(api, cycle["id"], reviewer["id"])
    fixtures.set_clock(api, response_clock)
    fixtures.complete_visit(api, visit["id"])
    report = fixtures.file_report(
        api,
        visit["id"],
        reviewer["id"],
        recommendation="DISCONTINUE",
        finding_codes=["F-ENROLL", "F-COST"],
    )
    assert report["sequence_number"] == 1
    assert fixtures.read_cycle(api, cycle["id"])["state"] == "REPORT_RECEIVED"

    invented = api.file_program_response(
        cycle["id"],
        factories.program_response_payload(
            response_concurrence="DISPUTE",
            response_text="The program disputes a finding nobody filed.",
            disputed_finding_codes=["F-QUALITY"],
        ),
        chair,
    )
    validate_error(invented, ERR_UNKNOWN_FINDING_CODE, 422)

    untouched = fixtures.read_cycle(api, cycle["id"])
    assert untouched["state"] == "REPORT_RECEIVED"
    assert untouched["addendum_round"] == 0
    assert untouched["response_concurrence"] is None
    assert untouched["response_text"] is None
    assert untouched["disputed_finding_codes"] == []
    assert untouched["response_submitted_at"] is None

    accepted = validate_success(
        api.file_program_response(
            cycle["id"],
            factories.program_response_payload(
                response_concurrence="DISPUTE",
                response_text="The program disputes the cost finding.",
                disputed_finding_codes=["F-COST"],
            ),
            chair,
        )
    )
    assert accepted["state"] == "ADDENDUM_REQUESTED"
    assert accepted["addendum_round"] == 1
    assert accepted["response_concurrence"] == "DISPUTE"
    assert accepted["disputed_finding_codes"] == ["F-COST"]
    assertions.assert_instant_equals(
        accepted["response_submitted_at"], response_clock, "cycle.response_submitted_at"
    )


def test_receiving_program_required_only_for_consolidation(api):
    """§2.10 check 28: `receiving_program_id` is symmetric branch discipline.

    §3.6 refuses both halves with the same error id — supplying the link on a
    `DISCONTINUATION` and omitting it on a `CONSOLIDATION`. Both faults sit below
    check 27, so the NONVIABLE band supports either wind-down outcome and it is
    genuinely check 28 answering.

    Design: Corner/validations/receiving_program_required_only_for_consolidation
    """
    proposer = make_provost_proposer_headers()
    receiver = fixtures.create_continue_eligible_program(
        api, code="BIOL-BA", name="Biology BA", department_code="BIOL"
    )
    ctx = fixtures.carry_cycle_to_response_submitted(
        api, code="HIST-BA", name="History BA", department_code="HIST"
    )
    cycle_version = fixtures.read_cycle(api, ctx.cycle_id)["version"]

    # Supplied on a non-consolidation outcome.
    supplied = api.create_decision_record(
        ctx.cycle_id,
        factories.decision_payload(
            outcome="DISCONTINUATION",
            expected_cycle_version=cycle_version,
            receiving_program_id=receiver["id"],
        ),
        proposer,
    )
    validate_error(supplied, ERR_RECEIVING_PROGRAM_REQUIRED, 422)

    # Omitted on a consolidation outcome.
    omitted = api.create_decision_record(
        ctx.cycle_id,
        factories.decision_payload(
            outcome="CONSOLIDATION", expected_cycle_version=cycle_version
        ),
        proposer,
    )
    validate_error(omitted, ERR_RECEIVING_PROGRAM_REQUIRED, 422)

    still_open = fixtures.read_cycle(api, ctx.cycle_id)
    assert still_open["state"] == "RESPONSE_SUBMITTED"
    assert still_open["version"] == cycle_version, "a refusal is not a mutation"
    _rows, meta = validate_paginated(
        api.list_decision_records(
            make_review_coordinator_headers(), params={"cycle_id": ctx.cycle_id}
        )
    )
    assert meta["total_count"] == 0

    # The same token still holds, because neither refusal bumped the cycle.
    decision = validate_success(
        api.create_decision_record(
            ctx.cycle_id,
            factories.decision_payload(
                outcome="DISCONTINUATION", expected_cycle_version=cycle_version
            ),
            proposer,
        ),
        201,
    )
    assert decision["state"] == "PROPOSED"
    assert decision["receiving_program_id"] is None
    assert decision["viability_band_at_proposal"] == constants.FIXTURE_A_BAND
    assertions.assert_decimal_equals(
        decision["composite_score_at_proposal"],
        constants.FIXTURE_A_COMPOSITE_UNDERGRADUATE,
        "composite_score_at_proposal",
    )
    assert fixtures.read_cycle(api, ctx.cycle_id)["state"] == "DECISION_PROPOSED"
    # The receiving program was never touched by the refused proposals.
    reread_receiver = fixtures.read_program(api, receiver["id"])
    assertions.assert_axes(reread_receiver, lifecycle_state="ACTIVE")
    assert reread_receiver["consolidated_into_program_id"] is None


def test_receiving_program_must_be_a_different_eligible_program(api):
    """§2.10 check 29: three-part eligibility on the consolidation target.

    §3.6 requires the receiving program to differ from the reviewed program, to
    be `ACTIVE`, and to band `CONTINUE_ELIGIBLE`; all three failures answer with
    the one error id. The reviewed program names itself (it is neither different
    nor `ACTIVE`, being `UNDER_REVIEW`), then a program with no observations at
    all is named (`INSUFFICIENT_DATA`), and only the strong program is accepted.

    Design: Corner/validations/receiving_program_must_be_a_different_eligible_program
    """
    proposer = make_provost_proposer_headers()
    strong = fixtures.create_continue_eligible_program(
        api, code="BIOL-BA", name="Biology BA", department_code="BIOL"
    )
    # §3.2: every factor at its clamp weights to 100.00 on the undergraduate vector.
    assertions.assert_decimal_equals(
        strong["composite_score"], 100.00, "strong.composite_score"
    )
    assert strong["viability_band"] == "CONTINUE_ELIGIBLE"
    assertions.assert_axes(strong, lifecycle_state="ACTIVE")

    barren = fixtures.create_program(
        api, code="ARTH-BA", name="Art History BA", department_code="ARTH"
    )
    # §3.1: no observations means a null score and INSUFFICIENT_DATA.
    assert barren["composite_score"] is None
    assert barren["viability_band"] == "INSUFFICIENT_DATA"

    ctx = fixtures.carry_cycle_to_response_submitted(
        api, code="HIST-BA", name="History BA", department_code="HIST"
    )
    cycle_version = fixtures.read_cycle(api, ctx.cycle_id)["version"]

    itself = api.create_decision_record(
        ctx.cycle_id,
        factories.decision_payload(
            outcome="CONSOLIDATION",
            expected_cycle_version=cycle_version,
            receiving_program_id=ctx.program_id,
        ),
        proposer,
    )
    validate_error(itself, ERR_RECEIVING_PROGRAM_INELIGIBLE, 422)

    unscored = api.create_decision_record(
        ctx.cycle_id,
        factories.decision_payload(
            outcome="CONSOLIDATION",
            expected_cycle_version=cycle_version,
            receiving_program_id=barren["id"],
        ),
        proposer,
    )
    validate_error(unscored, ERR_RECEIVING_PROGRAM_INELIGIBLE, 422)

    unchanged = fixtures.read_cycle(api, ctx.cycle_id)
    assert unchanged["state"] == "RESPONSE_SUBMITTED"
    assert unchanged["version"] == cycle_version

    decision = validate_success(
        api.create_decision_record(
            ctx.cycle_id,
            factories.decision_payload(
                outcome="CONSOLIDATION",
                expected_cycle_version=cycle_version,
                receiving_program_id=strong["id"],
            ),
            proposer,
        ),
        201,
    )
    assert decision["state"] == "PROPOSED"
    assert decision["outcome"] == "CONSOLIDATION"
    assert decision["receiving_program_id"] == strong["id"]
    assert decision["viability_band_at_proposal"] == constants.FIXTURE_A_BAND
    assert fixtures.read_cycle(api, ctx.cycle_id)["state"] == "DECISION_PROPOSED"


def test_teach_out_horizon_must_cover_the_decision_effective_term(api):
    """§2.10 check 30: the plan's horizon must reach the decision's effective term.

    §3.9 requires `final_award_term_index` to be at or after the linked decision's
    `effective_term_index`, so 1/2/3 is internally well ordered yet still refused
    against an effective term of 4. The refusal consumes no version, so the same
    `expected_program_version` token still holds for the corrected filing.

    Design: Corner/validations/teach_out_horizon_must_cover_the_decision_effective_term
    """
    coordinator = make_review_coordinator_headers()
    ctx = fixtures.setup_ratified_discontinuation(
        api, code="HIST-BA", name="History BA", department_code="HIST"
    )
    assert ctx.decision["effective_term_index"] == 4
    program_version = fixtures.read_program(api, ctx.program_id)["version"]

    refused = api.create_teach_out_plan(
        ctx.program_id,
        factories.teach_out_plan_payload(
            decision_id=ctx.decision["id"],
            expected_program_version=program_version,
            last_admit_term_index=1,
            first_teach_out_term_index=2,
            final_award_term_index=3,
        ),
        ctx.chair_headers,
    )
    validate_error(refused, ERR_TEACH_OUT_HORIZON_INSUFFICIENT, 422)

    _rows, meta = validate_paginated(
        api.list_teach_out_plans(coordinator, params={"program_id": ctx.program_id})
    )
    assert meta["total_count"] == 0, "the refused filing must not persist a plan"
    assert fixtures.read_program(api, ctx.program_id)["version"] == program_version

    plan = validate_success(
        api.create_teach_out_plan(
            ctx.program_id,
            factories.teach_out_plan_payload(
                decision_id=ctx.decision["id"],
                expected_program_version=program_version,
                last_admit_term_index=3,
                first_teach_out_term_index=4,
                final_award_term_index=5,
            ),
            ctx.chair_headers,
        ),
        201,
    )
    assert plan["state"] == "DRAFT"
    assert plan["decision_id"] == ctx.decision["id"]
    assert plan["plan_revision_round"] == 0
    assert plan["approved_at"] is None
    assert plan["activated_at"] is None
    assert plan["completed_at"] is None
    assertions.assert_plan_ledger(
        plan,
        guaranteed_seat_total=0,
        committed_seat_total=0,
        required_seat_total=0,
        seat_shortfall=0,
        at_risk_student_count=0,
        open_student_count=0,
    )


def test_seat_shortfall_outranks_the_at_risk_student_check(api):
    """§2.10 check 34 answers before check 35 on a plan failing both gates.

    §3.9's approval requires `seat_shortfall` at 0 and `at_risk_student_count` at
    0, and check 35 explicitly ranks below check 34. The plan here is short one
    seat *and* carrying an at-risk student, so the first approval reports the seat
    shortfall; closing only the seat gap then exposes the at-risk student.

    Design: Corner/validations/seat_shortfall_outranks_the_at_risk_student_check
    """
    ratifier = make_provost_ratifier_headers()
    ctx = fixtures.setup_ratified_discontinuation(
        api, code="HIST-BA", name="History BA", department_code="HIST"
    )
    fixtures.file_plan(
        api,
        ctx,
        last_admit_term_index=3,
        first_teach_out_term_index=4,
        final_award_term_index=5,
    )
    fixtures.add_guarantee(api, ctx, course_code="HIST-401", term_index=4, seats_guaranteed=3)
    student = fixtures.enrol_student(api, ctx, credits_remaining=12, max_credits_per_term=15)
    advised = fixtures.record_advising(
        api, student["id"], advised_credits_per_term=3, plan_signed=False
    )
    # §3.10: 12 credits at the advised 3 per term is 4 terms, completing at
    # 4 + 4 - 1 = 7, which is past the final award term 5, so at_risk is true.
    # required_seat_count is 12 / 3 rounded up = 4 seats, one more than guaranteed.
    assert advised["advising_status"] == "ADVISED"
    assertions.assert_projection(
        advised,
        "CONSERVATIVE_ADVISED_LOAD",
        terms_remaining=4,
        completion_term_index=7,
        at_risk=True,
        required_seat_count=4,
    )
    fixtures.submit_plan(api, ctx)

    both_failing = fixtures.read_plan(api, ctx.plan["id"])
    assertions.assert_plan_ledger(
        both_failing,
        guaranteed_seat_total=3,
        required_seat_total=4,
        seat_shortfall=1,
        at_risk_student_count=1,
        open_student_count=1,
    )

    # Both gates are open; check 34 is the one that answers.
    shortfall = api.transition_teach_out_plan(
        ctx.plan["id"], factories.plan_transition_payload("APPROVE"), ratifier
    )
    validate_error(shortfall, ERR_COURSE_GUARANTEE_SHORTFALL, 409)

    fixtures.add_guarantee(api, ctx, course_code="HIST-402", term_index=4, seats_guaranteed=1)
    seats_closed = fixtures.read_plan(api, ctx.plan["id"])
    assertions.assert_plan_ledger(
        seats_closed,
        guaranteed_seat_total=4,
        required_seat_total=4,
        seat_shortfall=0,
        at_risk_student_count=1,
    )

    # Only now does check 35 become the first failing check.
    at_risk = api.transition_teach_out_plan(
        ctx.plan["id"], factories.plan_transition_payload("APPROVE"), ratifier
    )
    validate_error(at_risk, ERR_AT_RISK_STUDENTS_PRESENT, 409)

    unapproved = fixtures.read_plan(api, ctx.plan["id"])
    assert unapproved["state"] == "SUBMITTED"
    assert unapproved["approved_at"] is None


def test_addendum_requests_are_bounded_at_two_rounds(api):
    """§2.10 check 18: the dispute loop is bounded at `addendum_round` 2.

    §3.5 bounds `REPORT_RECEIVED → ADDENDUM_REQUESTED → REPORT_RECEIVED` to two
    rounds, clears the response fields on each addendum so the program must
    respond afresh, and numbers the addenda 2 and 3 off the visit's
    `report_count`. The third dispute is refused even though its finding code is
    perfectly valid, and a `PARTIAL_CONCUR` still closes the cycle out.

    Design: Corner/validations/addendum_requests_are_bounded_at_two_rounds
    """
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    program = fixtures.create_program(
        api, code="HIST-BA", name="History BA", department_code="HIST"
    )
    chair = make_program_chair_headers(program["id"])
    cycle = fixtures.open_cycle(api, program["id"], required_section_codes=["S1"])
    study = fixtures.create_self_study(
        api, cycle["id"], program["id"], section_codes=["S1"]
    )
    fixtures.accept_self_study(api, study["id"], program["id"])
    reviewer = fixtures.register_reviewer(
        api, full_name="Dr Mira Cole", institution="Westgate College", specialty_code="HIST"
    )
    visit = fixtures.schedule_visit(api, cycle["id"], reviewer["id"])
    fixtures.set_clock(api, fixtures.CLOCK_AFTER_VISIT)
    fixtures.complete_visit(api, visit["id"])
    initial = fixtures.file_report(
        api, visit["id"], reviewer["id"], finding_codes=["F-ENROLL", "F-COST"]
    )
    assert initial["sequence_number"] == 1

    # Round 1.
    first_dispute = fixtures.file_program_response(
        api,
        cycle["id"],
        program["id"],
        response_concurrence="DISPUTE",
        response_text="The program disputes the cost finding.",
        disputed_finding_codes=["F-COST"],
    )
    assert first_dispute["state"] == "ADDENDUM_REQUESTED"
    assert first_dispute["addendum_round"] == 1

    first_addendum = fixtures.file_report(
        api, visit["id"], reviewer["id"], finding_codes=["F-COST"]
    )
    assert first_addendum["sequence_number"] == 2
    after_first = fixtures.read_cycle(api, cycle["id"])
    assert after_first["state"] == "REPORT_RECEIVED"
    assert after_first["addendum_round"] == 1
    # §3.5: the addendum clears the earlier response so a fresh one is required.
    assert after_first["response_concurrence"] is None
    assert after_first["response_text"] is None
    assert after_first["disputed_finding_codes"] == []
    assert fixtures.read_cycle(api, cycle["id"])["state"] == "REPORT_RECEIVED"

    # Round 2.
    second_dispute = fixtures.file_program_response(
        api,
        cycle["id"],
        program["id"],
        response_concurrence="DISPUTE",
        response_text="The program disputes the cost finding again.",
        disputed_finding_codes=["F-COST"],
    )
    assert second_dispute["state"] == "ADDENDUM_REQUESTED"
    assert second_dispute["addendum_round"] == 2

    second_addendum = fixtures.file_report(
        api, visit["id"], reviewer["id"], finding_codes=["F-COST"]
    )
    assert second_addendum["sequence_number"] == 3
    assert fixtures.read_cycle(api, cycle["id"])["state"] == "REPORT_RECEIVED"

    # A third dispute: the code is a valid subset of the newest report, so it is
    # genuinely check 18 answering and not check 26.
    third = api.file_program_response(
        cycle["id"],
        factories.program_response_payload(
            response_concurrence="DISPUTE",
            response_text="The program disputes the cost finding a third time.",
            disputed_finding_codes=["F-COST"],
        ),
        chair,
    )
    validate_error(third, ERR_ADDENDUM_LIMIT_REACHED, 409)

    capped = fixtures.read_cycle(api, cycle["id"])
    assert capped["state"] == "REPORT_RECEIVED"
    assert capped["addendum_round"] == 2

    # The other branch is still open at the cap.
    closed_out = validate_success(
        api.file_program_response(
            cycle["id"],
            factories.program_response_payload(
                response_concurrence="PARTIAL_CONCUR",
                response_text="The program partly concurs and moves on.",
            ),
            chair,
        )
    )
    assert closed_out["state"] == "RESPONSE_SUBMITTED"
    assert closed_out["response_concurrence"] == "PARTIAL_CONCUR"
    assert closed_out["addendum_round"] == 2
    assert closed_out["disputed_finding_codes"] == []
    assertions.assert_instant_equals(
        closed_out["response_submitted_at"],
        fixtures.CLOCK_AFTER_VISIT,
        "cycle.response_submitted_at",
    )


def test_effectuate_reports_the_missing_plan_only_after_notices_clear(api):
    """§2.10 check 31 outranks check 32 on an effectuation failing both.

    §3.8 puts the notice gate above the teach-out gate, so a `DISCONTINUATION`
    with two unacknowledged notices and no plan at all reports the compliance
    failure twice over — once per outstanding notice — and only reveals the
    missing plan once `unacknowledged_notification_count` reaches 0.

    Design: Corner/validations/effectuate_reports_the_missing_plan_only_after_notices_clear
    """
    coordinator = make_review_coordinator_headers()
    ctx = fixtures.setup_ratified_discontinuation(
        api, code="HIST-BA", name="History BA", department_code="HIST"
    )
    decision_id = ctx.decision["id"]
    notices = fixtures.list_notifications(api, decision_id)
    # §3.6 hop 3 mints exactly two notices on the discontinuation branch.
    assert len(notices) == 2
    assert fixtures.read_decision(api, decision_id)["unacknowledged_notification_count"] == 2
    assert fixtures.read_cycle(api, ctx.cycle_id)["compliance_posture"] == "NOTICES_PENDING"

    both_pending = api.transition_decision_record(
        decision_id, factories.effectuate_payload(), coordinator
    )
    validate_error(both_pending, ERR_AGENCY_NOTICE_NOT_ACKNOWLEDGED, 409)

    # One notice cleared is not enough: the gate reads the count, not a flag.
    fixtures.acknowledge_notification(api, notices[0]["id"])
    assert fixtures.read_decision(api, decision_id)["unacknowledged_notification_count"] == 1
    assert fixtures.read_cycle(api, ctx.cycle_id)["compliance_posture"] == "NOTICES_PENDING"

    one_pending = api.transition_decision_record(
        decision_id, factories.effectuate_payload(), coordinator
    )
    validate_error(one_pending, ERR_AGENCY_NOTICE_NOT_ACKNOWLEDGED, 409)

    fixtures.acknowledge_notification(api, notices[1]["id"])
    cleared = fixtures.read_decision(api, decision_id)
    assert cleared["unacknowledged_notification_count"] == 0
    assert fixtures.read_cycle(api, ctx.cycle_id)["compliance_posture"] == "NOTICES_CLEARED"

    # Now the next gate down answers. §2.10 check 33 is satisfied: with no
    # appointments on the program, deferred_fte is 0.00.
    missing_plan = api.transition_decision_record(
        decision_id, factories.effectuate_payload(), coordinator
    )
    validate_error(missing_plan, ERR_TEACH_OUT_REQUIRED, 409)

    unmoved = fixtures.read_decision(api, decision_id)
    assert unmoved["state"] == "RATIFIED"
    assert unmoved["effectuated_at"] is None
    program = fixtures.read_program(api, ctx.program_id)
    assertions.assert_axes(
        program,
        lifecycle_state="TEACH_OUT_PENDING",
        catalog_status="MARKETING_SUPPRESSED",
    )
    _rows, meta = validate_paginated(
        api.list_teach_out_plans(coordinator, params={"program_id": ctx.program_id})
    )
    assert meta["total_count"] == 0


def test_terminal_program_and_closed_cycle_refuse_further_writes(api):
    """§2.10 check 11 outranks check 12, and both outrank every later check.

    §2.9 closes a `DISCONTINUED` program to writes on itself and on every
    descendant, and check 11 sits above the family state checks — so a guarantee
    added to that program's own `COMPLETED` plan reports
    `ERR_PROGRAM_ALREADY_TERMINAL` rather than the plan-state error. Before the
    program turns terminal, the same ladder shows check 12 answering on a `CLOSED`
    cycle, where no terminal bar applies yet.

    Design: Corner/validations/terminal_program_and_closed_cycle_refuse_further_writes
    """
    coordinator = make_review_coordinator_headers()
    ctx = fixtures.setup_ratified_discontinuation(
        api, code="HIST-BA", name="History BA", department_code="HIST"
    )
    fixtures.acknowledge_all_notifications(api, ctx.decision["id"])
    # An empty plan: no guarantees and no students, so both approval gates read 0.
    fixtures.file_plan(api, ctx)
    fixtures.submit_plan(api, ctx)
    approved = fixtures.approve_plan(api, ctx)
    assert approved["state"] == "APPROVED"
    effectuated = fixtures.effectuate_decision(api, ctx)
    assert effectuated["state"] == "EFFECTUATED"
    assert fixtures.read_cycle(api, ctx.cycle_id)["state"] == "CLOSED"
    assertions.assert_axes(
        fixtures.read_program(api, ctx.program_id),
        lifecycle_state="TEACH_OUT_ACTIVE",
        catalog_status="ADMISSIONS_CLOSED",
    )

    # Check 12 on a CLOSED cycle: the program is not terminal yet.
    late_response = api.file_program_response(
        ctx.cycle_id,
        factories.program_response_payload(
            response_concurrence="CONCUR",
            response_text="A response filed after the cycle closed.",
        ),
        ctx.chair_headers,
    )
    validate_error(late_response, ERR_CYCLE_STATE_INVALID, 409)

    # §3.9's empty-cohort case: activation auto-completes the plan in the same
    # request, which cascades the program to DISCONTINUED and CATALOG_WITHDRAWN.
    activated = validate_success(
        api.transition_teach_out_plan(
            ctx.plan["id"], factories.plan_transition_payload("ACTIVATE"), coordinator
        )
    )
    assert activated["state"] == "COMPLETED"
    terminal_plan = fixtures.read_plan(api, ctx.plan["id"])
    assert terminal_plan["state"] == "COMPLETED"
    assertions.assert_axes(
        fixtures.read_program(api, ctx.program_id),
        lifecycle_state="DISCONTINUED",
        catalog_status="CATALOG_WITHDRAWN",
    )

    # Check 11 on a write nested under the terminal program itself.
    snapshot = api.create_metric_snapshot(
        ctx.program_id,
        factories.metric_snapshot_payload(
            term_code="2027SP",
            term_index=4,
            enrollment_headcount=10,
            credit_hours=100,
            direct_cost_cents=1000000,
            completions_count=1,
            market_demand_index=10,
        ),
        coordinator,
    )
    validate_error(snapshot, ERR_PROGRAM_ALREADY_TERMINAL, 409)
    assert fixtures.read_program(api, ctx.program_id)["snapshot_count"] == len(
        constants.FIXTURE_A_SNAPSHOTS
    )

    # Check 11 again on a descendant whose own state would also refuse: the
    # terminal bar answers first, so it is not ERR_PLAN_STATE_INVALID.
    guarantee = api.create_course_guarantee(
        ctx.plan["id"],
        factories.course_guarantee_payload(
            course_code="HIST-499", term_index=5, seats_guaranteed=1
        ),
        ctx.chair_headers,
    )
    validate_error(guarantee, ERR_PROGRAM_ALREADY_TERMINAL, 409)
    assertions.assert_plan_ledger(
        fixtures.read_plan(api, ctx.plan["id"]),
        guaranteed_seat_total=0,
        open_student_count=0,
    )
