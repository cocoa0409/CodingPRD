"""Difficulty queue A: resource_temporal_overlap — half-open schedule adjacency
vs inclusive-day report coverage."""
from test_helpers import (
    ApiErrorId,
    create_active_licensee,
    create_effective_schedule,
    create_rate_schedule_payload,
    create_report_with_lines,
    create_usage_report_payload,
    make_admin_headers,
    make_licensee_headers,
    make_royalty_ops_headers,
    validate_error,
    validate_success,
)

ADMIN = make_admin_headers()
OPS = make_royalty_ops_headers()


class TestRateScheduleHalfOpenAdjacency:
    def test_adjacent_schedule_start_equals_prior_end_allowed(self, api):
        """PRD §2.7: "Rate schedules collide under half-open semantics. Two
        RateSchedules of the same `category`, each in DRAFT or EFFECTIVE status,
        may not have windows that overlap under half-open adjacency semantics —
        that is, treating each window as the interval from `effective_start`
        inclusive up to but not including the day after `effective_end`.
        Back-to-back schedules are allowed: one schedule's `effective_start` may
        equal the day after another's `effective_end`."

        Design: Difficulty/resource_temporal_overlap/rate_schedule_half_open_adjacency
        """
        create_effective_schedule(category="BUSINESS_ESTABLISHMENT",
                                  proceeding_ref="D-2025-BE")
        # Back-to-back per PRD §2.7: the new schedule's effective_start equals
        # the day after the prior schedule's effective_end (2026-12-31), i.e.
        # 2027-01-01 — allowed under half-open semantics.
        adjacent = api.create_rate_schedule(
            create_rate_schedule_payload(
                proceeding_ref="D-2026-BE",
                effective_start="2027-01-01T00:00:00Z",
                effective_end="2027-12-30T00:00:00Z",
                rate_per_performance_microcents=3000,
                min_fee_cents=120000,
                category="BUSINESS_ESTABLISHMENT",
            ),
            ADMIN,
        )
        created = validate_success(adjacent, expected_status=201)
        assert created["schedule_status"] == "DRAFT"

    def test_interior_overlap_schedule_rejected(self, api):
        """PRD §2.7: "This check runs both when a schedule is created and when a
        DRAFT schedule is activated; a collision is rejected with
        `ERR_RATE_SCHEDULE_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/rate_schedule_half_open_adjacency
        """
        create_effective_schedule(category="BUSINESS_ESTABLISHMENT",
                                  proceeding_ref="D-2025-BE")
        err = api.create_rate_schedule(
            create_rate_schedule_payload(
                proceeding_ref="D-2026-BE2",
                effective_start="2026-06-01T00:00:00Z",
                effective_end="2027-05-31T00:00:00Z",
                rate_per_performance_microcents=3000,
                min_fee_cents=120000,
                category="BUSINESS_ESTABLISHMENT",
            ),
            ADMIN,
        )
        validate_error(err, ApiErrorId.ERR_RATE_SCHEDULE_OVERLAP.value)


class TestUsageReportInclusiveDayCoverage:
    def test_shared_boundary_day_is_a_collision(self, api):
        """PRD §2.7: "Usage reports collide under aggregate-coverage semantics.
        A usage report's proposed window from `period_start` through
        `period_end` may not share any single day — both ends inclusive — with
        any other usage report of the same licensee that is in SUBMITTED,
        ACCEPTED, or AMENDED status."
        PRD §2.7: "A collision is rejected with `ERR_USAGE_REPORT_OVERLAP`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/usage_report_inclusive_day_coverage
        """
        create_effective_schedule()
        lic = create_active_licensee(legal_name="InclCo")
        lh = make_licensee_headers(lic["id"])
        r1, _ = create_report_with_lines(
            lic["id"],
            [{"isrc": "NM-I1", "track_title": "i1", "artist_name": "i1",
              "performance_count": 10}],
            "2026-06-01T00:00:00Z",
            "2026-06-30T00:00:00Z",
        )
        validate_success(api.submit_usage_report(r1["id"], lh))
        # r2 shares the single boundary day 2026-06-30 with the SUBMITTED r1,
        # so creating r2 already collides under inclusive-day coverage (§2.7).
        err = api.create_usage_report(
            create_usage_report_payload(
                lic["id"],
                period_start="2026-06-30T00:00:00Z",
                period_end="2026-07-30T00:00:00Z",
            ),
            lh,
        )
        validate_error(err, ApiErrorId.ERR_USAGE_REPORT_OVERLAP.value)

    def test_disjoint_windows_do_not_collide(self, api):
        """PRD §2.7: "Usage reports collide under aggregate-coverage semantics.
        A usage report's proposed window from `period_start` through
        `period_end` may not share any single day — both ends inclusive — with
        any other usage report of the same licensee that is in SUBMITTED,
        ACCEPTED, or AMENDED status."

        Design: Difficulty/resource_temporal_overlap/usage_report_inclusive_day_coverage
        """
        create_effective_schedule()
        lic = create_active_licensee(legal_name="InclCo2")
        lh = make_licensee_headers(lic["id"])
        r1, _ = create_report_with_lines(
            lic["id"],
            [{"isrc": "NM-J1", "track_title": "j1", "artist_name": "j1",
              "performance_count": 10}],
            "2026-06-01T00:00:00Z",
            "2026-06-30T00:00:00Z",
        )
        validate_success(api.submit_usage_report(r1["id"], lh))
        r2, _ = create_report_with_lines(
            lic["id"],
            [{"isrc": "NM-J2", "track_title": "j2", "artist_name": "j2",
              "performance_count": 10}],
            "2026-07-01T00:00:00Z",
            "2026-07-30T00:00:00Z",
        )
        submitted = validate_success(api.submit_usage_report(r2["id"], lh))
        assert submitted["report_status"] == "SUBMITTED"
