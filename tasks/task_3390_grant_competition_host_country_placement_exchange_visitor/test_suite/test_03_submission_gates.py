"""Application creation/submission gating rules (PRD §3.2)."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    add_country_program,
    application_transition_payload,
    close_cycle,
    create_application_payload,
    create_cycle,
    create_draft_application,
    get_application,
    make_applicant_headers,
    register_applicant,
    set_clock_to,
    setup_draft_application,
    setup_submitted_application,
    submit_application,
    validate_error,
    withdraw_application,
)

from test_helpers import LOGICAL_CLOCK_START


def _instant(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def test_application_submit_while_cycle_draft_returns_cycle_not_open(
    api,
):
    """PRD §3.2: "Creation already enforces the fundamentals: the addressed
    country program must belong to the addressed cycle (`ERR_VALIDATION`), the
    cycle must be OPEN (`ERR_CYCLE_NOT_OPEN`), and the proposed duration must
    sit within the program's duration bounds, inclusive of both ends
    (`ERR_DURATION_OUT_OF_RANGE`, 422)."

    Design: Corner/state_machines/application_submit_while_cycle_draft_returns_cycle_not_open
    """
    cycle = create_cycle()  # left in DRAFT — never opened
    program = add_country_program(cycle)
    applicant = register_applicant()

    payload = create_application_payload(
        applicant["id"], cycle["id"], program["id"],
    )
    resp = api.create_application(payload, make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_OPEN)


def test_withdrawn_application_cannot_be_submitted(api):
    """PRD §3.2: "An applicant may withdraw from DRAFT, CAMPUS_REVIEW,
    NATIONAL_SCREENING, HOST_REVIEW, or ALTERNATE at any time, landing in the
    terminal WITHDRAWN state with no further preconditions."
    PRD §2.7: "The target entity must be in a state from which the requested
    transition exists — otherwise `ERR_INVALID_STATE` (409)"

    Design: Corner/state_machines/withdrawn_application_cannot_be_submitted
    """
    bundle = setup_draft_application()
    applicant = bundle["applicant"]
    withdrawn = withdraw_application(bundle["application"], applicant)
    assert withdrawn["status"] == "WITHDRAWN"

    resp = api.transition_application(
        withdrawn["id"], application_transition_payload("SUBMIT"),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    stayed = get_application(withdrawn)
    assert stayed["status"] == "WITHDRAWN", (
        "WITHDRAWN is terminal; a rejected SUBMIT must not move it"
    )


def test_submit_after_deadline_returns_deadline_passed(api):
    """PRD §3.2: "Every other precondition is identical across the fork: the
    cycle must be OPEN (`ERR_CYCLE_NOT_OPEN`); the logical clock must be at or
    before the cycle's `application_deadline`, the deadline being inclusive
    (`ERR_DEADLINE_PASSED`); the proposed duration must be within the
    program's bounds (`ERR_DURATION_OUT_OF_RANGE`); the applicant must not
    already hold another application in the same cycle in any of
    CAMPUS_REVIEW, NATIONAL_SCREENING, HOST_REVIEW, SELECTED, ALTERNATE,
    PLACEMENT, GRANT_PENDING, or AWARDED (`ERR_DUPLICATE_APPLICATION`); and a
    follow-on submission re-verifies that the latest alumni profile's
    `follow_on_eligible` is ELIGIBLE (`ERR_FOLLOW_ON_INELIGIBLE`)."

    Design: Corner/endpoints/submit_after_deadline_returns_deadline_passed
    """
    bundle = setup_draft_application()  # cycle OPEN, deadline 2026-10-15
    set_clock_to("2026-10-16T00:00:00Z")  # strictly past the deadline

    resp = api.transition_application(
        bundle["application"]["id"], application_transition_payload("SUBMIT"),
        make_applicant_headers(bundle["applicant"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DEADLINE_PASSED)

    stayed = get_application(bundle["application"])
    assert stayed["status"] == "DRAFT", (
        "a deadline-rejected SUBMIT must leave the application DRAFT"
    )


def test_duplicate_application_on_second_submit(api):
    """PRD §3.2: "the applicant must not already hold another application in
    the same cycle in any of CAMPUS_REVIEW, NATIONAL_SCREENING, HOST_REVIEW,
    SELECTED, ALTERNATE, PLACEMENT, GRANT_PENDING, or AWARDED
    (`ERR_DUPLICATE_APPLICATION`)"

    Design: Corner/endpoints/duplicate_application_on_second_submit
    """
    bundle = setup_submitted_application()  # first application NATIONAL_SCREENING
    applicant = bundle["applicant"]
    app_b = create_draft_application(
        applicant, bundle["cycle"], bundle["program"],
        project_title="Second Draft", project_summary="Another project",
        proposed_duration_months=8,
    )

    resp = api.transition_application(
        app_b["id"], application_transition_payload("SUBMIT"),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_APPLICATION)

    assert get_application(app_b)["status"] == "DRAFT"
    assert get_application(bundle["application"])["status"] == "NATIONAL_SCREENING"


def test_submit_rejected_once_cycle_has_closed(api):
    """PRD §3.2: "Every other precondition is identical across the fork: the
    cycle must be OPEN (`ERR_CYCLE_NOT_OPEN`); the logical clock must be at or
    before the cycle's `application_deadline`, the deadline being inclusive
    (`ERR_DEADLINE_PASSED`); the proposed duration must be within the
    program's bounds (`ERR_DURATION_OUT_OF_RANGE`); the applicant must not
    already hold another application in the same cycle in any of
    CAMPUS_REVIEW, NATIONAL_SCREENING, HOST_REVIEW, SELECTED, ALTERNATE,
    PLACEMENT, GRANT_PENDING, or AWARDED (`ERR_DUPLICATE_APPLICATION`); and a
    follow-on submission re-verifies that the latest alumni profile's
    `follow_on_eligible` is ELIGIBLE (`ERR_FOLLOW_ON_INELIGIBLE`)."

    The cycle is CLOSED after the draft was created and the deadline
    (2026-10-15) has not passed at the 2026-09-01 logical clock, so only the
    cycle-state gate can fail.

    Design: Difficulty/cross_entity_state_dependency/submit_requires_cycle_open
    """
    bundle = setup_draft_application()  # DRAFT application under an OPEN cycle
    close_cycle(bundle["cycle"])

    resp = api.transition_application(
        bundle["application"]["id"], application_transition_payload("SUBMIT"),
        make_applicant_headers(bundle["applicant"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_OPEN)

    stayed = get_application(bundle["application"])
    assert stayed["status"] == "DRAFT"


def test_submit_succeeds_while_cycle_is_open(api):
    """PRD §3.2: "When an ENROLLED_STUDENT submits, the application moves
    DRAFT → CAMPUS_REVIEW; when an INDEPENDENT submits, it moves DRAFT →
    NATIONAL_SCREENING."
    PRD §3.2: "A successful submission stamps `submitted_at` with the logical
    clock."

    Control arm of the cycle-state gate: the identical SUBMIT is legal while
    the cycle is OPEN.

    Design: Difficulty/cross_entity_state_dependency/submit_requires_cycle_open
    """
    bundle = setup_draft_application()  # INDEPENDENT applicant, cycle OPEN
    submitted = submit_application(bundle["application"], bundle["applicant"])
    assert submitted["status"] == "NATIONAL_SCREENING", (
        f"INDEPENDENT submission must fork to NATIONAL_SCREENING, got {submitted['status']}"
    )
    assert _instant(submitted["submitted_at"]) == _instant(LOGICAL_CLOCK_START), (
        f"submitted_at must be stamped from the logical clock, "
        f"got {submitted['submitted_at']}"
    )
