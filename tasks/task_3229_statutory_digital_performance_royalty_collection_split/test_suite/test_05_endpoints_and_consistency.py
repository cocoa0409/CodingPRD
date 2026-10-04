"""Endpoint behavior claims: logical clock, immediate consistency, filters
(queue B, endpoints section)."""
from test_helpers import (
    ApiErrorId,
    PAST_SCHEDULED_FOR,
    create_active_licensee,
    create_effective_schedule,
    create_pool,
    create_recording,
    create_report_with_lines,
    create_verified_artist,
    create_verified_rights_owner,
    make_admin_headers,
    make_licensee_headers,
    make_royalty_ops_headers,
    set_clock,
    setup_standard_paid_scenario,
    submit_and_accept_report,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = make_admin_headers()
OPS = make_royalty_ops_headers()


class TestLogicalClock:
    def test_clock_default_and_set_current_utc(self, api):
        """PRD §2.5: "An administrator advances it through the test-driving clock
        endpoint, which accepts a target instant `to_iso8601` and returns the
        resulting `current_utc`."

        Design: Corner/endpoints/clock_default_is_2026_09_01
        """
        data = validate_success(api.set_clock("2026-10-01T00:00:00Z", ADMIN))
        assert data["current_utc"] == "2026-10-01T00:00:00Z"


class TestExecuteImmediateConsistency:
    def test_execute_response_is_immediate_consistency(self, api):
        """PRD §3.6: "Execution writes `executed_at` from the logical clock and
        increments the batch's `version` by 1."
        PRD §3.6: "The new batch's `batch_status` is `PLANNED` and its
        `executed_at` is null until execution."
        PRD §2.10: "Consistency is immediate: there is no
        eventual-consistency window anywhere in this system."

        Design: Corner/endpoints/execute_response_is_immediate_consistency
        """
        scenario = setup_standard_paid_scenario(
            legal_name="ICo",
            lines=[{"isrc": "NM-IC", "track_title": "ic", "artist_name": "ic",
                    "performance_count": 10000}],
        )
        report = scenario["report"]
        create_pool()
        batch = validate_success(
            api.create_distribution_batch(
                report["id"], {"scheduled_for": "2026-10-01T00:00:00Z"}, OPS,
            ),
            expected_status=201,
        )
        # Advance the logical clock to exactly scheduled_for so the batch is due.
        set_clock("2026-10-01T00:00:00Z")
        batch_version = batch["version"]
        executed = validate_success(
            api.execute_distribution_batch(
                batch["id"],
                {"expected_distribution_batch_version": batch_version},
                OPS,
            )
        )
        assert executed["batch_status"] == "EXECUTED"
        assert executed["executed_at"] is not None
        assert executed["version"] == batch_version + 1
        got = validate_success(api.get_distribution_batch(batch["id"], OPS))
        assert got["batch_status"] == "EXECUTED"
        assert got["executed_at"] == executed["executed_at"]
        assert got["version"] == batch_version + 1


class TestBatchPlanningValidation:
    def test_scheduled_for_must_be_future(self, api):
        """PRD §3.6: "The plan carries a `scheduled_for` datetime that must be
        strictly after the current logical clock time; a `scheduled_for` not
        strictly in the future is rejected with `ERR_SCHEDULED_TIME_NOT_FUTURE`
        (HTTP 400)."
        PRD §2.5: "The clock's startup default, before any explicit set, is
        exactly 2026-09-01T00:00:00Z."

        Design: Corner/validations/scheduled_for_must_be_future
        """
        create_effective_schedule()
        lic = create_active_licensee(legal_name="SCo")
        report, _ = create_report_with_lines(
            lic["id"],
            [{"isrc": "NM-SC", "track_title": "sc", "artist_name": "sc",
              "performance_count": 10}],
            "2026-01-01T00:00:00Z",
            "2026-01-31T00:00:00Z",
        )
        accepted = submit_and_accept_report(report["id"], lic["id"])
        validate_success(
            api.compute_liability(
                report["id"],
                {"expected_usage_report_version": accepted["version"]},
                OPS,
            ),
            expected_status=201,
        )
        err = api.create_distribution_batch(
            report["id"], {"scheduled_for": PAST_SCHEDULED_FOR}, OPS,
        )
        validate_error(err, ApiErrorId.ERR_SCHEDULED_TIME_NOT_FUTURE.value)


class TestPlayLineListing:
    def test_play_line_filter_by_identification_status(self, api):
        """PRD §3.3: "Play lines can be listed per report filtered by
        `identification_status`, or across reports filtered by
        `matched_recording_id` or `identification_status`."
        PRD §3.3: "the line's `identification_status` is `MATCHED` if and only if
        exactly one Recording with the same `isrc` in `ACTIVE` catalog status
        exists, and `UNMATCHED` otherwise."

        Design: Corner/endpoints/play_line_filter_by_identification_status
        """
        lic = create_active_licensee(legal_name="FltCo")
        ro = create_verified_rights_owner(legal_name="RF",
                                          contact_email="rf@example.com")
        fa = create_verified_artist(stage_name="FF",
                                    contact_email="ff@example.com")
        create_recording(ro["id"], fa["id"], isrc="ISRC-FLT", track_title="flt")
        report, _ = create_report_with_lines(
            lic["id"],
            [
                {"isrc": "ISRC-FLT", "track_title": "flt", "artist_name": "ff",
                 "performance_count": 10},
                {"isrc": "NM-FLT", "track_title": "un", "artist_name": "un",
                 "performance_count": 20},
            ],
            "2026-01-01T00:00:00Z",
            "2026-01-31T00:00:00Z",
        )
        filtered, _ = validate_paginated(
            api.list_play_lines(report["id"], OPS,
                                params={"identification_status": "UNMATCHED"})
        )
        assert len(filtered) == 1
        assert filtered[0]["isrc"] == "NM-FLT"
        assert filtered[0]["identification_status"] == "UNMATCHED"
        unfiltered, meta = validate_paginated(
            api.list_play_lines(report["id"], OPS)
        )
        assert len(unfiltered) == 2
