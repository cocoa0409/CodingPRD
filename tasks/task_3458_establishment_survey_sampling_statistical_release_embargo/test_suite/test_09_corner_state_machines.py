"""Corner coverage: state-machine claims.

Invalid transitions, terminal lockdown, precondition enforcement, temporal
gates on advance endpoints, and side-effect cascades (report-accept case
closure, postpone grant revocation, factor-set supersession).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_report,
    api_client,
    approve_disclosure,
    close_collection,
    create_cycle,
    create_factor_set,
    create_program,
    create_release,
    enroll,
    find_case,
    get_case,
    get_grant,
    get_release,
    lifecycle,
    make_respondent_headers,
    open_collection,
    open_embargo,
    record_contact,
    register_establishment,
    release_advance_payload,
    reschedule_release,
    return_report,
    set_clock,
    setup_certified_cycle,
    setup_embargoed_release,
    setup_enrolled_panel,
    setup_program_with_frozen_frame,
    submit_report,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
COLLECTOR = TEST_USERS["collection_officer_headers"]
RELEASE_MANAGER = TEST_USERS["release_manager_headers"]
METHODOLOGIST = TEST_USERS["survey_methodologist_headers"]


def test_freeze_non_draft_frame_rejected(api):
    """PRD §3.1: "Freezing is the act that turns a draft design into a sampling plan, moving `frame_status` from `DRAFT` to `FROZEN`; freezing anything but a `DRAFT` frame is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/freeze_non_draft_frame_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    _program, frame = setup_program_with_frozen_frame(code="CES",
                                                      sample_budget=3)
    assert frame["total_sample_size"] == 3, (
        "first freeze computed and stored the allocation")
    resp = api_client.freeze_sample_frame(frame["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)  # 409


def test_accept_returned_report_rejected(api):
    """PRD §2.8 (stage 6): "The state machine's from-state holds for the requested action — no double freeze, no acceptance of a `RETURNED` report, no bulletin read on a `REVOKED` or `BREACHED` grant, no advance on a terminal entity. Violations are rejected with `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.3: "The correction loop closes with resubmission: the owning `Respondent` moves `RETURNED` back to `SUBMITTED`"

    Design: Corner/state_machines/accept_returned_report_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(code="CES", sample_budget=3)
    panel = setup_enrolled_panel("CES", count=1)
    en1 = panel["enrollments"][0]
    cycle = create_cycle("CES", "2026-09")
    open_collection(cycle)
    report = submit_report(en1, cycle["id"], 9)
    return_report(report["id"], return_reason="verify units")

    resp = api_client.advance_report(report["id"], {"action": "ACCEPT"},
                                     COLLECTOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)  # 409
    assert api_client.get_report(report["id"], COLLECTOR)
    report = validate_success(api_client.get_report(report["id"], COLLECTOR))
    assert report["report_status"] == "RETURNED", (
        "only resubmission (SUBMIT) exits RETURNED")


def test_refused_enrollment_terminal_lockdown(api):
    """PRD §3.2: "An invited establishment answers for itself: the owning `Respondent` accepts, moving `INVITED` to `ENROLLED`, or declines, moving `INVITED` to `REFUSED`, which is terminal."
    PRD §3.2: "Every lifecycle action requires the matching from-state, enforced with `ERR_INVALID_STATE`"

    Design: Corner/state_machines/refused_enrollment_terminal_lockdown
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(code="CES", sample_budget=3)
    est = register_establishment()
    enrollment = enroll(est["id"], "CES")
    refused = lifecycle(enrollment, "DECLINE")
    assert refused["enrollment_status"] == "REFUSED"

    resp = api_client.enrollment_lifecycle(
        enrollment["id"], {"action": "ACCEPT"},
        make_respondent_headers(est["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)  # 409
    resp = api_client.enrollment_lifecycle(
        enrollment["id"], {"action": "EXIT"}, COLLECTOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)  # 409


def test_certify_without_compute_rejected(api):
    """PRD §3.5: "It demands that estimates have been computed since the last close or reopen — otherwise the advance is rejected with `ERR_ESTIMATES_NOT_COMPUTED`"

    Design: Corner/state_machines/certify_without_compute_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(code="CES", sample_budget=3)
    panel = setup_enrolled_panel("CES", count=1)
    en1 = panel["enrollments"][0]
    cycle = create_cycle("CES", "2026-09")
    open_collection(cycle)
    accept_report(submit_report(en1, cycle["id"], 9)["id"])
    close_collection(cycle)  # NO compute run

    resp = api_client.advance_cycle(cycle["id"], {"action": "CERTIFY"},
                                    TEST_USERS["estimation_analyst_headers"])
    validate_error(resp, ApiErrorId.ERR_ESTIMATES_NOT_COMPUTED)  # 409
    rows, _meta = validate_paginated(api_client.list_cycles(
        COLLECTOR, params={"program_code": "CES"}))
    assert rows[0]["cycle_status"] == "PROCESSING", "the cycle stays PROCESSING"


def test_publish_before_release_at_rejected(api):
    """PRD §3.9: "Publishing requires the release `EMBARGO_OPEN`, the clock at or past `release_at` (otherwise `ERR_RELEASE_TOO_EARLY`), and disclosure still `APPROVED` (otherwise `ERR_DISCLOSURE_NOT_APPROVED`)"

    Design: Corner/state_machines/publish_before_release_at_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(code="CES", sample_budget=3)
    panel = setup_enrolled_panel("CES", count=1)
    en1 = panel["enrollments"][0]
    cycle = setup_certified_cycle("CES", "2026-09", panel["enrollments"],
                                  {en1["id"]: 9})
    release = create_release(cycle["id"], "2026-10-01T13:30:00Z")
    approve_disclosure(release["id"])
    open_embargo(release["id"])  # clock now 13:00:00Z, inside the window

    # The clock 2026-10-01T13:00:00Z is before release_at 13:30:00Z.
    resp = api_client.advance_release(
        release["id"],
        release_advance_payload(
            "PUBLISH",
            expected_release_version=get_release(release["id"])["version"]),
        RELEASE_MANAGER)
    validate_error(resp, ApiErrorId.ERR_RELEASE_TOO_EARLY)  # 422

    assert get_release(release["id"])["pub_status"] == "EMBARGO_OPEN", (
        "release remains EMBARGO_OPEN")


def test_accept_report_auto_closes_followup_case(api):
    """PRD §3.3: "Acceptance carries a cross-entity cascade: if a follow-up case exists for the same enrollment and cycle in `OPEN`, `IN_CONTACT`, or `ESCALATED`, it moves at once to `CLOSED_RESPONDED`."
    PRD §3.3: "Accepting a report moves it from `SUBMITTED` to the terminal `ACCEPTED` and is permitted while the cycle is `COLLECTING` or `PROCESSING`"

    Design: Corner/state_machines/accept_report_auto_closes_followup_case
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(code="CES", sample_budget=3)
    panel = setup_enrolled_panel("CES", count=1)
    en1 = panel["enrollments"][0]
    cycle = create_cycle("CES", "2026-09")
    open_collection(cycle)
    report = submit_report(en1, cycle["id"], 9)  # NOT accepted before close
    close_collection(cycle)
    case = find_case(en1["id"], cycle["id"])
    assert case["case_status"] == "OPEN", (
        "SUBMITTED-but-not-ACCEPTED still creates a case at close")

    contacted = record_contact(case["id"], 10, at="2026-09-22T09:00:00Z")
    assert contacted["case_status"] == "IN_CONTACT"

    accepted = accept_report(report["id"])
    assert accepted["report_status"] == "ACCEPTED", (
        "accept allowed while cycle PROCESSING")
    assert get_case(case["id"])["case_status"] == "CLOSED_RESPONDED", (
        "cascade, no explicit close")


def test_postpone_revokes_active_grants(api):
    """PRD §3.9: "Postponing from either `SCHEDULED` or `EMBARGO_OPEN` lands the release in `POSTPONED`; postponing an open embargo revokes every grant of the release in `ISSUED` or `ACCESSED`, moving each to `REVOKED`, and recomputes `active_embargo_grant_count`, which accordingly reads 0."
    PRD §3.9: "thereafter it always counts this release's grants in `ISSUED` or `ACCESSED`, recomputed whenever any of those grants changes status."

    Design: Corner/state_machines/postpone_revokes_active_grants
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(code="CES", sample_budget=3)
    panel = setup_enrolled_panel("CES", count=1)
    en1 = panel["enrollments"][0]
    cycle = setup_certified_cycle("CES", "2026-09", panel["enrollments"],
                                  {en1["id"]: 9})
    staged = setup_embargoed_release(cycle["id"], "2026-10-01T13:30:00Z")
    release = staged["release"]
    grant = staged["grants"][0]
    assert release["active_embargo_grant_count"] == 1, "grant issued at open"

    resp = api_client.advance_release(
        release["id"],
        release_advance_payload(
            "POSTPONE", expected_release_version=release["version"]),
        RELEASE_MANAGER)
    postponed = validate_success(resp)
    assert postponed["pub_status"] == "POSTPONED"
    assert postponed["active_embargo_grant_count"] == 0
    assert get_grant(grant["id"])["grant_status"] == "REVOKED"

    rescheduled = reschedule_release(release["id"], "2026-10-08T13:30:00Z")
    assert rescheduled["pub_status"] == "SCHEDULED"
    assert rescheduled["active_embargo_grant_count"] == 0, (
        "revoked grants are not restored by a later RESCHEDULE")


def test_superseded_factor_set_on_recreate(api):
    """PRD §3.6: "A new set is born `PROVISIONAL`, and creating one for a series and year that already has a set — whether `PROVISIONAL` or `FINAL` — moves the previous set to the terminal `SUPERSEDED`."

    Design: Corner/state_machines/superseded_factor_set_on_recreate
    """
    create_program(code="CES", sample_budget=3)
    s1 = create_factor_set("CES", year=2026,
                           month_overrides={1: 0.95, 9: 1.05})
    s2 = create_factor_set("CES", year=2026,
                           month_overrides={1: 0.98, 9: 1.02})
    assert s2["set_status"] == "PROVISIONAL", "new set starts PROVISIONAL"

    rows, meta = validate_paginated(api_client.list_factor_sets(
        METHODOLOGIST, params={"program_code": "CES", "year": 2026,
                               "set_status": "SUPERSEDED"}))
    assert meta["total_count"] == 1 and rows[0]["id"] == s1["id"], (
        "S1 was superseded by S2's creation")
