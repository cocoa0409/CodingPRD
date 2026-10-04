"""Depth tests: cross-entity state dependencies and interval semantics.

Whether a report may be created depends on the cycle's state; whether a
grant is minted depends on the outlet's accreditation at the exact open
instant; embargo windows are half-open intervals; frame quarters must be
strictly contiguous.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_report,
    api_client,
    approve_disclosure,
    assert_same_instant,
    certify_cycle,
    close_collection,
    collect_cycle,
    create_cycle,
    create_frame,
    create_outlet,
    create_program,
    create_release,
    create_sample_frame_payload,
    create_stratum,
    get_program_version,
    grant_for_outlet,
    list_grants,
    make_respondent_headers,
    open_collection,
    open_embargo,
    outlet_action,
    set_clock,
    setup_certified_cycle,
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


def test_report_create_blocked_when_cycle_processing(api):
    """PRD §3.3: "Two distinct temporal guards apply, in the order of §2.8: the cycle must still be in `COLLECTING` — once it has been closed, submission is rejected with `ERR_CYCLE_NOT_COLLECTING` — and the logical clock must not have passed `collection_close_at`, otherwise submission is rejected with `ERR_REPORT_WINDOW_CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/report_create_blocked_when_cycle_processing
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(code="CES", sample_budget=3,
                                    annual_burden_budget_minutes=500)
    panel = setup_enrolled_panel("CES", count=2)
    en1, en2 = panel["enrollments"]
    cycle = create_cycle("CES", "2026-09")
    open_collection(cycle)
    accept_report(submit_report(en1, cycle["id"], 9)["id"])
    close_collection(cycle)  # cycle leaves COLLECTING

    resp = api_client.create_report(
        {"enrollment_id": en2["id"], "cycle_id": cycle["id"],
         "employment": 7},
        make_respondent_headers(en2["establishment_id"]))
    validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_COLLECTING)
    # 409: the cycle-state gate (an earlier pipeline stage) beats the
    # also-true report-window temporal violation.

    rows, meta = validate_paginated(api_client.list_reports(
        COLLECTOR, params={"enrollment_id": en2["id"],
                           "cycle_id": cycle["id"]}))
    assert meta["total_count"] == 0 and rows == [], (
        "no report row exists for the rejected submission")


def test_grant_issuance_skips_suspended_outlet(api):
    """PRD §3.9: "When the embargo opens, the system creates one embargo grant per media outlet whose `accreditation_status` is `ACCREDITED` at that exact moment — outlets accredited later simply miss this release"
    PRD §3.9: "The release's `active_embargo_grant_count` is set to the number of grants created"

    Design: Difficulty/cross_entity_state_dependency/grant_issuance_skips_suspended_outlet
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(code="CES", sample_budget=3,
                                    annual_burden_budget_minutes=500)
    panel = setup_enrolled_panel("CES", count=1)
    en1 = panel["enrollments"][0]
    cycle = setup_certified_cycle("CES", "2026-09", panel["enrollments"],
                                  {en1["id"]: 9})

    o1 = create_outlet(name="Wire Service")
    o2 = create_outlet(name="Daily News")
    outlet_action(o1["id"], "ACCREDIT")
    outlet_action(o2["id"], "ACCREDIT")
    outlet_action(o2["id"], "SUSPEND")  # suspended before the embargo opens

    release = create_release(cycle["id"], "2026-10-01T13:30:00Z")
    approve_disclosure(release["id"])
    opened = open_embargo(release["id"])
    assert opened["active_embargo_grant_count"] == 1, (
        "only O1 was ACCREDITED at OPEN_EMBARGO")

    grant = grant_for_outlet(release["id"], o1["id"])
    assert grant["grant_status"] == "ISSUED"
    assert grant["media_outlet_id"] == o1["id"]

    rows, meta = validate_paginated(api_client.list_grants(
        RELEASE_MANAGER, params={"media_outlet_id": o2["id"]}))
    assert meta["total_count"] == 0 and rows == [], (
        "the suspended outlet received no grant")


def test_embargo_windows_half_open_adjacency(api):
    """PRD §2.9: "The window is half-open: it includes its opening instant and excludes the release instant itself."
    PRD §2.9: "Because windows are half-open, back-to-back windows — one release's `release_at` landing exactly on another release's `embargo_open_at` — do not overlap and are permitted. A schedule or reschedule whose window would overlap a live window of the same program is rejected with `ERR_EMBARGO_WINDOW_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/embargo_windows_half_open_adjacency
    """
    set_clock("2026-09-01T00:00:00Z")
    create_program(code="CES", sample_budget=3)
    cyc_sep = create_cycle("CES", "2026-09")
    cyc_oct = create_cycle("CES", "2026-10")
    cyc_nov = create_cycle("CES", "2026-11")

    r1 = create_release(cyc_sep["id"], "2026-10-01T13:30:00Z")
    assert_same_instant(r1["embargo_open_at"], "2026-10-01T13:00:00Z")

    # Back-to-back: R2's window [13:30, 14:00) touches R1's [13:00, 13:30).
    r2 = validate_success(api_client.create_release(
        {"cycle_id": cyc_oct["id"], "release_at": "2026-10-01T14:00:00Z"},
        RELEASE_MANAGER), 201)
    assert_same_instant(r2["embargo_open_at"], "2026-10-01T13:30:00Z"), (
        "adjacent windows do not overlap under half-open semantics")

    # One second earlier: [12:59:59, 13:29:59) intersects R1's window.
    resp = api_client.create_release(
        {"cycle_id": cyc_nov["id"], "release_at": "2026-10-01T13:29:59Z"},
        RELEASE_MANAGER)
    validate_error(resp, ApiErrorId.ERR_EMBARGO_WINDOW_OVERLAP)  # 409


def test_frame_quarters_strict_contiguity(api):
    """PRD §3.1: "First, if a non-`SUPERSEDED` frame already covers the same `reference_quarter` and the request did not name a `replaces_frame_id`, creation is rejected with `ERR_DUPLICATE_FRAME_PERIOD`. Second, without a `replaces_frame_id`, the new frame's quarter must be the quarter immediately following the latest non-`SUPERSEDED` frame's quarter — the program's very first frame may name any quarter — and a skipped or repeated quarter is rejected with `ERR_FRAME_PERIOD_GAP`."
    PRD §3.1: "Because frame creation mutates the program — its `version` increments by 1 on every successful creation, replacement or not"

    Design: Difficulty/resource_temporal_overlap/frame_quarters_strict_contiguity
    """
    set_clock("2026-09-01T00:00:00Z")
    create_program(code="CES", sample_budget=3)
    f1 = create_frame("CES", "2026-Q3",
                      strata=[create_stratum("MANUFACTURING", "SMALL", 100)])
    assert f1["frame_status"] == "DRAFT"
    prog_v2 = get_program_version("CES")  # advanced by F1's creation

    strata = [create_stratum("MANUFACTURING", "SMALL", 100)]

    resp = api_client.create_sample_frame(
        create_sample_frame_payload("CES", "2027-Q1", strata, prog_v2), ADMIN)
    validate_error(resp, ApiErrorId.ERR_FRAME_PERIOD_GAP)  # skips 2026-Q4

    resp = api_client.create_sample_frame(
        create_sample_frame_payload("CES", "2026-Q3", strata, prog_v2), ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_FRAME_PERIOD)  # re-entered

    # The immediate successor is accepted — with the pre-failure version,
    # proving the rejected creates did not bump SurveyProgram.version.
    f2 = validate_success(api_client.create_sample_frame(
        create_sample_frame_payload("CES", "2026-Q4", strata, prog_v2), ADMIN),
        201)
    assert f2["reference_quarter"] == "2026-Q4"
