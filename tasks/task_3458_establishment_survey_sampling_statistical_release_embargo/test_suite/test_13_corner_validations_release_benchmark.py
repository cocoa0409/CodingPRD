"""Corner coverage: validations on releases, benchmarks, notices, factors.

Disclosure gates, segregation of duties, release uniqueness and window
overlap against dormant releases, finalize/activate timing, benchmark cell
checks, and freeze feasibility.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    approve_disclosure,
    certify_cycle,
    create_admin_cell_count,
    create_benchmark_run,
    create_cycle,
    create_factor_set,
    create_frame,
    create_notice,
    create_program,
    create_release,
    create_stratum,
    get_release,
    get_single_cell,
    list_grants,
    make_disclosure_officer_headers,
    notice_action,
    postpone_release,
    release_advance_payload,
    set_clock,
    setup_certified_cycle,
    setup_enrolled_panel,
    setup_program_with_frozen_frame,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
COLLECTOR = TEST_USERS["collection_officer_headers"]
METHODOLOGIST = TEST_USERS["survey_methodologist_headers"]
RELEASE_MANAGER = TEST_USERS["release_manager_headers"]
ANALYST_USER_ID = "analyst-1"
OFFICER_USER_ID = "officer-7"


def _certified_september_cycle():
    """One-enrollment program; September cycle reported (9) and CERTIFIED."""
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(code="CES", sample_budget=3)
    panel = setup_enrolled_panel("CES", count=1)
    en1 = panel["enrollments"][0]
    return setup_certified_cycle("CES", "2026-09", panel["enrollments"],
                                 {en1["id"]: 9})


def test_open_embargo_without_disclosure_approval_rejected(api):
    """PRD §3.9: "Opening the embargo — a `ReleaseManager` action — requires the release still `SCHEDULED`, the logical clock at or past `embargo_open_at` (otherwise `ERR_RELEASE_TOO_EARLY`), the cycle `CERTIFIED` (otherwise `ERR_CYCLE_NOT_CERTIFIED`), and disclosure `APPROVED` (otherwise `ERR_DISCLOSURE_NOT_APPROVED`)."

    Design: Corner/validations/open_embargo_without_disclosure_approval_rejected
    """
    cycle = _certified_september_cycle()
    release = create_release(cycle["id"], "2026-10-01T13:30:00Z")
    set_clock("2026-10-01T13:00:00Z")  # at embargo_open_at

    resp = api_client.advance_release(
        release["id"],
        release_advance_payload(
            "OPEN_EMBARGO", expected_release_version=release["version"]),
        RELEASE_MANAGER)
    validate_error(resp, ApiErrorId.ERR_DISCLOSURE_NOT_APPROVED)  # 409

    assert list_grants(release_event_id=release["id"]) == [], (
        "no grants are minted")
    assert get_release(release["id"])["pub_status"] == "SCHEDULED"


def test_disclosure_review_by_certifier_segregation_rejected(api):
    """PRD §3.9: "the reviewer must not be the analyst who certified the cycle — the reviewer's `X-User-ID` must differ from the cycle's `certified_by_user_id`, otherwise the review is rejected with `ERR_SEGREGATION_OF_DUTIES`"
    PRD §3.5: "Success records the certifying analyst's `X-User-ID` in `certified_by_user_id`, the value the segregation-of-duties check later enforces."

    Design: Corner/validations/disclosure_review_by_certifier_segregation_rejected
    """
    cycle = _certified_september_cycle()  # certified by analyst-1
    assert cycle["certified_by_user_id"] == ANALYST_USER_ID
    release = create_release(cycle["id"], "2026-10-01T13:30:00Z")

    resp = api_client.advance_release(
        release["id"],
        release_advance_payload(
            "APPROVE_DISCLOSURE",
            expected_release_version=release["version"]),
        make_disclosure_officer_headers(ANALYST_USER_ID))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)  # 403: the
    # same person may not certify and approve.

    approved = approve_disclosure(release["id"], OFFICER_USER_ID)
    assert approved["disclosure_status"] == "APPROVED", (
        "the failed attempt did not mutate state; an independent officer "
        "succeeds")


def test_second_release_for_same_cycle_rejected(api):
    """PRD §3.9: "one release may exist per cycle, with duplicates rejected as `ERR_DUPLICATE_RELEASE`"

    Design: Corner/validations/second_release_for_same_cycle_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    create_program(code="CES", sample_budget=3)
    cycle = create_cycle("CES", "2026-09")
    create_release(cycle["id"], "2026-10-01T13:30:00Z")

    resp = api_client.create_release(
        {"cycle_id": cycle["id"], "release_at": "2026-10-02T13:30:00Z"},
        RELEASE_MANAGER)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RELEASE)  # 409, even with
    # a different release_at.


def test_overlapping_release_against_postponed_allowed(api):
    """PRD §2.9: "The overlap check considers only releases in `SCHEDULED` or `EMBARGO_OPEN` status; `POSTPONED` and `PUBLISHED` releases are excluded entirely."

    Design: Corner/validations/overlapping_release_against_postponed_allowed
    """
    set_clock("2026-09-01T00:00:00Z")
    create_program(code="CES", sample_budget=3)
    c1 = create_cycle("CES", "2026-09")
    c2 = create_cycle("CES", "2026-10")
    r1 = create_release(c1["id"], "2026-10-01T13:30:00Z")
    postponed = postpone_release(r1["id"])
    assert postponed["pub_status"] == "POSTPONED"

    # R2's window [12:45, 13:15) overlaps R1's dormant [13:00, 13:30).
    r2 = validate_success(api_client.create_release(
        {"cycle_id": c2["id"], "release_at": "2026-10-01T13:15:00Z"},
        RELEASE_MANAGER), 201)
    assert r2["pub_status"] == "SCHEDULED", (
        "POSTPONED releases are excluded from the overlap check")


def test_factor_finalize_before_year_end_rejected(api):
    """PRD §3.6: "It is gated on the calendar: the logical clock must have reached January 1 at 00:00:00 UTC of the year after the set's `year`, otherwise the finalize is rejected with `ERR_FACTOR_SET_FINALIZE_TOO_EARLY`."

    Design: Corner/validations/factor_finalize_before_year_end_rejected
    """
    set_clock("2026-12-31T23:59:59Z")
    create_program(code="CES", sample_budget=3)
    s1 = create_factor_set("CES", year=2026,
                           month_overrides={1: 0.95, 9: 1.05})

    resp = api_client.finalize_factor_set(s1["id"], METHODOLOGIST)
    validate_error(resp, ApiErrorId.ERR_FACTOR_SET_FINALIZE_TOO_EARLY)  # 422
    # one second before the year boundary

    set_clock("2027-01-01T00:00:00Z")
    finalized = validate_success(
        api_client.finalize_factor_set(s1["id"], METHODOLOGIST))
    assert finalized["set_status"] == "FINAL", (
        "inclusive boundary at exactly 2027-01-01T00:00:00Z")


def test_notice_activate_before_effective_rejected(api):
    """PRD §3.8: "Activation moves `ANNOUNCED` to the terminal `EFFECTIVE` and requires the clock to have reached `effective_from`, otherwise the advance is rejected with `ERR_NOTICE_NOT_EFFECTIVE`; activation stamps `activated_at`."
    PRD §3.8: "the `effective_from` instant must lie strictly after the current logical-clock reading, otherwise the announce is rejected with `ERR_VALIDATION`."

    Design: Corner/validations/notice_activate_before_effective_rejected
    """
    set_clock("2027-01-15T00:00:00Z")
    create_program(code="CES", sample_budget=3)
    notice = create_notice("CES", "NAICS 2027 conversion",
                           "2027-02-01T00:00:00Z",
                           reconstruction_factor_ppm=1100000)
    announced = notice_action(notice["id"], "ANNOUNCE")
    assert announced["notice_status"] == "ANNOUNCED"

    resp = api_client.advance_notice(
        notice["id"], {"action": "ACTIVATE"}, METHODOLOGIST)
    validate_error(resp, ApiErrorId.ERR_NOTICE_NOT_EFFECTIVE)  # 422: clock
    # 2027-01-15 is before effective_from 2027-02-01.


def test_benchmark_apply_missing_cell_rejected(api):
    """PRD §3.7: "Every entry in `admin_cell_counts` must match a cell estimate on the benchmark-month cycle for that industry and size whose `estimate_status` is `PRELIMINARY` or `REVISED` — a cell already `FINAL` or `RECONSTRUCTED` does not satisfy this — otherwise the apply is rejected with `ERR_BENCHMARK_CELL_MISSING`."

    Design: Corner/validations/benchmark_apply_missing_cell_rejected
    """
    set_clock("2026-12-01T00:00:00Z")
    setup_program_with_frozen_frame(
        code="CES", sample_budget=4, reference_quarter="2026-Q4",
        strata=[create_stratum("MANUFACTURING", "SMALL", 40)])
    panel = setup_enrolled_panel("CES", count=4)
    cycle = setup_certified_cycle(
        "CES", "2026-12", panel["enrollments"],
        {en["id"]: 25 for en in panel["enrollments"]})

    run = create_benchmark_run("CES", "2026-12", [
        create_admin_cell_count("MANUFACTURING", "SMALL", 1045),
        create_admin_cell_count("RETAIL", "MEDIUM", 300),
    ])
    resp = api_client.apply_benchmark_run(run["id"], METHODOLOGIST)
    validate_error(resp, ApiErrorId.ERR_BENCHMARK_CELL_MISSING)  # 422: the
    # RETAIL/MEDIUM entry has no cell estimate for 2026-12.

    cell = get_single_cell(cycle["id"], "MANUFACTURING", "SMALL")
    assert cell["employment_estimate"] == 1000
    assert cell["estimate_status"] == "PRELIMINARY", (
        "validation precedes mutation: the matching cell is NOT modified")


def test_benchmark_zero_estimate_undefined_wedge_rejected(api):
    """PRD §3.7: "And where a benchmark-month cell's `employment_estimate` is 0, the administrative count must also be 0, in which case the wedge is defined as exactly 1.000000; a zero estimate facing a positive administrative count leaves the wedge undefined and the apply is rejected with `ERR_BENCHMARK_UNDEFINED_WEDGE`."

    Design: Corner/validations/benchmark_zero_estimate_undefined_wedge_rejected
    """
    set_clock("2026-12-01T00:00:00Z")
    setup_program_with_frozen_frame(
        code="CES", sample_budget=4, reference_quarter="2026-Q4",
        strata=[create_stratum("MANUFACTURING", "SMALL", 40)])
    panel = setup_enrolled_panel("CES", count=4)
    cycle = setup_certified_cycle(
        "CES", "2026-12", panel["enrollments"],
        {en["id"]: 0 for en in panel["enrollments"]})  # estimate 0

    run = create_benchmark_run("CES", "2026-12", [
        create_admin_cell_count("MANUFACTURING", "SMALL", 50)])
    resp = api_client.apply_benchmark_run(run["id"], METHODOLOGIST)
    validate_error(resp, ApiErrorId.ERR_BENCHMARK_UNDEFINED_WEDGE)  # 422


def test_infeasible_budget_at_freeze_rejected(api):
    """PRD §3.1: "Feasibility comes first: the program's `sample_budget` must be at least twice the number of strata on the frame, because every stratum is guaranteed a minimum allocation of 2, and a budget that cannot meet that floor is rejected with `ERR_SAMPLE_BUDGET_INFEASIBLE`."

    Design: Corner/validations/infeasible_budget_at_freeze_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    create_program(code="CES", sample_budget=3)
    frame = create_frame("CES", "2026-Q3",
                         strata=[create_stratum("MANUFACTURING", "SMALL", 100),
                                 create_stratum("RETAIL", "MEDIUM", 60)])

    resp = api_client.freeze_sample_frame(frame["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_SAMPLE_BUDGET_INFEASIBLE)  # 422:
    # budget 3 cannot meet 2 strata x minimum 2.

    frame = validate_success(api_client.get_sample_frame(frame["id"], ADMIN))
    assert frame["frame_status"] == "DRAFT"
