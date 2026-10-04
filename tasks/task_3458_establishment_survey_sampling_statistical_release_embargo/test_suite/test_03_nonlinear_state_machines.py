"""Depth tests: non-linear state machines.

The ResponseReport correction cycle (SUBMITTED -> RETURNED -> SUBMITTED ->
ACCEPTED), the SurveyCycle revision loop (PUBLISHED -> REVISION_OPEN ->
CERTIFIED -> back to PUBLISHED), and the ReleaseEvent's two parallel
dimensions evolving independently.
"""
from test_helpers import (
    ANALYST_2_USER_ID,
    TEST_USERS,
    advance_release,
    api_client,
    approve_disclosure,
    certify_cycle,
    compute_estimates,
    create_cycle,
    create_release,
    get_enrollment,
    get_release,
    get_single_cell,
    open_collection,
    publish_release,
    reopen_revision,
    resubmit_report,
    return_report,
    set_clock,
    setup_certified_cycle,
    setup_embargoed_release,
    setup_enrolled_panel,
    setup_program_with_frozen_frame,
    submit_report,
    validate_success,
)


def test_response_report_return_resubmit_cycle(api):
    """PRD §3.3: "The correction loop closes with resubmission: the owning `Respondent` moves `RETURNED` back to `SUBMITTED`, which requires the cycle still `COLLECTING` and the clock still at or before `collection_close_at`"
    PRD §3.3: "Resubmission increments `submit_count` by 1, refreshes `submitted_at` from the logical clock, clears `return_reason`, and adds another 15 burden minutes."
    PRD §3.3: "Every submission event — the initial create and each resubmission after a return — adds 15 minutes to the enrollment's burden ledger under the rollover rule of §3.4."

    Design: Difficulty/non_linear_state_machine/response_report_return_resubmit_cycle
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(code="CES", sample_budget=3,
                                    annual_burden_budget_minutes=500)
    panel = setup_enrolled_panel("CES", count=1)
    en1 = panel["enrollments"][0]
    cycle = create_cycle("CES", "2026-09")
    open_collection(cycle)

    report = submit_report(en1, cycle["id"], 10)
    assert report["report_status"] == "SUBMITTED", (
        "electronic submission is born SUBMITTED")

    returned = return_report(report["id"], return_reason="unit mismatch")
    assert returned["report_status"] == "RETURNED"

    resubmitted = resubmit_report(report["id"], en1)
    assert resubmitted["report_status"] == "SUBMITTED", "cycle traversed"
    assert resubmitted["submit_count"] == 2, (
        "resubmission after RETURN is a new submission event")
    assert resubmitted["return_reason"] is None, "return_reason cleared"

    accepted = api_client.advance_report(
        report["id"], {"action": "ACCEPT"},
        TEST_USERS["collection_officer_headers"])
    accepted = validate_success(accepted)
    assert accepted["report_status"] == "ACCEPTED", "terminal state reached"

    enrollment = get_enrollment(en1["id"])
    assert enrollment["burden_minutes_ytd"] == 30, (
        f"2 submissions x 15 minutes each, got "
        f"{enrollment['burden_minutes_ytd']}")


def test_cycle_revision_loop_publish_reopen_recertify(api):
    """PRD §3.5: "the reopen clears `estimates_computed_at`, and on the cycle's published release it sets `revision_notice_required` to true and drops an `APPROVED` `disclosure_status` back to `PENDING`, leaving `REJECTED` and `PENDING` untouched."
    PRD §3.5: "when a release for the cycle already has `pub_status` `PUBLISHED`, the re-certified cycle lands directly in `PUBLISHED` rather than `CERTIFIED`."

    Design: Difficulty/non_linear_state_machine/cycle_revision_loop_publish_reopen_recertify
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(code="CES", sample_budget=3,
                                    annual_burden_budget_minutes=500)
    panel = setup_enrolled_panel("CES", count=3)
    en1, en2, en3 = panel["enrollments"]
    cycle = setup_certified_cycle(
        "CES", "2026-09", panel["enrollments"],
        {en1["id"]: 9, en2["id"]: 11, en3["id"]: 8})
    staged = setup_embargoed_release(cycle["id"], "2026-10-01T13:30:00Z")
    release = publish_release(staged["release"]["id"])

    reopened = reopen_revision(cycle["id"])
    assert reopened["cycle_status"] == "REVISION_OPEN", (
        "PUBLISHED -> REVISION_OPEN loop entry")

    release = get_release(release["id"])
    assert release["disclosure_status"] == "PENDING", (
        "disclosure auto-reverted by the reopen cascade")
    assert release["revision_notice_required"] is True

    compute_estimates(cycle["id"])
    cell = get_single_cell(cycle["id"], "MANUFACTURING", "SMALL")
    assert cell["revision_no"] == 2
    assert cell["estimate_status"] == "REVISED", (
        "revision pass bumped the preliminary estimate")

    recertified = certify_cycle(cycle["id"], ANALYST_2_USER_ID)
    assert recertified["cycle_status"] == "PUBLISHED", (
        "CERTIFY from REVISION_OPEN lands on PUBLISHED when a published "
        "release exists, closing the loop")


def test_release_parallel_dimensions_independent_evolution(api):
    """PRD §3.9: "is born with `pub_status` `SCHEDULED` and `disclosure_status` `PENDING` — two parallel dimensions that evolve independently on the one entity"
    PRD §3.9: "Approval moves `disclosure_status` from `PENDING` to `APPROVED`"

    Design: Difficulty/non_linear_state_machine/release_parallel_dimensions_independent_evolution
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(code="CES", sample_budget=3,
                                    annual_burden_budget_minutes=500)
    panel = setup_enrolled_panel("CES", count=3)
    en1, en2, en3 = panel["enrollments"]
    cycle = setup_certified_cycle(
        "CES", "2026-09", panel["enrollments"],
        {en1["id"]: 9, en2["id"]: 11, en3["id"]: 8})

    release = create_release(cycle["id"], "2026-10-01T13:30:00Z")
    assert release["pub_status"] == "SCHEDULED"
    assert release["disclosure_status"] == "PENDING"

    approved = approve_disclosure(release["id"])
    assert approved["disclosure_status"] == "APPROVED"
    assert approved["pub_status"] == "SCHEDULED", (
        "disclosure review leaves the publication dimension untouched — "
        "dimensions evolve independently")
    assert approved["revision_notice_required"] is False, (
        "no estimate change has occurred")
