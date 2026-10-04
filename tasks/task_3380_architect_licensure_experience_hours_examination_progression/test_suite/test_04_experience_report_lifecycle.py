"""Experience report lifecycle: creation defaults, state legality, ranges,
verify consistency, supervisor ownership, list envelope (PRD §2.2, §2.3,
§3.3)."""
from test_helpers import (
    ApiErrorId, FULL_CREDIT_PCT, LOGICAL_CLOCK_START_DATE,
    MAX_HOURS_PER_REPORT, MIN_HOURS_PER_REPORT, PAGINATION_DEFAULT_LIMIT,
    assert_experience_report, create_active_supervisor, create_candidate,
    create_draft_report, create_jurisdiction, create_submitted_report,
    create_verified_report, make_candidate_headers,
    make_supervisor_headers, validate_error, validate_paginated,
    validate_success,
)

J1 = "J1"


def _registry(api):
    create_jurisdiction(code=J1)
    candidate = create_candidate(home_jurisdiction_code=J1)
    supervisor = create_active_supervisor(jurisdiction_code=J1)
    return candidate, supervisor


class TestReportCreationShape:
    def test_report_initial_state_is_draft(self, api):
        """PRD §3.3: "New reports are `DRAFT`, with `submitted_at` null,
        `credit_pct` 0, `credited_hours` 0, and `return_reason` null."

        Design: Corner/state_machines/report_initial_state_is_draft
        """
        candidate, supervisor = _registry(api)
        data = validate_success(api.create_experience_report(
            {
                "candidate_id": candidate["id"],
                "supervisor_id": supervisor["id"],
                "practice_area": "PRACTICE_MANAGEMENT",
                "hours": 40,
                "work_period_start": "2026-01-05",
                "work_period_end": "2026-02-02",
            },
            make_candidate_headers(candidate["id"]),
        ), expected_status=201)
        assert_experience_report(data)
        assert data["status"] == "DRAFT"
        assert data["submitted_at"] is None
        assert data["credit_pct"] == 0
        assert data["credited_hours"] == 0
        assert data["return_reason"] is None

    def test_report_hours_range_enforced(self, api):
        """PRD §3.3: "A single report must carry at least 1 hour and at most
        2000 hours; anything outside that range is rejected with
        `ERR_HOURS_OUT_OF_RANGE`."

        Design: Corner/validations/report_hours_range_enforced
        """
        candidate, supervisor = _registry(api)
        ch = make_candidate_headers(candidate["id"])

        def create_with_hours(hours):
            return api.create_experience_report(
                {
                    "candidate_id": candidate["id"],
                    "supervisor_id": supervisor["id"],
                    "practice_area": "PRACTICE_MANAGEMENT",
                    "hours": hours,
                    "work_period_start": "2026-01-05",
                    "work_period_end": "2026-02-02",
                },
                ch,
            )

        validate_error(
            create_with_hours(MIN_HOURS_PER_REPORT - 1),
            ApiErrorId.ERR_HOURS_OUT_OF_RANGE,
        )
        validate_error(
            create_with_hours(MAX_HOURS_PER_REPORT + 1),
            ApiErrorId.ERR_HOURS_OUT_OF_RANGE,
        )
        data = validate_success(
            create_with_hours(MAX_HOURS_PER_REPORT), expected_status=201,
        )
        assert data["status"] == "DRAFT", "upper boundary 2000 is inclusive"

    def test_work_period_inverted_rejected(self, api):
        """PRD §3.3: "The `work_period_end` must fall strictly after
        `work_period_start`, failing which the create is rejected with
        `ERR_WORK_PERIOD_INVALID`."

        Design: Corner/validations/work_period_inverted_rejected
        """
        candidate, supervisor = _registry(api)
        validate_error(
            api.create_experience_report(
                {
                    "candidate_id": candidate["id"],
                    "supervisor_id": supervisor["id"],
                    "practice_area": "PRACTICE_MANAGEMENT",
                    "hours": 40,
                    "work_period_start": "2026-02-02",
                    "work_period_end": "2026-02-02",
                },
                make_candidate_headers(candidate["id"]),
            ),
            ApiErrorId.ERR_WORK_PERIOD_INVALID,
        )


class TestReportStateLegality:
    def test_report_double_submit_rejected(self, api):
        """PRD §2.6: "The target resource's current state must permit the
        attempted transition; any trigger attempted from a state that does not
        list it is rejected with the generic `ERR_INVALID_STATE` (HTTP 409)."
        PRD §3.3: "A successful submission moves the report to `SUBMITTED`,
        stamps `submitted_at` with the current logical-clock instant, and
        locks the credit percentage into `credit_pct` according to how quickly
        the hours were reported".

        Design: Corner/state_machines/report_double_submit_rejected
        """
        candidate, supervisor = _registry(api)
        ch = make_candidate_headers(candidate["id"])
        report = create_submitted_report(
            candidate, supervisor, "PRACTICE_MANAGEMENT", 40,
            "2026-01-05", "2026-02-02",
        )
        assert report["credit_pct"] == FULL_CREDIT_PCT
        assert report["submitted_at"].startswith(LOGICAL_CLOCK_START_DATE)
        validate_error(
            api.submit_experience_report(report["id"], ch),
            ApiErrorId.ERR_INVALID_STATE,
        )
        after = validate_success(api.get_experience_report(report["id"], ch))
        assert after["status"] == "SUBMITTED"
        assert after["submitted_at"] == report["submitted_at"], (
            "rejected re-submit must not restamp submitted_at"
        )
        assert after["credit_pct"] == FULL_CREDIT_PCT, "locked tier untouched"

    def test_verify_from_draft_rejected(self, api):
        """PRD §3.3: "verifying a report that is not `SUBMITTED` is an
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/verify_from_draft_rejected
        """
        candidate, supervisor = _registry(api)
        report = create_draft_report(
            candidate, supervisor, "PRACTICE_MANAGEMENT", 40,
            "2026-01-05", "2026-02-02",
        )
        validate_error(
            api.verify_experience_report(
                report["id"], make_supervisor_headers(supervisor["id"]),
            ),
            ApiErrorId.ERR_INVALID_STATE,
        )
        after = validate_success(api.get_experience_report(
            report["id"], make_supervisor_headers(supervisor["id"]),
        ))
        assert after["status"] == "DRAFT"
        assert after["credited_hours"] == 0

    def test_return_of_verified_terminal_rejected(self, api):
        """PRD §3.3: "A successful verification moves the report to its
        terminal `VERIFIED` state and stamps `credited_hours`".
        PRD §2.6: "The target resource's current state must permit the
        attempted transition; any trigger attempted from a state that does not
        list it is rejected with the generic `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/return_of_verified_terminal_rejected
        """
        candidate, supervisor = _registry(api)
        report = create_verified_report(
            candidate, supervisor, "PRACTICE_MANAGEMENT", 40,
            "2026-01-05", "2026-02-02",
        )
        assert report["credited_hours"] == 40
        validate_error(
            api.return_experience_report(
                report["id"], {"return_reason": "too late"},
                make_supervisor_headers(supervisor["id"]),
            ),
            ApiErrorId.ERR_INVALID_STATE,
        )
        after = validate_success(api.get_experience_report(
            report["id"], make_supervisor_headers(supervisor["id"]),
        ))
        assert after["status"] == "VERIFIED"
        assert after["credited_hours"] == 40


class TestVerifyConsistencyAndOwnership:
    def test_verify_response_reflects_credited_hours_immediately(self, api):
        """PRD §3.3: "A successful verification moves the report to its
        terminal `VERIFIED` state and stamps `credited_hours`: the report's
        `hours` are multiplied by the locked `credit_pct` percentage and the
        product is rounded half-up to a whole hour, per report, before any
        aggregation."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the
        data field."

        Design: Corner/consistency_model/verify_response_reflects_credited_hours_immediately
        """
        candidate, supervisor = _registry(api)
        report = create_submitted_report(
            candidate, supervisor, "PRACTICE_MANAGEMENT", 40,
            "2026-01-05", "2026-02-02",
        )
        sh = make_supervisor_headers(supervisor["id"])
        data = validate_success(api.verify_experience_report(report["id"], sh))
        assert data["status"] == "VERIFIED"
        assert data["credited_hours"] == 40
        assert data["credit_pct"] == FULL_CREDIT_PCT
        reread = validate_success(api.get_experience_report(report["id"], sh))
        assert reread["status"] == data["status"]
        assert reread["credited_hours"] == data["credited_hours"]
        assert reread["credit_pct"] == data["credit_pct"], "no drift on re-read"

    def test_supervisor_cannot_verify_unassigned_report(self, api):
        """PRD §3.3: "The caller's `X-User-ID` must equal the report's
        `supervisor_id`, failing which the rejection is
        `ERR_SUPERVISOR_MISMATCH`".

        Design: Corner/rbac/supervisor_cannot_verify_unassigned_report
        """
        candidate, supervisor = _registry(api)
        other = create_active_supervisor(jurisdiction_code=J1)
        report = create_submitted_report(
            candidate, supervisor, "PRACTICE_MANAGEMENT", 40,
            "2026-01-05", "2026-02-02",
        )
        validate_error(
            api.verify_experience_report(
                report["id"], make_supervisor_headers(other["id"]),
            ),
            ApiErrorId.ERR_SUPERVISOR_MISMATCH,
        )
        after = validate_success(api.get_experience_report(
            report["id"], make_supervisor_headers(supervisor["id"]),
        ))
        assert after["status"] == "SUBMITTED"
        assert after["credited_hours"] == 0


class TestListEnvelope:
    def test_list_envelope_and_pagination_defaults(self, api):
        """PRD §2.3: "The `limit` parameter defaults to 10, must be at least
        1, and may not exceed 100; the `offset` parameter defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`, where
        `total_count` is the number of matching records before pagination and
        `has_more` indicates whether further records exist beyond the returned
        window."
        PRD §3.3: "Experience reports may be listed with `candidate_id`,
        `supervisor_id`, `status`, and `practice_area` filters alongside
        `limit` and `offset`."

        Design: Corner/endpoints/list_envelope_and_pagination_defaults
        """
        candidate, supervisor = _registry(api)
        other_candidate = create_candidate(home_jurisdiction_code=J1)
        ch = make_candidate_headers(candidate["id"])
        create_draft_report(
            candidate, supervisor, "PRACTICE_MANAGEMENT", 40,
            "2026-01-05", "2026-02-02",
        )
        create_draft_report(
            candidate, supervisor, "PROJECT_MANAGEMENT", 40,
            "2026-02-02", "2026-03-02",
        )
        create_draft_report(
            other_candidate, supervisor, "PRACTICE_MANAGEMENT", 40,
            "2026-01-05", "2026-02-02",
        )

        resp = api.list_experience_reports(ch, params={"candidate_id": candidate["id"]})
        assert resp.status_code == 200
        body = resp.json()
        assert body["response_type"] == "array"
        assert isinstance(body["meta"].get("api_request_id"), str)
        rows, meta = validate_paginated(resp)
        assert meta["limit"] == PAGINATION_DEFAULT_LIMIT, "default limit"
        assert meta["offset"] == 0, "default offset"
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert len(rows) == 2
        assert all(r["candidate_id"] == candidate["id"] for r in rows), (
            "candidate_id filter returns only this candidate's reports"
        )

        resp2 = api.list_experience_reports(
            ch, params={"candidate_id": candidate["id"], "limit": 1, "offset": 1},
        )
        rows2, meta2 = validate_paginated(resp2)
        assert len(rows2) == 1
        assert meta2["total_count"] == 2
        assert meta2["limit"] == 1
        assert meta2["offset"] == 1
        assert meta2["has_more"] is False, "page 2 of 2 has nothing beyond it"
