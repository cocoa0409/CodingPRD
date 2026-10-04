"""Cascading invalidation: retraction, settings edits, suspension (PRD §2.9, §3.1, §3.5)."""
from test_helpers import (
    TEST_USERS,
    create_active_integration,
    create_assignment,
    create_instructor,
    create_institution,
    create_source,
    finalize_report,
    create_grade,
    get_assignment_version,
    get_report,
    inject_fragment,
    make_instructor_headers,
    process,
    reset_clock,
    setup_basic_scenario,
    setup_finalized_report,
    setup_processed_submission,
    submit,
    validate_paginated,
    validate_success,
    words,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INST_ADMIN = TEST_USERS["institutional_admin_headers"]


def test_source_retract_depth3_cascade(api):
    """PRD §2.9: "Retracting a `SourceDocument` marks every `MatchFragment`
    referencing it as excluded, and every similarity report whose submission
    holds one of those fragments goes `STALE` — which in turn flips any
    `RELEASED` grade entries on those submissions back to `PROVISIONAL`."

    Design: Difficulty/transitive_cascade/source_retract_depth3_cascade
    """
    inst, integ, instr, student, asg = setup_basic_scenario("US")
    sub = submit(asg["id"], student["id"], words(100))
    src = create_source(inst["id"], uri="https://src.example/c7")
    inject_fragment(sub["id"], src["id"], 10, "DIRECT_QUOTE", 0)

    process(sub["id"], instr["id"])
    grade = create_grade(sub["id"], instr["id"], score_points=88.5, feedback_text="good")
    report = get_report(sub["id"], instr["id"])
    finalize_report(report["id"], instr["id"], "NOT_MISCONDUCT")

    resp = api.retract_source(src["id"], INST_ADMIN)
    validate_success(resp)

    # hop 1: fragment excluded
    frags, _ = validate_paginated(api.list_match_fragments_of_submission(sub["id"], INST_ADMIN))
    assert frags[0]["excluded"] is True
    # hop 2: FINALIZED report goes STALE
    report_after = get_report(sub["id"], instr["id"])
    assert report_after["report_state"] == "STALE"
    # hop 3: RELEASED grade flips back to PROVISIONAL
    grades, _ = validate_paginated(api.list_grade_entries(sub["id"], INST_ADMIN))
    assert grades[0]["grade_state"] == "PROVISIONAL"
    # version-pinning keeps the stale pin visible
    assert grades[0]["pinned_report_version"] == grade["pinned_report_version"]


def test_source_retract_stales_draft_report_too(api):
    """PRD §2.9: "Retracting a `SourceDocument` marks every `MatchFragment`
    referencing it as excluded, and every similarity report whose submission
    holds one of those fragments goes `STALE`"

    Design: Difficulty/transitive_cascade/source_retract_depth3_cascade
    """
    inst, integ, instr, student, asg = setup_basic_scenario("US")
    sub = submit(asg["id"], student["id"], words(100))
    src = create_source(inst["id"], uri="https://src.example/c7b")
    inject_fragment(sub["id"], src["id"], 10, "DIRECT_QUOTE", 0)
    process(sub["id"], instr["id"])
    assert get_report(sub["id"], instr["id"])["report_state"] == "DRAFT"

    validate_success(api.retract_source(src["id"], INST_ADMIN))
    report_after = get_report(sub["id"], instr["id"])
    assert report_after["report_state"] == "STALE", "DRAFT reports stale on retraction as well"


def test_assignment_patch_depth2_cascade(api):
    """PRD §3.3: "changing any of the three exclusion switches or the threshold
    invalidates existing scoring, so every similarity report of the assignment's
    submissions that is currently `DRAFT` or `FINALIZED` flips to `STALE`
    (incrementing each report's `version`), and — as the compensation cascade —
    every grade entry on those submissions that had been `RELEASED` flips back
    to `PROVISIONAL` with its own `version` bump. The assignment's own `version`
    increments once for the edit itself."

    Design: Difficulty/transitive_cascade/assignment_patch_depth2_cascade
    """
    inst, integ, instr, student, asg, sub, report, grade = setup_finalized_report(
        "US", "quote heavy text", assignment_overrides={"exclude_quotes": False}
    )
    grades_before, _ = validate_paginated(api.list_grade_entries(sub["id"], INST_ADMIN))
    assert grades_before[0]["grade_state"] == "RELEASED"

    asg_v = get_assignment_version(asg["id"], instr["id"])
    patched = validate_success(
        api.patch_assignment(
            asg["id"],
            {"expected_assignment_version": asg_v, "exclude_quotes": True},
            make_instructor_headers(instr["id"]),
        )
    )
    assert patched["version"] == asg_v + 1, "the PATCH itself bumps the assignment version by 1"

    # hop 1: FINALIZED report -> STALE
    report_after = get_report(sub["id"], instr["id"])
    assert report_after["report_state"] == "STALE"
    # hop 2: RELEASED grade -> PROVISIONAL
    grades_after, _ = validate_paginated(api.list_grade_entries(sub["id"], INST_ADMIN))
    assert grades_after[0]["grade_state"] == "PROVISIONAL"


def test_assignment_patch_stales_draft_report(api):
    """PRD §3.3: "changing any of the three exclusion switches or the threshold
    invalidates existing scoring, so every similarity report of the assignment's
    submissions that is currently `DRAFT` or `FINALIZED` flips to `STALE`"

    Design: Difficulty/transitive_cascade/assignment_patch_depth2_cascade
    """
    inst, integ, instr, student, asg, sub = setup_processed_submission("US", "draft staleness body")
    assert get_report(sub["id"], instr["id"])["report_state"] == "DRAFT"
    asg_v = get_assignment_version(asg["id"], instr["id"])
    validate_success(
        api.patch_assignment(
            asg["id"],
            {"expected_assignment_version": asg_v, "exclude_bibliography": True},
            make_instructor_headers(instr["id"]),
        )
    )
    assert get_report(sub["id"], instr["id"])["report_state"] == "STALE"


def test_suspend_integration_conditional_cascade_only_open_assignments(api):
    """PRD §3.1: "moving an integration from `ACTIVE` to `SUSPENDED`
    conditionally cascades downward, flipping every assignment of that
    integration whose `accepting_state` is `OPEN` to `CLOSED`; assignments
    already `CLOSED` are untouched."

    Design: Corner/state_machines/suspend_integration_conditional_cascade_only_open_assignments
    """
    reset_clock("2026-09-01T00:00:00Z")
    inst = create_institution(name="Cond U", residency_region="US")
    integ = create_active_integration(inst["id"], external_key="c6")
    instr = create_instructor(inst["id"])
    a_open = create_assignment(integ["id"], instr["id"], title="A_open", due_at="2027-06-01T00:00:00Z")
    a_closed = create_assignment(integ["id"], instr["id"], title="A_closed", due_at="2026-09-02T00:00:00Z")

    reset_clock("2026-09-05T00:00:00Z")
    closed_read = validate_success(api.get_assignment(a_closed["id"], make_instructor_headers(instr["id"])))
    assert closed_read["accepting_state"] == "CLOSED", "lazy auto-close fired on the read"
    closed_v = closed_read["version"]

    validate_success(api.suspend_integration(integ["id"], ADMIN))

    open_read = validate_success(api.get_assignment(a_open["id"], make_instructor_headers(instr["id"])))
    assert open_read["accepting_state"] == "CLOSED", "cascade hit the OPEN assignment"
    closed_read2 = validate_success(api.get_assignment(a_closed["id"], make_instructor_headers(instr["id"])))
    assert closed_read2["version"] == closed_v, "already-CLOSED assignments are untouched by the cascade"


def test_assignment_parallel_dimensions_evolve_independently(api):
    """PRD §3.3: "An assignment carries two parallel, independent state
    dimensions." PRD §3.3: "The second dimension, `report_visibility`, starts
    `HIDDEN` and may be moved to `RELEASED` by the owning instructor via an
    OCC-guarded settings update; it evolves independently of whether the
    assignment still accepts submissions."

    Design: Corner/state_machines/assignment_parallel_dimensions_evolve_independently
    """
    inst, integ, instr, student, asg = setup_basic_scenario("US", consent=False)
    patched = validate_success(
        api.patch_assignment(
            asg["id"],
            {"expected_assignment_version": asg["version"], "report_visibility": "RELEASED"},
            make_instructor_headers(instr["id"]),
        )
    )
    assert patched["report_visibility"] == "RELEASED"
    assert patched["accepting_state"] == "OPEN", "releasing visibility does not affect the gate"

    reset_clock("2027-03-01T00:00:00Z")  # past due_at 2027-01-01
    fetched = validate_success(api.get_assignment(asg["id"], make_instructor_headers(instr["id"])))
    assert fetched["accepting_state"] == "CLOSED", "lazy auto-close fires past due_at"
    assert fetched["report_visibility"] == "RELEASED", "auto-close does not reset visibility"
