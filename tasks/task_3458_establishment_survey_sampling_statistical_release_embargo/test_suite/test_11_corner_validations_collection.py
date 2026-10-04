"""Corner coverage: validations on the collection side of the pipeline.

Authentication, collection-window and enrollment guards on report creation,
uniqueness constraints (cycles, enrollments, reports), and the frame gates
on enrollment.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_cycle,
    create_establishment_payload,
    create_frame,
    create_program,
    create_program_payload,
    create_stratum,
    enroll,
    freeze_frame,
    lifecycle,
    make_respondent_headers,
    open_collection,
    register_establishment,
    set_clock,
    setup_enrolled_panel,
    setup_program_with_frozen_frame,
    submit_report,
    validate_error,
)

ADMIN = TEST_USERS["program_admin_headers"]
COLLECTOR = TEST_USERS["collection_officer_headers"]


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting a role outside this declared list, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_role_header_unauthenticated
    """
    resp = api_client.create_program(
        create_program_payload(code="CES", name="X", sample_budget=3),
        headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)  # 401


def test_submit_after_window_closed_while_collecting_rejected(api):
    """PRD §3.3: "the logical clock must not have passed `collection_close_at`, otherwise submission is rejected with `ERR_REPORT_WINDOW_CLOSED`."
    PRD §3.3: "The second guard has teeth precisely because the first does not cover it: a cycle whose officer simply never closed collection remains `COLLECTING` on paper, yet late submissions are still refused at the window."

    Design: Corner/validations/submit_after_window_closed_while_collecting_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(code="CES", sample_budget=3)
    panel = setup_enrolled_panel("CES", count=1)
    en1 = panel["enrollments"][0]
    cycle = create_cycle("CES", "2026-09")
    open_collection(cycle)
    set_clock("2026-09-21T00:00:00Z")  # past the 20th 23:59:59Z close

    resp = api_client.create_report(
        {"enrollment_id": en1["id"], "cycle_id": cycle["id"],
         "employment": 9},
        make_respondent_headers(en1["establishment_id"]))
    validate_error(resp, ApiErrorId.ERR_REPORT_WINDOW_CLOSED)  # 422, not
    # ERR_CYCLE_NOT_COLLECTING — the cycle was never closed.


def test_duplicate_cycle_rejected(api):
    """PRD §3.3: "one cycle may exist per program and reference month, and a duplicate is rejected with `ERR_DUPLICATE_CYCLE`."

    Design: Corner/validations/duplicate_cycle_rejected
    """
    create_program(code="CES", sample_budget=3)
    create_cycle("CES", "2026-09")
    resp = api_client.create_cycle(
        {"program_code": "CES", "reference_month": "2026-09"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CYCLE)  # 409


def test_enroll_without_frozen_frame_rejected(api):
    """PRD §3.2: "The program must have a latest frame in `FROZEN` status — the most recently frozen frame that has not been superseded — otherwise the enrollment is rejected with `ERR_FRAME_NOT_FROZEN`."

    Design: Corner/validations/enroll_without_frozen_frame_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    create_program(code="CES", sample_budget=3)
    create_frame("CES", "2026-Q3",
                 strata=[create_stratum("MANUFACTURING", "SMALL", 100)])
    est = register_establishment()  # frame left DRAFT

    resp = api_client.create_enrollment(
        {"establishment_id": est["id"], "program_code": "CES"}, COLLECTOR)
    validate_error(resp, ApiErrorId.ERR_FRAME_NOT_FROZEN)  # 409


def test_enroll_unknown_stratum_rejected(api):
    """PRD §3.2: "The establishment's `industry_code` and `size_class` pair must match one of that frame's strata, otherwise the enrollment is rejected with `ERR_STRATUM_UNKNOWN`."

    Design: Corner/validations/enroll_unknown_stratum_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(code="CES", sample_budget=3)
    est = register_establishment(industry_code="RETAIL", size_class="LARGE")

    resp = api_client.create_enrollment(
        {"establishment_id": est["id"], "program_code": "CES"}, COLLECTOR)
    validate_error(resp, ApiErrorId.ERR_STRATUM_UNKNOWN)  # 409; the frozen
    # frame covers only (MANUFACTURING, SMALL).


def test_enroll_over_stratum_quota_rejected(api):
    """PRD §3.2: "And the stratum's sample quota must have room: the count of non-terminal enrollments — those in `INVITED`, `ENROLLED`, or `SUSPENDED` — for that stratum must still be below the stratum's `allocated_sample_size`, otherwise the enrollment is rejected with `ERR_STRATUM_SAMPLE_FULL`."

    Design: Corner/validations/enroll_over_stratum_quota_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    create_program(code="CES", sample_budget=2)
    frame = create_frame("CES", "2026-Q3",
                         strata=[create_stratum("MANUFACTURING", "SMALL", 10)])
    frozen = freeze_frame(frame["id"])
    assert frozen["total_sample_size"] == 2, (
        "single stratum receives the whole budget")

    e1 = register_establishment()
    e2 = register_establishment()
    e3 = register_establishment()
    enroll(e1["id"], "CES")  # INVITED counts toward the quota
    enroll(e2["id"], "CES")
    resp = api_client.create_enrollment(
        {"establishment_id": e3["id"], "program_code": "CES"}, COLLECTOR)
    validate_error(resp, ApiErrorId.ERR_STRATUM_SAMPLE_FULL)  # 409


def test_duplicate_enrollment_rejected(api):
    """PRD §3.2: "Independently, one establishment may hold only one non-terminal enrollment per program; a second live enrollment for the same `establishment_id` and `program_code` is rejected with `ERR_DUPLICATE_ENROLLMENT`."

    Design: Corner/validations/duplicate_enrollment_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(code="CES", sample_budget=3)
    est = register_establishment()
    enroll(est["id"], "CES")  # INVITED already blocks re-invitation

    resp = api_client.create_enrollment(
        {"establishment_id": est["id"], "program_code": "CES"}, COLLECTOR)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENROLLMENT)  # 409


def test_duplicate_report_rejected(api):
    """PRD §3.3: "one report may exist per enrollment and cycle, with duplicates rejected as `ERR_DUPLICATE_REPORT`"

    Design: Corner/validations/duplicate_report_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(code="CES", sample_budget=3)
    panel = setup_enrolled_panel("CES", count=1)
    en1 = panel["enrollments"][0]
    cycle = create_cycle("CES", "2026-09")
    open_collection(cycle)
    submit_report(en1, cycle["id"], 9)

    resp = api_client.create_report(
        {"enrollment_id": en1["id"], "cycle_id": cycle["id"],
         "employment": 10},
        make_respondent_headers(en1["establishment_id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_REPORT)  # 409; corrections
    # go through RETURN + resubmit, not a second row.


def test_report_for_invited_enrollment_rejected(api):
    """PRD §3.3: "The enrollment itself must be `ENROLLED`, otherwise the create is rejected with `ERR_ENROLLMENT_NOT_ACTIVE`"

    Design: Corner/validations/report_for_invited_enrollment_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(code="CES", sample_budget=3)
    est = register_establishment()
    enrollment = enroll(est["id"], "CES")  # still INVITED, never accepted
    cycle = create_cycle("CES", "2026-09")
    open_collection(cycle)

    resp = api_client.create_report(
        {"enrollment_id": enrollment["id"], "cycle_id": cycle["id"],
         "employment": 9},
        make_respondent_headers(est["id"]))
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE)  # 409
