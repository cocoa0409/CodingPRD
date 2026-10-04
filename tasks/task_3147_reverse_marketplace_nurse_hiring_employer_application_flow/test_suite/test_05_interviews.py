"""Interview scheduling: buffered per-nurse overlap and unit day-capacity."""
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import ApiErrorId
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.factories import create_interview_payload
from test_helpers.test_users import make_candidate_headers, make_employer_headers


def _make_day_filled_unit(api, day="2026-09-10", starts=("08", "10", "12", "14", "16", "18")):
    """Six distinct nurses each holding one UNDER_REVIEW application on one
    requisition, each with a SCHEDULED interview on `day` at the given hours.
    Returns the shared context plus the list of per-nurse contexts."""
    fx.set_clock()
    employer = fx.create_employer()
    req = fx.create_requisition(employer, openings_total=20)
    unit_ctxs = []
    for i, hour in enumerate(starts):
        nurse = fx.setup_active_nurse(email=f"u{i}@x.com", years_experience=3)["nurse"]
        app = fx.create_application(req, nurse, employer)
        app = fx.review_application(app, nurse)
        iv = fx.schedule_interview(
            app, employer,
            starts_at=f"{day}T{hour}:00:00Z",
            ends_at=f"{day}T{int(hour) + 1:02d}:00:00Z",
        )
        unit_ctxs.append({"nurse": nurse, "application": app, "interview": iv})
    return {"employer": employer, "requisition": req, "unit_ctxs": unit_ctxs}


def _extra_under_review_application(shared, email):
    nurse = fx.setup_active_nurse(email=email, years_experience=3)["nurse"]
    app = fx.create_application(shared["requisition"], nurse, shared["employer"])
    app = fx.review_application(app, nurse)
    return {"nurse": nurse, "application": app}


class TestInterviewDurationBounds:
    def test_duration_outside_30_240_minutes_rejected(self, api):
        """PRD §3.5: "`starts_at` must be strictly after clock now at scheduling time, `ends_at` must be strictly after `starts_at`, and the duration between them must be at least 30 minutes and at most 240 minutes — a duration outside that band is rejected with `ERR_TERMS_MISMATCH`."

        Design: Corner/state_machines/interview_duration_outside_30_240_minutes_rejected
        """
        ctx = fx.setup_application_under_review()
        app, employer, nurse = ctx["application"], ctx["employer"], ctx["nurse"]

        too_short = api_client.schedule_interview(
            app["id"],
            create_interview_payload(
                starts_at="2026-09-02T10:00:00Z", ends_at="2026-09-02T10:15:00Z"
            ),
            make_employer_headers(employer["id"]),
        )
        validate_error(too_short, ApiErrorId.ERR_TERMS_MISMATCH)

        too_long = api_client.schedule_interview(
            app["id"],
            create_interview_payload(
                starts_at="2026-09-02T10:00:00Z", ends_at="2026-09-02T15:00:00Z"
            ),
            make_employer_headers(employer["id"]),
        )
        validate_error(too_long, ApiErrorId.ERR_TERMS_MISMATCH)

        ok = validate_success(
            api_client.schedule_interview(
                app["id"],
                create_interview_payload(
                    starts_at="2026-09-02T10:00:00Z", ends_at="2026-09-02T10:30:00Z"
                ),
                make_employer_headers(employer["id"]),
            ),
            expected_status=201,
        )
        assert ok["status"] == "SCHEDULED"

        after = validate_success(
            api_client.get_application(app["id"], make_candidate_headers(nurse["id"]))
        )
        assert after["status"] == "INTERVIEWING"


class TestBufferedOverlap:
    def test_nurse_interview_buffered_half_open_overlap(self, api):
        """PRD §3.5: "Each existing interval is expanded by a 30-minute buffer on both sides, and the new interval collides if it overlaps any buffered existing interval: the new `starts_at` falling before the existing end plus 30 minutes while the existing start minus 30 minutes falls before the new `ends_at` constitutes overlap. Adjacency at exactly the buffer's edge is permitted — a new interview starting at the precise instant 30 minutes after an existing interview's end is accepted, because the comparison is strict on the buffered half-open form. A collision is rejected with `ERR_INTERVIEW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/nurse_interview_buffered_half_open_overlap
        """
        ctx = fx.setup_application_interviewing()
        nurse = ctx["nurse"]

        employer2 = fx.create_employer(
            legal_name="Coastal General", fee_model="SUBSCRIPTION",
            subscription_tier="PRO", guarantee_days=90, placement_fee_bps=1500,
        )
        req2 = fx.create_requisition(
            employer2, unit_name="ICU-North", distance_from_facility_miles=30,
            offered_hourly_rate_cents=8200, openings_total=1,
        )
        app2 = fx.create_application(req2, nurse, employer2, proposed_hourly_rate_cents=8300)
        fx.review_application(app2, nurse)

        inside_buffer = api_client.schedule_interview(
            app2["id"],
            create_interview_payload(
                starts_at="2026-09-02T11:15:00Z", ends_at="2026-09-02T12:15:00Z"
            ),
            make_employer_headers(employer2["id"]),
        )
        validate_error(inside_buffer, ApiErrorId.ERR_INTERVIEW_CONFLICT)

        at_buffer_edge = api_client.schedule_interview(
            app2["id"],
            create_interview_payload(
                starts_at="2026-09-02T11:30:00Z", ends_at="2026-09-02T12:30:00Z"
            ),
            make_employer_headers(employer2["id"]),
        )
        validate_success(at_buffer_edge, expected_status=201)

    def test_overlap_applies_across_all_of_the_nurses_applications(self, api):
        """PRD §3.5: "Collect every interview in `SCHEDULED` across all of that nurse's applications — not just the one at hand."

        Design: Difficulty/resource_temporal_overlap/nurse_interview_buffered_half_open_overlap
        """
        ctx = fx.setup_application_interviewing()
        nurse, employer1 = ctx["nurse"], ctx["employer"]
        app1 = ctx["application"]  # INTERVIEWING with interview 2026-09-02T10:00-11:00Z

        employer2 = fx.create_employer(
            legal_name="Coastal General", fee_model="SUBSCRIPTION",
            subscription_tier="PRO", guarantee_days=90, placement_fee_bps=1500,
        )
        req2 = fx.create_requisition(
            employer2, unit_name="ICU-North", offered_hourly_rate_cents=8200, openings_total=1,
        )
        app2 = fx.create_application(req2, nurse, employer2, proposed_hourly_rate_cents=8300)
        fx.review_application(app2, nurse)

        direct_overlap = api_client.schedule_interview(
            app2["id"],
            create_interview_payload(
                starts_at="2026-09-02T10:30:00Z", ends_at="2026-09-02T11:30:00Z"
            ),
            make_employer_headers(employer2["id"]),
        )
        validate_error(direct_overlap, ApiErrorId.ERR_INTERVIEW_CONFLICT)


class TestUnitDayCapacity:
    def test_unit_day_capacity_zero_remaining_rejects(self, api):
        """PRD §3.5: "For the requisition's unit — the (`facility_state`, `unit_name`) pair — a calendar day accepts at most 6 interview-starts, counted across all applications of all requisitions sharing that pair. Only interviews in `SCHEDULED` or `COMPLETED` whose `starts_at` calendar day equals the new interview's start day count toward the bucket. The day window is the closed interval from 00:00 through 23:59 of that day on the logical clock: an interview starting at exactly 23:59 counts toward that day, and one starting at exactly 00:00 counts toward the new day, not the previous one. When the target day already carries 6 such interview-starts, the scheduling is rejected with `ERR_UNIT_DAY_CAPACITY` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/unit_day_capacity_zero_remaining_rejects
        """
        shared = _make_day_filled_unit(api)
        employer = shared["employer"]
        extra = _extra_under_review_application(shared, "u7@x.com")

        seventh = api_client.schedule_interview(
            extra["application"]["id"],
            create_interview_payload(
                starts_at="2026-09-10T20:00:00Z", ends_at="2026-09-10T21:00:00Z"
            ),
            make_employer_headers(employer["id"]),
        )
        validate_error(seventh, ApiErrorId.ERR_UNIT_DAY_CAPACITY)

        next_day = api_client.schedule_interview(
            extra["application"]["id"],
            create_interview_payload(
                starts_at="2026-09-11T00:00:00Z", ends_at="2026-09-11T01:00:00Z"
            ),
            make_employer_headers(employer["id"]),
        )
        validate_success(next_day, expected_status=201)

        for unit_ctx in shared["unit_ctxs"]:
            iv = validate_success(
                api_client.get_interview(
                    unit_ctx["interview"]["id"], make_employer_headers(employer["id"])
                )
            )
            assert iv["status"] == "SCHEDULED", "rejection must be side-effect free"

    def test_unit_day_bucket_closed_boundary_vs_nurse_buffer(self, api):
        """PRD §3.5: "The second rule protects the unit's daily capacity, and its semantics are deliberately different from the per-nurse rule: there is no buffer and no interval arithmetic at all, only a start-day bucket count."
        PRD §3.5: "The day window is the closed interval from 00:00 through 23:59 of that day on the logical clock: an interview starting at exactly 23:59 counts toward that day, and one starting at exactly 00:00 counts toward the new day, not the previous one."

        Design: Difficulty/resource_temporal_overlap/unit_day_bucket_closed_boundary_vs_nurse_buffer
        """
        shared = _make_day_filled_unit(api)
        employer = shared["employer"]
        extra = _extra_under_review_application(shared, "v7@x.com")

        # 19:30 start clears the per-nurse buffer (19:00 end + 30min == 19:30,
        # gap exactly 0) but lands in the already-full 2026-09-10 day bucket.
        full_bucket = api_client.schedule_interview(
            extra["application"]["id"],
            create_interview_payload(
                starts_at="2026-09-10T19:30:00Z", ends_at="2026-09-10T20:30:00Z"
            ),
            make_employer_headers(employer["id"]),
        )
        validate_error(full_bucket, ApiErrorId.ERR_UNIT_DAY_CAPACITY)

        fresh_bucket = api_client.schedule_interview(
            extra["application"]["id"],
            create_interview_payload(
                starts_at="2026-09-11T00:00:00Z", ends_at="2026-09-11T01:00:00Z"
            ),
            make_employer_headers(employer["id"]),
        )
        validate_success(fresh_bucket, expected_status=201)


    def test_seventh_interview_in_bucket_rejected_day_boundary_resets(self, api):
        """PRD §3.5: "For the requisition's unit — the (`facility_state`, `unit_name`) pair — a calendar day accepts at most 6 interview-starts, counted across all applications of all requisitions sharing that pair."
        PRD §3.5: "The day window is the closed interval from 00:00 through 23:59 of that day on the logical clock: an interview starting at exactly 23:59 counts toward that day, and one starting at exactly 00:00 counts toward the new day, not the previous one."

        Design: Difficulty/boundary_precision_check/unit_day_capacity_zero_remaining_rejects
        """
        shared = _make_day_filled_unit(api)
        employer = shared["employer"]
        extra = _extra_under_review_application(shared, "u8@x.com")

        # Seventh start on the same calendar day: the bucket is full.
        seventh = api_client.schedule_interview(
            extra["application"]["id"],
            create_interview_payload(
                starts_at="2026-09-10T20:00:00Z", ends_at="2026-09-10T21:00:00Z"
            ),
            make_employer_headers(employer["id"]),
        )
        validate_error(seventh, ApiErrorId.ERR_UNIT_DAY_CAPACITY, 409)

        # Exactly 00:00 the next day belongs to a fresh bucket.
        next_day = validate_success(
            api_client.schedule_interview(
                extra["application"]["id"],
                create_interview_payload(
                    starts_at="2026-09-11T00:00:00Z", ends_at="2026-09-11T01:00:00Z"
                ),
                make_employer_headers(employer["id"]),
            ),
            expected_status=201,
        )
        assert next_day["status"] == "SCHEDULED"


    def test_midnight_start_belongs_to_new_day_despite_per_nurse_buffer(self, api):
        """PRD §3.5: "The day window is the closed interval from 00:00 through 23:59 of that day on the logical clock: an interview starting at exactly 23:59 counts toward that day, and one starting at exactly 00:00 counts toward the new day, not the previous one."
        PRD §3.5: "Adjacency at exactly the buffer's edge is permitted — a new interview starting at the precise instant 30 minutes after an existing interview's end is accepted, because the comparison is strict on the buffered half-open form."

        Design: Difficulty/resource_temporal_overlap/unit_day_bucket_closed_boundary_vs_nurse_buffer
        """
        shared = _make_day_filled_unit(api)
        employer = shared["employer"]
        extra = _extra_under_review_application(shared, "v8@x.com")

        # The 2026-09-10 bucket is full; a start at exactly 00:00 the next day
        # is counted toward the fresh bucket and is accepted.
        midnight = validate_success(
            api_client.schedule_interview(
                extra["application"]["id"],
                create_interview_payload(
                    starts_at="2026-09-11T00:00:00Z", ends_at="2026-09-11T01:00:00Z"
                ),
                make_employer_headers(employer["id"]),
            ),
            expected_status=201,
        )
        assert midnight["status"] == "SCHEDULED"


class TestInterviewCompletionWindow:
    def test_complete_before_window_end_rejected(self, api):
        """PRD §3.5: "An interview in `SCHEDULED` may be completed by the employer once the clock has reached its `ends_at`, moving it to `COMPLETED` — completion attempted before the window has passed is rejected with `ERR_DEADLINE_PASSED`."

        Design: Corner/state_machines/interview_complete_before_window_end_rejected
        """
        ctx = fx.setup_application_interviewing()
        iv, employer = ctx["interview"], ctx["employer"]

        fx.set_clock("2026-09-02T10:59:00Z")
        early = api_client.complete_interview(iv["id"], make_employer_headers(employer["id"]))
        validate_error(early, ApiErrorId.ERR_DEADLINE_PASSED)

        fx.set_clock("2026-09-02T11:00:00Z")
        completed = validate_success(
            api_client.complete_interview(iv["id"], make_employer_headers(employer["id"]))
        )
        assert completed["status"] == "COMPLETED"
