"""Verification visits: window validity, the consultant travel-buffer
conflict rule, single-filing lockdown, and the two denial layers on report
filing (role, then ownership).
"""

from test_helpers import (
    ACCREDITATION_REVIEWER,
    CONSULTANT_2_USER_ID,
    CONSULTANT_USER_ID,
    REGISTRAR,
    ApiErrorId,
    create_accepted_self_study,
    create_active_catalog,
    create_school,
    create_verification_visit_payload,
    create_visit,
    file_visit_report_payload,
    list_plans_for_school,
    make_consultant_headers,
    read_visit,
    reset_clock,
    set_clock,
    setup_school_with_reported_visit,
    validate_error,
    validate_success,
)


def test_visit_window_invalid_both_directions(api):
    """PRD section 3.6: "The window itself must not be malformed —
    `window_end` before `window_start`, or `window_start` before the current
    logical date, fails with `ERR_VISIT_WINDOW_INVALID` (HTTP 422)."

    Design: Corner/validations/visit_window_invalid_both_directions
    """
    reset_clock()
    create_active_catalog()
    school = create_school(name="V School", display_name="V Schoolhouse")
    study = create_accepted_self_study(school["id"])

    end_before_start = api.create_verification_visit(
        create_verification_visit_payload(
            school["id"], study["id"], CONSULTANT_USER_ID,
            window_start="2026-10-10", window_end="2026-10-09",
        ),
        headers=ACCREDITATION_REVIEWER,
    )
    validate_error(end_before_start, ApiErrorId.ERR_VISIT_WINDOW_INVALID)

    starts_in_past = api.create_verification_visit(
        create_verification_visit_payload(
            school["id"], study["id"], CONSULTANT_USER_ID,
            window_start="2026-08-01", window_end="2026-08-02",
        ),
        headers=ACCREDITATION_REVIEWER,
    )
    validate_error(starts_in_past, ApiErrorId.ERR_VISIT_WINDOW_INVALID)


def test_visit_report_filed_twice_rejected(api):
    """PRD section 3.6: "the visit must still be `SCHEDULED` (else
    `ERR_INVALID_STATE`, HTTP 409)". PRD section 3.6: "A `COMPLIANT` report
    ends the matter."

    Design: Corner/state_machines/visit_report_filed_twice_rejected
    """
    reset_clock()
    staged = setup_school_with_reported_visit(
        verdict="COMPLIANT", findings=["Fine"]
    )
    second = api.file_visit_report(
        staged.visit["id"],
        file_visit_report_payload(verdict="NONCOMPLIANT", findings=["Changed my mind"]),
        headers=make_consultant_headers(CONSULTANT_USER_ID),
    )
    validate_error(second, ApiErrorId.ERR_INVALID_STATE)

    visit = read_visit(staged.visit["id"])
    assert visit["verdict"] == "COMPLIANT", "the rejected second filing did not overwrite"
    assert visit["report_filed_at"] is not None
    assert list_plans_for_school(staged.school["id"]) == []


def test_registrar_cannot_file_visit_reports_forbidden(api):
    """PRD section 2.1: "A request whose role is authenticated but not listed
    among an endpoint's authorized roles is rejected with `ERR_FORBIDDEN`
    (HTTP 403)." PRD section 3.6: "Only the visit's own consultant may file —
    `X-User-ID` must equal the visit's `consultant_id`, else `ERR_FORBIDDEN`
    (HTTP 403)".

    Design: Corner/rbac/registrar_cannot_file_visit_reports_forbidden
    """
    reset_clock()
    create_active_catalog()
    school = create_school(name="Deny School", display_name="Deny Schoolhouse")
    study = create_accepted_self_study(school["id"])
    visit = create_visit(school["id"], study["id"], consultant_id="con-yes")
    set_clock("2026-10-02T00:00:00Z")

    wrong_role = api.file_visit_report(
        visit["id"],
        file_visit_report_payload(verdict="COMPLIANT", findings=["x"]),
        headers=REGISTRAR,
    )
    validate_error(wrong_role, ApiErrorId.ERR_FORBIDDEN)

    wrong_consultant = api.file_visit_report(
        visit["id"],
        file_visit_report_payload(verdict="COMPLIANT", findings=["x"]),
        headers=make_consultant_headers("con-no"),
    )
    validate_error(wrong_consultant, ApiErrorId.ERR_FORBIDDEN)

    visit = read_visit(visit["id"])
    assert visit["status"] == "SCHEDULED"
    assert visit["verdict"] is None


def test_consultant_buffer_touching_window_conflicts(api):
    """PRD section 3.6: "across that consultant's non-`CANCELLED` visits, each
    existing window expanded by the catalog's `consultant_travel_buffer_days`
    on both ends must not intersect the requested window — expanded windows
    that merely touch still count as a conflict — and a clash fails with
    `ERR_CONSULTANT_SCHEDULE_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/consultant_visit_buffer_overlap_adjacency_conflicts
    """
    reset_clock()
    create_active_catalog()
    school = create_school(name="Buffer School", display_name="Buffer Schoolhouse")
    study = create_accepted_self_study(school["id"])
    create_visit(
        school["id"], study["id"], consultant_id=CONSULTANT_2_USER_ID,
        window_start="2027-10-10", window_end="2027-10-12",
    )

    touching = api.create_verification_visit(
        create_verification_visit_payload(
            school["id"], study["id"], CONSULTANT_2_USER_ID,
            window_start="2027-10-13", window_end="2027-10-14",
        ),
        headers=ACCREDITATION_REVIEWER,
    )
    validate_error(touching, ApiErrorId.ERR_CONSULTANT_SCHEDULE_CONFLICT)


def test_consultant_buffer_one_clear_day_allowed(api):
    """PRD section 3.6: "each existing window expanded by the catalog's
    `consultant_travel_buffer_days` on both ends must not intersect the
    requested window — expanded windows that merely touch still count as a
    conflict". A start one day beyond the buffered edge leaves a clear travel
    day and is admitted; the earlier rejected attempt occupies nothing.

    Design: Difficulty/resource_temporal_overlap/consultant_visit_buffer_overlap_adjacency_conflicts
    """
    reset_clock()
    create_active_catalog()
    school = create_school(name="Buffer School", display_name="Buffer Schoolhouse")
    study = create_accepted_self_study(school["id"])
    create_visit(
        school["id"], study["id"], consultant_id=CONSULTANT_2_USER_ID,
        window_start="2027-10-10", window_end="2027-10-12",
    )
    api.create_verification_visit(
        create_verification_visit_payload(
            school["id"], study["id"], CONSULTANT_2_USER_ID,
            window_start="2027-10-13", window_end="2027-10-14",
        ),
        headers=ACCREDITATION_REVIEWER,
    )

    clear_day = api.create_verification_visit(
        create_verification_visit_payload(
            school["id"], study["id"], CONSULTANT_2_USER_ID,
            window_start="2027-10-14", window_end="2027-10-16",
        ),
        headers=ACCREDITATION_REVIEWER,
    )
    created = validate_success(clear_day, 201)
    assert created["status"] == "SCHEDULED"
