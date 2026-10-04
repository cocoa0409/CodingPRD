"""Coverage windows: open-ended defaults, closed-interval overlap semantics,
and optimistic concurrency on window creation."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_coverage_window_payload,
    set_clock, setup_employer_with_member,
)


class TestCoverageWindowDefaults:
    def test_coverage_window_defaults_effective_end_null_and_open(
            self, api, platform_admin_headers):
        """PRD §3.1: "each carries a `coverage_tier` of `EMPLOYEE_ONLY`,
        `EMPLOYEE_SPOUSE`, `EMPLOYEE_CHILDREN`, or `FAMILY`, an inclusive
        `effective_start` date, and an `effective_end` date that is null for an
        open-ended window."

        Design: Corner/entities/coverage_window_defaults_effective_end_null_and_open
        """
        set_clock()
        _, member = setup_employer_with_member()
        resp = api.create_coverage_window(
            member["id"],
            create_coverage_window_payload(
                coverage_tier="FAMILY", effective_start="2026-01-01",
                expected_member_version=member["version"]),
            platform_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert data["effective_end"] is None
        assert data["status"] == "OPEN"


class TestCoverageWindowOverlap:
    def test_overlap_shared_boundary_day_rejected(
            self, api, platform_admin_headers):
        """PRD §3.1: "Windows of a member use closed-interval semantics: a new
        window whose `[effective_start, effective_end]` shares even one day with
        an existing window of the same member is rejected with
        `ERR_COVERAGE_OVERLAP` (409), while pure contiguity — an existing window
        ending the day before the new one begins — is allowed."

        Design: Difficulty/resource_temporal_overlap/coverage_window_closed_interval_overlap_and_contiguity
        """
        set_clock()
        _, member = setup_employer_with_member()
        validate_success(api.create_coverage_window(
            member["id"],
            create_coverage_window_payload(
                coverage_tier="EMPLOYEE_ONLY", effective_start="2026-01-01",
                effective_end="2026-06-30",
                expected_member_version=member["version"]),
            platform_admin_headers), expected_status=201)
        fresh = validate_success(api.get_member(
            member["id"], platform_admin_headers))

        overlap = api.create_coverage_window(
            member["id"],
            create_coverage_window_payload(
                coverage_tier="FAMILY", effective_start="2026-06-30",
                effective_end="2026-12-31",
                expected_member_version=fresh["version"]),
            platform_admin_headers)
        validate_error(overlap, ApiErrorId.ERR_COVERAGE_OVERLAP,
                       expected_status=409)

    def test_contiguous_window_allowed(self, api, platform_admin_headers):
        """PRD §3.1: "while pure contiguity — an existing window ending the day
        before the new one begins — is allowed."

        Design: Difficulty/resource_temporal_overlap/coverage_window_closed_interval_overlap_and_contiguity
        """
        set_clock()
        _, member = setup_employer_with_member()
        validate_success(api.create_coverage_window(
            member["id"],
            create_coverage_window_payload(
                coverage_tier="EMPLOYEE_ONLY", effective_start="2026-01-01",
                effective_end="2026-06-30",
                expected_member_version=member["version"]),
            platform_admin_headers), expected_status=201)
        fresh = validate_success(api.get_member(
            member["id"], platform_admin_headers))

        ok = api.create_coverage_window(
            member["id"],
            create_coverage_window_payload(
                coverage_tier="FAMILY", effective_start="2026-07-01",
                effective_end="2026-12-31",
                expected_member_version=fresh["version"]),
            platform_admin_headers)
        data = validate_success(ok, expected_status=201)
        assert data["coverage_tier"] == "FAMILY"
        assert data["effective_start"] == "2026-07-01"


class TestCoverageWindowOcc:
    def test_stale_member_version_rejected_with_412(
            self, api, platform_admin_headers):
        """PRD §2.7: "a creation request carrying an `expected_member_version`
        below the member's current `version` is rejected with
        `ERR_STALE_VERSION` (HTTP 412): the client's view of the member's
        coverage is stale because an earlier window creation has already
        advanced the aggregate."

        Design: Corner/validations/occ_stale_member_version_on_coverage_window_create
        """
        set_clock()
        _, member = setup_employer_with_member()
        validate_success(api.create_coverage_window(
            member["id"],
            create_coverage_window_payload(
                coverage_tier="EMPLOYEE_ONLY", effective_start="2026-01-01",
                expected_member_version=member["version"]),
            platform_admin_headers), expected_status=201)

        stale = api.create_coverage_window(
            member["id"],
            create_coverage_window_payload(
                coverage_tier="FAMILY", effective_start="2026-07-01",
                expected_member_version=member["version"]),
            platform_admin_headers)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION,
                       expected_status=412)

    def test_fresh_version_succeeds_and_supersedes_prior_open_window(
            self, api, platform_admin_headers):
        """PRD §3.1: "Opening an open-ended window supersedes the member's
        prior `OPEN` window automatically: the prior window's `effective_end` is
        set to the day before the new window's `effective_start`, its `status`
        becomes `CLOSED`, and the member's `version` increments because the
        supersede mutates the member aggregate."

        Design: Corner/validations/occ_stale_member_version_on_coverage_window_create
        """
        set_clock()
        _, member = setup_employer_with_member()
        first = validate_success(api.create_coverage_window(
            member["id"],
            create_coverage_window_payload(
                coverage_tier="EMPLOYEE_ONLY", effective_start="2026-01-01",
                expected_member_version=member["version"]),
            platform_admin_headers), expected_status=201)

        fresh = validate_success(api.get_member(
            member["id"], platform_admin_headers))
        assert fresh["version"] == member["version"] + 1

        second = validate_success(api.create_coverage_window(
            member["id"],
            create_coverage_window_payload(
                coverage_tier="FAMILY", effective_start="2026-07-01",
                expected_member_version=fresh["version"]),
            platform_admin_headers), expected_status=201)
        assert second["status"] == "OPEN"
        assert second["effective_start"] == "2026-07-01"

        prior = None
        for w in validate_success(api.list_coverage_windows(
                member["id"], platform_admin_headers)):
            if w["id"] == first["id"]:
                prior = w
        assert prior is not None
        assert prior["status"] == "CLOSED"
        assert prior["effective_end"] == "2026-06-30"
