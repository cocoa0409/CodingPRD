"""Corner coverage: validations on follow-up cases, burden, and timing.

Contact spacing and evidence rules, escalation aging, the burden budget
floor, the exit gate on live cases, pre-announcement lead, collection
windows, and disclosure review on an uncertified cycle.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_report,
    api_client,
    assert_same_instant,
    close_collection,
    create_cycle,
    create_program,
    create_release,
    find_case,
    get_enrollment,
    get_release,
    lifecycle,
    make_disclosure_officer_headers,
    open_collection,
    record_contact,
    release_advance_payload,
    set_clock,
    setup_enrolled_panel,
    setup_program_with_frozen_frame,
    submit_report,
    validate_error,
    validate_success,
    void_contact,
)

COLLECTOR = TEST_USERS["collection_officer_headers"]
RELEASE_MANAGER = TEST_USERS["release_manager_headers"]
DISCLOSURE_OFFICER_USER_ID = "officer-7"


def _case_for_silent_enrollment(budget=500):
    """One accepted enrollment stays silent through the September cycle, so
    closing collection opens its follow-up case. Returns (enrollment, case).
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(code="CES", sample_budget=3,
                                    annual_burden_budget_minutes=budget)
    panel = setup_enrolled_panel("CES", count=1)
    en1 = panel["enrollments"][0]
    cycle = create_cycle("CES", "2026-09")
    open_collection(cycle)
    close_collection(cycle)  # clock now 2026-09-21T00:00:00Z
    return en1, find_case(en1["id"], cycle["id"])


def test_escalate_before_seven_days_rejected(api):
    """PRD §3.4: "Escalating moves `IN_CONTACT` to `ESCALATED` and demands both a contact history and patience: at least 2 non-voided contacts must exist, and the logical clock must have reached 7 days after `opened_at`, otherwise the escalation is rejected with `ERR_ESCALATION_TOO_EARLY`"

    Design: Corner/validations/escalate_before_seven_days_rejected
    """
    _en1, case = _case_for_silent_enrollment()
    record_contact(case["id"], 5, at="2026-09-22T09:00:00Z")
    record_contact(case["id"], 5, at="2026-09-23T10:00:00Z")

    set_clock("2026-09-23T11:00:00Z")  # ~26h after opened_at, far under 7 days
    resp = api_client.advance_follow_up_case(
        case["id"], {"action": "ESCALATE"}, COLLECTOR)
    validate_error(resp, ApiErrorId.ERR_ESCALATION_TOO_EARLY)  # 422


def test_close_unresponsive_before_escalation_rejected(api):
    """PRD §3.4: "Closing with `outcome` `UNRESPONSIVE` is reserved for the terminal stage of pursuit: only an `ESCALATED` case may move to `CLOSED_UNRESPONSIVE`, and attempting it from `OPEN` or `IN_CONTACT` is rejected with `ERR_INVALID_STATE`."

    Design: Corner/validations/close_unresponsive_before_escalation_rejected
    """
    _en1, case = _case_for_silent_enrollment()
    record_contact(case["id"], 5, at="2026-09-22T09:00:00Z")  # IN_CONTACT

    resp = api_client.advance_follow_up_case(
        case["id"], {"action": "CLOSE", "outcome": "UNRESPONSIVE"}, COLLECTOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)  # 409


def test_close_refused_without_contact_rejected(api):
    """PRD §3.4: "Closing with `outcome` `REFUSED` is available from `OPEN`, `IN_CONTACT`, or `ESCALATED` and moves the case to `CLOSED_REFUSED`, but only once at least 1 non-voided contact exists — closing as refused with no contact evidence is rejected with `ERR_NO_CONTACT_RECORDED`."

    Design: Corner/validations/close_refused_without_contact_rejected
    """
    _en1, case = _case_for_silent_enrollment()

    resp = api_client.advance_follow_up_case(
        case["id"], {"action": "CLOSE", "outcome": "REFUSED"}, COLLECTOR)
    validate_error(resp, ApiErrorId.ERR_NO_CONTACT_RECORDED)  # 422


def test_void_contact_twice_rejected(api):
    """PRD §3.4: "Naming a `contact_seq` that exists on the case marks that entry voided and subtracts its minutes back out of the enrollment's burden accumulator; an unknown `contact_seq` is rejected with `ERR_VALIDATION`, and voiding an entry that is already voided is rejected with `ERR_CONTACT_ALREADY_VOIDED`."

    Design: Corner/validations/void_contact_twice_rejected
    """
    en1, case = _case_for_silent_enrollment()
    record_contact(case["id"], 12, at="2026-09-22T09:00:00Z")
    void_contact(case["id"], 1)

    resp = api_client.advance_follow_up_case(
        case["id"], {"action": "VOID_CONTACT", "contact_seq": 1}, COLLECTOR)
    validate_error(resp, ApiErrorId.ERR_CONTACT_ALREADY_VOIDED)  # 409
    assert get_enrollment(en1["id"])["burden_minutes_ytd"] == 0, (
        "the single void refunded 12; no double subtraction")


def test_burden_budget_exceeded_blocks_contact_rejected(api):
    """PRD §3.4: "the enrollment's `burden_minutes_ytd` plus the new `contact_minutes` must not exceed the program's `annual_burden_budget_minutes`, evaluated after the calendar-year rollover described below, otherwise the recording is rejected with `ERR_BURDEN_BUDGET_EXCEEDED`."

    Design: Corner/validations/burden_budget_exceeded_blocks_contact_rejected
    """
    en1, case = _case_for_silent_enrollment(budget=30)
    record_contact(case["id"], 20, at="2026-09-22T09:00:00Z")

    # 25 hours later: spacing passes, but 20 + 25 = 45 > budget 30.
    set_clock("2026-09-23T10:00:00Z")
    resp = api_client.advance_follow_up_case(
        case["id"],
        {"action": "RECORD_CONTACT", "contact_minutes": 25,
         "channel": "PHONE"},
        COLLECTOR)
    validate_error(resp, ApiErrorId.ERR_BURDEN_BUDGET_EXCEEDED)  # 422
    assert get_enrollment(en1["id"])["burden_minutes_ytd"] == 20, (
        "rejected contact added nothing")


def test_exit_with_open_case_rejected(api):
    """PRD §3.2: "Exit is blocked while any follow-up case for the enrollment is still live — `OPEN`, `IN_CONTACT`, or `ESCALATED` — and the attempt is rejected with `ERR_CASE_STILL_OPEN`; cases in any `CLOSED` state do not block."

    Design: Corner/validations/exit_with_open_case_rejected
    """
    en1, _case = _case_for_silent_enrollment()

    resp = api_client.enrollment_lifecycle(
        en1["id"], {"action": "EXIT"}, COLLECTOR)
    validate_error(resp, ApiErrorId.ERR_CASE_STILL_OPEN)  # 409
    assert get_enrollment(en1["id"])["enrollment_status"] == "ENROLLED"


def test_preannounce_lead_boundary(api):
    """PRD §2.9: "A release is pre-announced: its publication instant `release_at` must fall at least 3 days after the current logical-clock reading, both when the release is first scheduled and when it is later rescheduled."
    PRD §2.9: "Each release carries an embargo window that opens at `embargo_open_at` — exactly the program's `embargo_window_minutes` before `release_at` — and closes at `release_at`."

    Design: Corner/validations/preannounce_lead_boundary
    """
    set_clock("2026-09-21T13:30:00Z")
    create_program(code="CES", sample_budget=3)
    c1 = create_cycle("CES", "2026-10")
    c2 = create_cycle("CES", "2026-11")

    # One second under the 3-day lead.
    resp = api_client.create_release(
        {"cycle_id": c1["id"], "release_at": "2026-09-24T13:29:59Z"},
        RELEASE_MANAGER)
    validate_error(resp, ApiErrorId.ERR_PREANNOUNCE_LEAD_TOO_SHORT)  # 422

    # Exactly clock + 3 days: the inclusive boundary is accepted.
    rel = validate_success(api_client.create_release(
        {"cycle_id": c2["id"], "release_at": "2026-09-24T13:30:00Z"},
        RELEASE_MANAGER), 201)
    assert_same_instant(rel["embargo_open_at"], "2026-09-24T13:00:00Z"), (
        "30-minute default window")


def test_cycle_open_close_window_violations(api):
    """PRD §3.3: "`collection_open_at` is the first day of the reference month at 00:00:00 UTC, and `collection_close_at` is the 20th day of the reference month at 23:59:59 UTC."
    PRD §3.3: "the logical clock must have reached `collection_open_at`, otherwise the advance is rejected with `ERR_CYCLE_WINDOW_VIOLATION`."
    PRD §3.3: "it must have reached `collection_close_at`, otherwise the advance is rejected with `ERR_CYCLE_WINDOW_VIOLATION`."

    Design: Corner/validations/cycle_open_close_window_violations
    """
    set_clock("2026-09-15T00:00:00Z")
    create_program(code="CES", sample_budget=3)
    cycle = create_cycle("CES", "2026-10")
    assert_same_instant(cycle["collection_open_at"], "2026-10-01T00:00:00Z")
    assert_same_instant(cycle["collection_close_at"], "2026-10-20T23:59:59Z")

    resp = api_client.advance_cycle(
        cycle["id"], {"action": "OPEN_COLLECTION"}, COLLECTOR)
    validate_error(resp, ApiErrorId.ERR_CYCLE_WINDOW_VIOLATION)  # too early

    set_clock("2026-10-01T00:00:00Z")
    opened = validate_success(api_client.advance_cycle(
        cycle["id"], {"action": "OPEN_COLLECTION"}, COLLECTOR))
    assert opened["cycle_status"] == "COLLECTING"

    set_clock("2026-10-10T00:00:00Z")  # before the 20th 23:59:59Z close
    resp = api_client.advance_cycle(
        cycle["id"], {"action": "CLOSE_COLLECTION"}, COLLECTOR)
    validate_error(resp, ApiErrorId.ERR_CYCLE_WINDOW_VIOLATION)


def test_disclosure_review_on_uncertified_cycle_rejected(api):
    """PRD §3.9: "Three further preconditions bind both actions: the cycle must be `CERTIFIED` or `PUBLISHED`, otherwise the review is rejected with `ERR_CYCLE_NOT_CERTIFIED`"

    Design: Corner/validations/disclosure_review_on_uncertified_cycle_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    create_program(code="CES", sample_budget=3)
    cycle = create_cycle("CES", "2026-09")  # stays SCHEDULED
    release = create_release(cycle["id"], "2026-10-01T13:30:00Z")

    resp = api_client.advance_release(
        release["id"],
        release_advance_payload(
            "APPROVE_DISCLOSURE",
            expected_release_version=release["version"]),
        make_disclosure_officer_headers(DISCLOSURE_OFFICER_USER_ID))
    validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_CERTIFIED)  # 409

    assert get_release(release["id"])["disclosure_status"] == "PENDING"
