"""Reporting deadlines, the window that enforces them, and the headcount gate."""
from test_helpers import (
    TEST_USERS,
    api_client,
    approve_application,
    create_application,
    file_report,
    file_report_raw,
    get_application,
    set_clock,
    setup_release_context,
    setup_two_qualifier_applications,
    transition_payload,
    validate_error,
    validate_success,
)


def test_a_qualifier_deadline_is_the_street_date_plus_eighteen_days(api):
    """PRD §3.2: "Reporting obligations attach only to the two competitive rungs:
    a `LOCAL` event carries no deadline at all, while a `QUALIFIER` or
    `CHAMPIONSHIP` event acquires a deadline of the cited set release's street
    date plus eighteen days."
    PRD §3.7: "Every approved application on this release at `QUALIFIER` or
    `CHAMPIONSHIP` tier has its `reporting_due_by` set to the street date plus
    eighteen days."

    Design: Corner/calculations/reporting_deadline_is_street_date_plus_eighteen_days
    """
    store, set_release, fmt = setup_release_context()
    application = create_application(
        store, set_release, fmt, tier="QUALIFIER",
        scheduled_date="2026-09-26T18:00:00Z", expected_headcount=30,
    )

    approved = approve_application(application["id"], store["id"])
    assert approved["reporting_due_by"] == "2026-10-06T00:00:00Z"
    assert approved["prizing_report_status"] == "DUE"
    assert approved["prize_allocation_id"] is not None


def test_the_deadline_is_not_the_seven_day_completion_offset(api):
    """PRD §3.2: "Reporting obligations attach only to the two competitive rungs:
    a `LOCAL` event carries no deadline at all, while a `QUALIFIER` or
    `CHAMPIONSHIP` event acquires a deadline of the cited set release's street
    date plus eighteen days."
    PRD §3.4: "To be closed out, it is completed, which is available only from
    `APPROVED` and only once the logical clock has reached at least seven days
    past the set's street date."

    Design: Corner/calculations/reporting_deadline_is_street_date_plus_eighteen_days
    """
    store, set_release, fmt = setup_release_context()
    application = create_application(
        store, set_release, fmt, tier="QUALIFIER",
        scheduled_date="2026-09-26T18:00:00Z", expected_headcount=30,
    )
    approved = approve_application(application["id"], store["id"])

    assert approved["reporting_due_by"] != "2026-09-25T00:00:00Z", (
        "the seven-day completion offset is not the reporting deadline"
    )
    assert approved["reporting_due_by"] == "2026-10-06T00:00:00Z"


def test_a_local_event_carries_no_deadline_through_approval_and_completion(api):
    """PRD §3.2: "Reporting obligations attach only to the two competitive rungs:
    a `LOCAL` event carries no deadline at all, while a `QUALIFIER` or
    `CHAMPIONSHIP` event acquires a deadline of the cited set release's street
    date plus eighteen days."

    Design: Corner/calculations/local_tier_deadline_is_null_and_stays_null
    """
    store, set_release, fmt = setup_release_context()
    application = create_application(
        store, set_release, fmt, tier="LOCAL",
        scheduled_date="2026-09-26T18:00:00Z", expected_headcount=12,
    )
    approved = approve_application(application["id"], store["id"])
    assert approved["reporting_due_by"] is None

    set_clock("2026-09-26T00:00:00Z")
    transition = api_client.transition_event_application(
        application["id"], transition_payload("COMPLETE"),
        __import__("test_helpers").make_store_organizer_headers(store["id"]),
    )
    validate_success(transition, 200)
    completed = get_application(application["id"])
    assert completed["status"] == "COMPLETED"
    assert completed["reporting_due_by"] is None


def test_a_local_event_reports_no_scheduled_deadline_in_its_prizing_summary(api):
    """PRD §3.13: "a `reporting_due_status` drawn from exactly three values,
    `NOT_SCHEDULED` when no deadline applies, `OPEN` while the logical clock is at
    or before the deadline, and `PAST_DUE` once the clock has passed it"
    PRD §3.2: "Reporting obligations attach only to the two competitive rungs: a
    `LOCAL` event carries no deadline at all, while a `QUALIFIER` or
    `CHAMPIONSHIP` event acquires a deadline of the cited set release's street
    date plus eighteen days."

    Design: Corner/calculations/local_tier_deadline_is_null_and_stays_null
    """
    store, set_release, fmt = setup_release_context()
    application = create_application(
        store, set_release, fmt, tier="LOCAL",
        scheduled_date="2026-09-26T18:00:00Z", expected_headcount=12,
    )
    approve_application(application["id"], store["id"])
    set_clock("2026-09-26T00:00:00Z")
    api_client.transition_event_application(
        application["id"], transition_payload("COMPLETE"),
        __import__("test_helpers").make_store_organizer_headers(store["id"]),
    ).raise_for_status()

    summary = validate_success(
        api_client.get_prizing_summary(application["id"], TEST_USERS["judge_headers"]),
        200,
    )
    assert summary["reporting_due_status"] == "NOT_SCHEDULED"
    assert summary["reporting_due_by"] is None
    assert summary["qualified_headcount"] is False
    assert summary["headcount_gate_error"] is None


def test_filing_at_the_deadline_instant_is_legal_and_one_second_later_is_not(api):
    """PRD §3.6: "And the filing must happen while the logical clock is still at
    or before the application's `reporting_due_by`, whenever that deadline is
    non-null; a filing attempted after the deadline has passed is rejected with
    `ERR_REPORT_WINDOW_CLOSED`."

    Design: Corner/errors/report_window_closed_after_deadline
    """
    scenario = setup_two_qualifier_applications()
    store = scenario["store"]

    set_clock("2026-10-06T00:00:00Z")
    accepted = file_report(
        scenario["first"]["id"], scenario["first_allocation"]["id"], store["id"],
        unclaimed_tp=0, reported_headcount=30,
    )
    assert accepted["status"] == "FILED"
    assert get_application(scenario["first"]["id"])["status"] == "REPORTED"

    set_clock("2026-10-06T00:00:01Z")
    refused = file_report_raw(
        scenario["second"]["id"], store["id"],
        {
            "prize_allocation_id": scenario["second_allocation"]["id"],
            "unclaimed_tp": 0,
            "reported_headcount": 30,
        },
    )
    validate_error(refused, "ERR_REPORT_WINDOW_CLOSED", expected_status=422)


def test_the_late_application_stays_completed_and_due_after_the_refusal(api):
    """PRD §3.6: "And the filing must happen while the logical clock is still at
    or before the application's `reporting_due_by`, whenever that deadline is
    non-null; a filing attempted after the deadline has passed is rejected with
    `ERR_REPORT_WINDOW_CLOSED`."
    PRD §3.6: "an event that has not been opted into its reporting window cannot
    be reported"

    Design: Corner/errors/report_window_closed_after_deadline
    """
    scenario = setup_two_qualifier_applications()
    store = scenario["store"]

    set_clock("2026-10-06T00:00:01Z")
    refused = file_report_raw(
        scenario["second"]["id"], store["id"],
        {
            "prize_allocation_id": scenario["second_allocation"]["id"],
            "unclaimed_tp": 0,
            "reported_headcount": 30,
        },
    )
    validate_error(refused, "ERR_REPORT_WINDOW_CLOSED", expected_status=422)

    row = get_application(scenario["second"]["id"])
    assert row["status"] == "COMPLETED"
    assert row["prizing_report_status"] == "DUE"


def test_a_headcount_of_exactly_twenty_four_clears_the_prizing_gate(api):
    """PRD §3.13: "A headcount of exactly twenty-four qualifies — the comparison
    admits equality — and a headcount of zero is a perfectly well-formed report
    describing an event nobody attended, which simply fails the gate."

    Design: Difficulty/boundary_precision_check/headcount_threshold_inclusive_at_exactly_twenty_four
    """
    scenario = setup_two_qualifier_applications(
        first_headcount=24, second_headcount=23
    )
    store = scenario["store"]

    file_report(
        scenario["first"]["id"], scenario["first_allocation"]["id"], store["id"],
        unclaimed_tp=0, reported_headcount=24,
    )
    file_report(
        scenario["second"]["id"], scenario["second_allocation"]["id"], store["id"],
        unclaimed_tp=0, reported_headcount=23,
    )

    summary = validate_success(
        api_client.get_prizing_summary(scenario["first"]["id"], TEST_USERS["judge_headers"]),
        200,
    )
    assert summary["qualified_headcount"] is True
    assert summary["headcount_gate_error"] is None
    assert summary["report_status"] == "FILED"


def test_a_headcount_of_twenty_three_fails_the_same_gate(api):
    """PRD §3.13: "A headcount of exactly twenty-four qualifies — the comparison
    admits equality — and a headcount of zero is a perfectly well-formed report
    describing an event nobody attended, which simply fails the gate."
    PRD §3.13: "a `QUALIFIER` or `CHAMPIONSHIP` event that clears the threshold
    also produces a null gate error and one that misses it produces
    `ERR_HEADCOUNT_BELOW_THRESHOLD`."

    Design: Difficulty/boundary_precision_check/headcount_threshold_inclusive_at_exactly_twenty_four
    """
    scenario = setup_two_qualifier_applications(
        first_headcount=24, second_headcount=23
    )
    store = scenario["store"]

    file_report(
        scenario["first"]["id"], scenario["first_allocation"]["id"], store["id"],
        unclaimed_tp=0, reported_headcount=24,
    )
    file_report(
        scenario["second"]["id"], scenario["second_allocation"]["id"], store["id"],
        unclaimed_tp=0, reported_headcount=23,
    )

    summary = validate_success(
        api_client.get_prizing_summary(scenario["second"]["id"], TEST_USERS["judge_headers"]),
        200,
    )
    assert summary["qualified_headcount"] is False
    assert summary["headcount_gate_error"] == "ERR_HEADCOUNT_BELOW_THRESHOLD"
    assert summary["report_status"] == "FILED", (
        "the gate reads a filed report rather than an absent one"
    )