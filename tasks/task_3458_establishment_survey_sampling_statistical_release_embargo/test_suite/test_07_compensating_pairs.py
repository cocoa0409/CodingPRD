"""Depth tests: compensating invariants.

RECORD_CONTACT / VOID_CONTACT are a compensating pair that conserves burden
minutes; SUSPEND / REINSTATE are a compensating pair that conserves the
program's ENROLLED panel count.
"""
from test_helpers import (
    TEST_USERS,
    accept_report,
    api_client,
    close_collection,
    count_enrollments,
    create_cycle,
    find_case,
    get_case,
    get_enrollment,
    lifecycle,
    open_collection,
    record_contact,
    set_clock,
    setup_enrolled_panel,
    setup_program_with_frozen_frame,
    submit_report,
    validate_paginated,
    void_contact,
)


def test_burden_record_void_pair_conserves_minutes(api):
    """PRD §3.4: "Naming a `contact_seq` that exists on the case marks that entry voided and subtracts its minutes back out of the enrollment's burden accumulator"
    PRD §3.4: "`total_contact_minutes` is by definition the sum of `contact_minutes` over the entries whose `voided` is false, so voiding an entry reduces the total exactly by that entry's minutes."
    PRD §3.4: "from `OPEN` it moves the case to `IN_CONTACT`"

    Design: Difficulty/compensating_invariant/burden_record_void_pair_conserves_minutes
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(code="CES", sample_budget=3,
                                    annual_burden_budget_minutes=120)
    panel = setup_enrolled_panel("CES", count=2)
    en1, en2 = panel["enrollments"]

    # E1 reports (accepted); E2 silent -> a case is opened for E2 at close.
    cycle = create_cycle("CES", "2026-09")
    open_collection(cycle)
    accept_report(submit_report(en1, cycle["id"], 9)["id"])
    close_collection(cycle)
    case = find_case(en2["id"], cycle["id"])

    assert get_enrollment(en2["id"])["burden_minutes_ytd"] == 0

    mid = record_contact(case["id"], 12, at="2026-09-22T09:00:00Z",
                         channel="PHONE")
    assert mid["case_status"] == "IN_CONTACT", (
        "first contact moved OPEN -> IN_CONTACT")
    assert mid["total_contact_minutes"] == 12
    assert get_enrollment(en2["id"])["burden_minutes_ytd"] == 12

    end = void_contact(case["id"], 1)
    assert end["total_contact_minutes"] == 0, (
        "voiding reduces the total exactly by the entry's minutes")
    burden_end = get_enrollment(en2["id"])["burden_minutes_ytd"]
    assert burden_end == 0, (
        f"compensating action restores the invariant, got {burden_end}")

    entry = end["contacts"][0]
    assert entry["voided"] is True and entry["contact_minutes"] == 12, (
        "entry preserved, excluded from totals")
    assert end["case_status"] == "IN_CONTACT", (
        "voiding does not revert the case status")


def test_suspend_reinstate_pair_conserves_enrolled_count(api):
    """PRD §3.2: "Suspension moves `ENROLLED` to `SUSPENDED` and may be initiated by the owning `Respondent` or by a `CollectionOfficer`; while an enrollment is `SUSPENDED` it leaves the response-rate denominator of every future estimate computation. Reinstatement returns `SUSPENDED` to `ENROLLED` and belongs to the `CollectionOfficer` alone"

    Design: Difficulty/compensating_invariant/suspend_reinstate_pair_conserves_enrolled_count
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(code="CES", sample_budget=3,
                                    annual_burden_budget_minutes=500)
    panel = setup_enrolled_panel("CES", count=2)
    en1, en2 = panel["enrollments"]

    assert count_enrollments("CES", "ENROLLED") == 2, (
        "before the pair the panel holds two ENROLLED enrollments")

    suspended = lifecycle(en1, "SUSPEND", as_officer=True)
    assert suspended["enrollment_status"] == "SUSPENDED"
    assert count_enrollments("CES", "ENROLLED") == 1
    rows, meta = validate_paginated(api_client.list_enrollments(
        TEST_USERS["collection_officer_headers"],
        params={"program_code": "CES", "enrollment_status": "ENROLLED"}))
    assert meta["total_count"] == 1 and rows[0]["id"] == en2["id"]

    reinstated = lifecycle(en1, "REINSTATE", as_officer=True)
    assert reinstated["enrollment_status"] == "ENROLLED"
    assert count_enrollments("CES", "ENROLLED") == 2, (
        "the forward/compensating pair conserves the panel count")
